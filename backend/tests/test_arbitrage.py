import pytest
from decimal import Decimal
from datetime import datetime, timezone, date
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient

from backend.main import app
from backend.app.db.session import Base
from backend.app.db.models import Bond, PriceSnapshot, ArbitrageSignal, MacroIndicator
from backend.app.schemas.snapshot import BondQuoteView
from backend.app.arbitrage.strategies import ArbitrageStrategies
from backend.app.arbitrage.engine import ArbitrageEngine
from backend.app.services.ingestion_service import IngestionService

TEST_DB_URL = "sqlite:///:memory:"

@pytest.fixture
def db_session():
    engine = create_engine(TEST_DB_URL, connect_args={"check_same_thread": False})
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)

def test_law_premium_rule_a_compression():
    """Verifica Regla A: Compresión de ratio legal <= 1.01 dispara ROTAR_A_NY."""
    quotes = {
        "AL30": BondQuoteView(
            ticker="AL30", name="Bonar 2030", bond_type="HARD_DOLLAR", law="ARG", settlement_type="24hs",
            price_mep=54.50, last_price=54.50, ytm_percentage=19.5
        ),
        "GD30": BondQuoteView(
            ticker="GD30", name="Global 2030", bond_type="HARD_DOLLAR", law="NY", settlement_type="24hs",
            price_mep=54.60, last_price=54.60, ytm_percentage=19.4 # Ratio = 54.60 / 54.50 = 1.0018 <= 1.01
        )
    }

    signals = ArbitrageStrategies.evaluate_law_premium(quotes)
    assert len(signals) == 1
    sig = signals[0]
    assert sig.strategy_name == "LAW_PREMIUM"
    assert sig.action_recommended == "ROTAR_A_NY"
    assert sig.leg_sell_ticker == "AL30"
    assert sig.leg_buy_ticker == "GD30"
    assert sig.metric_value <= Decimal("1.01")

def test_law_premium_rule_b_expansion():
    """Verifica Regla B: Ensanchamiento de ratio legal >= 1.12 dispara ROTAR_A_ARG."""
    quotes = {
        "AL30": BondQuoteView(
            ticker="AL30", name="Bonar 2030", bond_type="HARD_DOLLAR", law="ARG", settlement_type="24hs",
            price_mep=50.00, last_price=50.00, ytm_percentage=22.0
        ),
        "GD30": BondQuoteView(
            ticker="GD30", name="Global 2030", bond_type="HARD_DOLLAR", law="NY", settlement_type="24hs",
            price_mep=57.00, last_price=57.00, ytm_percentage=17.0 # Ratio = 57 / 50 = 1.14 >= 1.12
        )
    }

    signals = ArbitrageStrategies.evaluate_law_premium(quotes)
    assert len(signals) == 1
    sig = signals[0]
    assert sig.strategy_name == "LAW_PREMIUM"
    assert sig.action_recommended == "ROTAR_A_ARG"
    assert sig.leg_sell_ticker == "GD30"
    assert sig.leg_buy_ticker == "AL30"
    assert sig.metric_value >= Decimal("1.12")

def test_relative_value_short_end():
    """Verifica Estrategia 2: Spread AL30 vs GD29 > 130 bps activa SWAP_DURACION."""
    quotes = {
        "AL30": BondQuoteView(
            ticker="AL30", name="Bonar 2030", bond_type="HARD_DOLLAR", law="ARG", settlement_type="24hs",
            price_mep=52.72, ytm_percentage=12.90, modified_duration=1.66
        ),
        "GD29": BondQuoteView(
            ticker="GD29", name="Global 2029", bond_type="HARD_DOLLAR", law="NY", settlement_type="24hs",
            price_mep=53.70, ytm_percentage=9.67, modified_duration=1.29 # Spread = 12.90 - 9.67 = 3.23% = 323 bps > 130 bps
        )
    }

    signals = ArbitrageStrategies.evaluate_relative_value_curve(quotes)
    assert len(signals) == 1
    sig = signals[0]
    assert sig.strategy_name == "RELATIVE_VALUE_CURVE"
    assert sig.leg_sell_ticker == "GD29"
    assert sig.leg_buy_ticker == "AL30"
    assert sig.action_recommended == "SWAP_DURACION"
    assert sig.metric_value >= Decimal("130.0")

def test_breakeven_inflation_strategy():
    """Verifica Estrategia 3: Posicionamiento CER vs Tasa Fija."""
    quotes = {
        "S30N6": BondQuoteView(
            ticker="S30N6", name="LECAP Noviembre", bond_type="TASA_FIJA", law="ARG", settlement_type="24hs",
            ytm_percentage=26.8 # ~26.8% anual
        ),
        "TZX27": BondQuoteView(
            ticker="TZX27", name="BONCER 2027", bond_type="CER", law="ARG", settlement_type="24hs",
            ytm_percentage=7.5 # ~7.5% real anual -> Breakeven mensual ~1.38%
        )
    }

    # Si la inflación mensual esperada es 2.8% (> 1.38% + 0.15%):
    sig_cer = ArbitrageStrategies.evaluate_breakeven_inflation(quotes, expected_monthly_inflation_pct=2.8)
    assert len(sig_cer) == 1
    assert sig_cer[0].action_recommended == "COMPRAR_CER"
    assert sig_cer[0].leg_buy_ticker == "TZX27"

    # Si la inflación mensual esperada es 1.0% (< 1.38% - 0.15%):
    sig_fix = ArbitrageStrategies.evaluate_breakeven_inflation(quotes, expected_monthly_inflation_pct=1.0)
    assert len(sig_fix) == 1
    assert sig_fix[0].action_recommended == "COMPRAR_TASA_FIJA"
    assert sig_fix[0].leg_buy_ticker == "S30N6"

def test_dual_bonds_strategy():
    """Verifica Estrategia 4: Bono Dual con descuento en paridad activa COMPRAR_DUAL."""
    quotes = {
        "TXMD8": BondQuoteView(
            ticker="TXMD8", name="Dual Mayo 2028", bond_type="DUAL", law="ARG", settlement_type="24hs",
            parity_percentage=94.2 # < 96.0%
        )
    }

    signals = ArbitrageStrategies.evaluate_dual_bonds(quotes)
    assert len(signals) == 1
    assert signals[0].action_recommended == "COMPRAR_DUAL"
    assert signals[0].leg_buy_ticker == "TXMD8"

@pytest.mark.asyncio
async def test_arbitrage_engine_execution(db_session):
    """Verifica la persistencia y ciclo completo del ArbitrageEngine en base de datos."""
    ingestion = IngestionService()
    await ingestion.ingest_market_data(db_session)

    engine = ArbitrageEngine(ingestion)
    active_signals = engine.evaluate_all_strategies(db_session)

    assert isinstance(active_signals, list)
    
    # Comprobar consulta en base de datos
    db_signals = db_session.query(ArbitrageSignal).filter(ArbitrageSignal.status == "ACTIVE").all()
    assert len(db_signals) == len(active_signals)

def test_arbitrage_api_endpoints(client):
    """Verifica los endpoints REST del motor de arbitrajes."""
    # 1. Ejecutar evaluación
    eval_res = client.post("/api/v1/arbitrage/evaluate")
    assert eval_res.status_code == 200
    assert eval_res.json()["status"] == "success"

    # 2. Consultar señales activas
    sig_res = client.get("/api/v1/arbitrage/signals")
    assert sig_res.status_code == 200
    assert isinstance(sig_res.json(), list)

    # 3. Consultar Command Center
    cc_res = client.get("/api/v1/arbitrage/command-center")
    assert cc_res.status_code == 200
    cc_data = cc_res.json()
    assert "law_premium_matrix" in cc_data
    assert "relative_value_tramo_corto" in cc_data
    assert len(cc_data["law_premium_matrix"]) == 5

