"""
Bandas de los ratios entre bonos: historia diaria de Rava, banda propia de cada par, filtro de
costos y prueba histórica (la señal solo se emite en los pares donde la banda fue rentable).
"""

import asyncio
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.arbitrage.engine import ArbitrageEngine
from backend.app.arbitrage.market_view import Book, Level, MarketView
from backend.app.arbitrage.ratios import BAND_DAYS, backtest_band, compute_pair_ratios
from backend.app.data.rava_client import parse_history
from backend.app.db.models import DailyClose
from backend.app.db.session import Base
from backend.app.services.price_history_service import PriceHistoryService, history_symbols
from backend.app.services.trading_settings import TradingParams

PARAMS = TradingParams(commission_pct=0.11, min_net_profit_pct=0.40, trade_size_usd=500)
TODAY = date(2026, 11, 4)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    s = sessionmaker(bind=engine)()
    try:
        yield s
    finally:
        s.close()


def bk(symbol, bid, ask, settlement="24HS"):
    return Book(symbol=symbol, base=symbol[:-1], currency="MEP", settlement=settlement,
                bids=[Level(bid, 1e9)], asks=[Level(ask, 1e9)], last=None, trade_time=None,
                timestamp=None, source="BULLMARKET")


def view_of(*books):
    return MarketView(books={(b.symbol, b.settlement): b for b in books}, today=TODAY,
                      next_bd=TODAY + timedelta(days=1), mep_reference=1585.0, caucion_tna_pct=26.0,
                      flows_by_base={})


def load_history(db, a, b, ratios, base_price=50.0):
    """Cierres diarios de A (fijo) y B (= A x ratio), terminando el día anterior a TODAY."""
    start = TODAY - timedelta(days=len(ratios))
    for i, r in enumerate(ratios):
        day = start + timedelta(days=i)
        db.add(DailyClose(symbol=a + "D", day=day, close=base_price))
        db.add(DailyClose(symbol=b + "D", day=day, close=base_price * r))
    db.commit()


def stable_series(n=300):
    """Oscila alrededor de 1,03 y cada 25 ruedas se dispara un día a 1,05 y vuelve."""
    return [1.05 if i % 25 == 24 else 1.03 + (0.002 if i % 2 else -0.002) for i in range(n)]


def trending_series(n=300):
    """Sube de a escalones que no se revierten (cambio de nivel, como los pares largos en 2026)."""
    return [1.00 + 0.012 * (i // 20) + 0.0003 * (i % 20) for i in range(n)]


def pair(ratios, a="AL30", b="GD30"):
    return next(r for r in ratios if (r.a, r.b, r.settlement) == (a, b, "24HS"))


# ---------------------------------------------------------------------------
# Rava
# ---------------------------------------------------------------------------

def test_parse_rava_history():
    text = ("﻿especie,apertura,maximo,minimo,ultimo,fecha,volumen,cierre,timestamp,usd_apertura\n"
            "AL30D-0002-C-CT-USD,51.5,53,51,51.3,2026-11-06,27254145,51.3,1793934000,0.03\n"
            "AL30D-0002-C-CT-USD,52.66,52.66,51.1,51.47,2026-11-05,175136415,51.47,1793847600,0.03\n"
            "AL30D-0002-C-CT-USD,1,1,1,1,fecha-rota,1,1,1,1\n"
            "AL30D-0002-C-CT-USD,1,1,1,1,2026-11-04,1,0,1,1\n")
    assert parse_history(text) == [(date(2026, 11, 5), 51.47), (date(2026, 11, 6), 51.3)]


def test_history_service_refresh_and_staleness(db):
    class FakeRava:
        async def fetch_histories(self, symbols):
            ok = {s: [(date(2026, 11, 2), 50.0), (date(2026, 11, 3), 51.0)] for s in symbols if s != "GD41D"}
            return ok, {"GD41D": "HTTP 500"}

    svc = PriceHistoryService(client=FakeRava())
    assert svc.is_stale(db)
    res = asyncio.run(svc.refresh(db))
    assert res["symbols"] == len(history_symbols()) - 1 and res["errors"] == {"GD41D": "HTTP 500"}
    assert svc.is_stale(db)                          # falta una especie: se reintenta
    db.add(DailyClose(symbol="GD41D", day=date(2026, 11, 3), close=60.0))
    db.commit()
    assert not svc.is_stale(db)
    assert svc.is_stale(db, today=datetime.now(timezone.utc).date() + timedelta(days=2))
    asyncio.run(svc.refresh(db))                     # reemplaza, no duplica
    assert db.query(DailyClose).filter_by(symbol="AL30D").count() == 2


# ---------------------------------------------------------------------------
# Prueba histórica
# ---------------------------------------------------------------------------

def test_backtest_marks_stable_pair_as_reliable():
    t = backtest_band(stable_series(), roundtrip_cost_pct=0.44, min_net_pct=0.40)
    assert t["signals"] >= 5 and t["wins"] == t["signals"] and t["reliable"]
    # entra en 1,05 y sale al día siguiente en 1,028: 2,14% bruto menos 0,44% de las 4 operaciones
    assert t["avg_net_pct"] == pytest.approx((1.05 / 1.028 - 1) * 100 - 0.44, abs=0.05)


def test_backtest_marks_trending_pair_as_unreliable():
    t = backtest_band(trending_series(), roundtrip_cost_pct=0.44, min_net_pct=0.40)
    assert t["signals"] >= 5 and not t["reliable"] and t["avg_net_pct"] < 0


def test_backtest_needs_history():
    assert backtest_band([1.03] * (BAND_DAYS + 5), 0.44, 0.40) is None


# ---------------------------------------------------------------------------
# Banda sobre puntas
# ---------------------------------------------------------------------------

def test_band_comes_from_rava_and_excludes_today(db):
    load_history(db, "AL30", "GD30", stable_series())
    db.add(DailyClose(symbol="AL30D", day=TODAY, close=50.0))        # la rueda en curso no entra
    db.add(DailyClose(symbol="GD30D", day=TODAY, close=99.0))
    db.commit()
    r = pair(compute_pair_ratios(db, view_of(bk("AL30D", 49.95, 50.05), bk("GD30D", 51.45, 51.55)), PARAMS))
    assert r.history_source == "RAVA" and r.calibration == f"BANDA_{BAND_DAYS}r"
    assert r.hist_mean == pytest.approx(1.031, abs=0.002)
    assert r.band_lower < r.mid_ratio < r.band_upper                 # 1,03: adentro
    assert r.band_signal is None and r.long_mean == pytest.approx(1.031, abs=0.002)


def test_signal_when_out_of_band_and_covers_costs(db):
    load_history(db, "AL30", "GD30", stable_series())
    v = view_of(bk("AL30D", 49.95, 50.05), bk("GD30D", 52.95, 53.05))   # ratio 1,06
    r = pair(compute_pair_ratios(db, v, PARAMS))
    assert r.band_signal == "B_TO_A" and r.reliable
    # vender GD a 52,95 y comprar AL a 50,05; volver a la media (~1,031) con otras dos operaciones
    expected = ((52.95 * 0.9989) / (50.05 * 1.0011) * (0.9989 / 1.0011) / r.hist_mean - 1) * 100
    assert r.expected_net_pct == pytest.approx(expected, abs=0.02) and r.expected_net_pct > 2
    sig = ArbitrageEngine._signals_from_law_ratios([r])
    assert [(s.leg_sell_ticker, s.leg_buy_ticker, s.action_recommended) for s in sig] == [("GD30D", "AL30D", "ROTAR_A_ARG")]
    assert sig[0].net_profit_pct is None             # estadística: sin notificación de Windows
    assert "No es ganancia asegurada" in sig[0].notes


def test_low_side_of_the_band_rotates_to_ny(db):
    load_history(db, "AL30", "GD30", [x + 0.05 for x in stable_series()])   # nivel ~1,08: lejos del 1,01
    v = view_of(bk("AL30D", 49.95, 50.05), bk("GD30D", 52.45, 52.55))       # ratio 1,05
    r = pair(compute_pair_ratios(db, v, PARAMS))
    assert r.band_signal == "A_TO_B" and r.expected_net_pct > 2
    sig = ArbitrageEngine._signals_from_law_ratios([r])
    assert [(s.leg_sell_ticker, s.leg_buy_ticker, s.action_recommended) for s in sig] == [("AL30D", "GD30D", "ROTAR_A_NY")]


def test_out_of_band_but_not_enough_to_cover_costs(db):
    load_history(db, "AL30", "GD30", stable_series())
    v = view_of(bk("AL30D", 49.95, 50.05), bk("GD30D", 51.95, 52.05))   # ratio 1,04: fuera de banda por poco
    r = pair(compute_pair_ratios(db, v, PARAMS))
    assert r.mid_ratio > r.band_upper and r.band_signal is None
    assert any("no cubre el mínimo" in n for n in r.notes)
    assert ArbitrageEngine._signals_from_law_ratios([r]) == []


def test_unreliable_pair_is_informative_only(db):
    load_history(db, "AE38", "GD38", trending_series())
    level = trending_series()[-1]
    v = view_of(bk("AE38D", 59.95, 60.05), bk("GD38D", 60 * (level + 0.04) - 0.05, 60 * (level + 0.04) + 0.05))
    r = pair(compute_pair_ratios(db, v, PARAMS), "AE38", "GD38")
    assert r.band_signal == "B_TO_A" and not r.reliable
    assert any("no fue confiable" in n for n in r.notes)
    assert ArbitrageEngine._signals_from_law_ratios([r]) == []


def test_no_fixed_threshold_without_history(db):
    """Un ratio de 1,17 sin historia ya no dispara nada (antes: corte común de 1,12)."""
    v = view_of(bk("AE38D", 59.95, 60.05), bk("GD38D", 70.15, 70.25))
    r = pair(compute_pair_ratios(db, v, PARAMS), "AE38", "GD38")
    assert r.calibration == "SIN_HISTORIA" and r.z_score is None and r.band_signal is None
    assert ArbitrageEngine._signals_from_law_ratios([r]) == []
