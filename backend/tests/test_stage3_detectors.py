"""
Tests de la etapa 3: detectores sobre puntas (CI vs 24hs, dólar implícito, ratios), corte de
cupón, persistencia de señales y parámetros editables.

Los casos usan libros sintéticos para controlar exactamente cada número.
"""

from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

from backend.app.arbitrage.ci_24hs import detect_ci_vs_24hs
from backend.app.arbitrage.engine import ArbitrageEngine
from backend.app.arbitrage.fx_implied import best_round_trips, implied_fx_quotes
from backend.app.arbitrage.market_view import Book, Level, MarketView, walk_book
from backend.app.arbitrage.ratios import MIN_HISTORY_DAYS, compute_pair_ratios
from backend.app.db.migrations import add_missing_columns
from backend.app.db.models import ArbitrageSignal, BookQuote, PriceSnapshot, Bond
from backend.app.db.session import Base
from backend.app.services.market_calendar import ART
from backend.app.services.trading_settings import TradingParams

PARAMS = TradingParams(commission_pct=0.11, min_net_profit_pct=0.40, trade_size_usd=500)
WED, THU = date(2026, 11, 4), date(2026, 11, 5)


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine)()
    try:
        yield db
    finally:
        db.close()


def bk(symbol, settlement, bid=None, ask=None, bid_qty=1e9, ask_qty=1e9, currency="MEP", base=None):
    return Book(symbol=symbol, base=base or (symbol[:-1] if currency != "ARS" else symbol),
                currency=currency, settlement=settlement,
                bids=[Level(bid, bid_qty)] if bid else [], asks=[Level(ask, ask_qty)] if ask else [],
                last=None, trade_time=None, timestamp=None, source="BYMA")


def view_of(*books, today=WED, next_bd=THU, flows=None, caucion=26.1, mep=1585.0):
    return MarketView(books={(b.symbol, b.settlement): b for b in books}, today=today, next_bd=next_bd,
                      mep_reference=mep, caucion_tna_pct=caucion, flows_by_base=flows or {})


def opp(opps, symbol, direction):
    return next(o for o in opps if o.symbol == symbol and o.direction == direction)


# ---------------------------------------------------------------------------
# Profundidad del libro
# ---------------------------------------------------------------------------

def test_walk_book_averages_levels():
    f = walk_book([Level(100, 300), Level(101, 700)], 1000)
    assert f.complete and f.avg_price == pytest.approx(100.7)


def test_walk_book_insufficient_depth():
    f = walk_book([Level(100, 300)], 1000)
    assert not f.complete and f.avg_price is None and f.filled == 300


# ---------------------------------------------------------------------------
# CI vs 24hs
# ---------------------------------------------------------------------------

NO_FLOWS = {"XX27": ("USD", [(date(2027, 6, 30), 100.0)])}


def test_sell_ci_buy_24hs_signal():
    v = view_of(bk("XX27D", "CI", bid=101.0, ask=101.5), bk("XX27D", "24HS", bid=99.5, ask=100.0), flows=NO_FLOWS)
    o = opp(detect_ci_vs_24hs(v, PARAMS), "XX27D", "VENDER_CI_COMPRAR_24HS")
    assert o.gross_pct == pytest.approx(1.0)
    assert o.net_pct == pytest.approx(0.78)          # 1% - 2 x 0,11%
    assert o.coupon_status == "SIN_PAGOS"
    assert o.signal


def test_buy_ci_sell_24hs_discounts_caucion():
    """Comprar CI y vender 24hs inmoviliza el efectivo 1 día: se resta la caución."""
    carry = 26.1 / 365
    v = view_of(bk("XX27D", "CI", bid=99.0, ask=100.0), bk("XX27D", "24HS", bid=100.3, ask=101.0), flows=NO_FLOWS)
    o = opp(detect_ci_vs_24hs(v, PARAMS), "XX27D", "COMPRAR_CI_VENDER_24HS")
    assert o.carry_pct == pytest.approx(carry, abs=1e-4)
    assert o.net_pct == pytest.approx(0.30 - 0.22 - carry, abs=1e-4)
    assert not o.signal                               # neto < 0,40%


def test_weekend_counts_three_days_of_caucion():
    fri, mon = date(2026, 11, 6), date(2026, 11, 9)
    v = view_of(bk("XX27D", "CI", bid=99, ask=100), bk("XX27D", "24HS", bid=101, ask=102),
                today=fri, next_bd=mon, flows=NO_FLOWS)
    o = opp(detect_ci_vs_24hs(v, PARAMS), "XX27D", "COMPRAR_CI_VENDER_24HS")
    assert o.days == 3
    assert o.carry_pct == pytest.approx(26.1 * 3 / 365, abs=1e-4)


def test_coupon_cutoff_is_not_an_arbitrage():
    """
    Viernes 08-ene-2027: el AL30 paga 8,24 USD el 09-ene. El CI (liquida hoy) incluye el pago y
    el 24hs (liquida el lunes 11) ya no. La diferencia de ~16% es el cupón, no un arbitraje.
    """
    flows = {"AL30": ("USD", [(date(2027, 1, 9), 8.24), (date(2027, 7, 9), 8.21)])}
    v = view_of(bk("AL30D", "CI", bid=60.70, ask=60.90), bk("AL30D", "24HS", bid=52.30, ask=52.50),
                today=date(2027, 1, 8), next_bd=date(2027, 1, 11), flows=flows)
    o = opp(detect_ci_vs_24hs(v, PARAMS), "AL30D", "VENDER_CI_COMPRAR_24HS")
    assert o.coupon_status == "AJUSTADO"
    assert o.flow_adjustment == pytest.approx(8.24)
    assert o.gross_pct == pytest.approx(((60.70 - 8.24) / 52.50 - 1) * 100, abs=1e-3)
    assert o.gross_pct < 0.1
    assert not o.signal


def test_coupon_cutoff_peso_species_converted_with_implied_fx():
    flows = {"AL30": ("USD", [(date(2027, 1, 9), 8.24)])}
    v = view_of(
        bk("AL30", "CI", bid=96000, ask=96300, currency="ARS"), bk("AL30", "24HS", bid=82900, ask=83000, currency="ARS"),
        bk("AL30D", "CI", bid=60.6, ask=60.8),
        today=date(2027, 1, 8), next_bd=date(2027, 1, 11), flows=flows,
    )
    o = opp(detect_ci_vs_24hs(v, PARAMS), "AL30", "VENDER_CI_COMPRAR_24HS")
    fx = ((96000 + 96300) / 2) / ((60.6 + 60.8) / 2)
    assert o.flow_adjustment == pytest.approx(8.24 * fx, rel=1e-6)
    assert not o.signal


def test_unknown_payment_schedule_never_signals():
    v = view_of(bk("ZZ27D", "CI", bid=105, ask=106), bk("ZZ27D", "24HS", bid=99, ask=100))
    o = opp(detect_ci_vs_24hs(v, PARAMS), "ZZ27D", "VENDER_CI_COMPRAR_24HS")
    assert o.net_pct > 4 and o.coupon_status == "DESCONOCIDO"
    assert not o.signal
    assert any("corte de cupón" in n for n in o.notes)


def test_insufficient_depth_never_signals():
    """USD 500 de un bono a ~100 = ~501 VN (precio medio 24hs 99,75); la punta tiene 78 VN."""
    v = view_of(bk("XX27D", "CI", bid=101.0, ask=101.5, bid_qty=78), bk("XX27D", "24HS", bid=99.5, ask=100.0),
                flows=NO_FLOWS)
    o = opp(detect_ci_vs_24hs(v, PARAMS), "XX27D", "VENDER_CI_COMPRAR_24HS")
    assert o.nominal == pytest.approx(500 / 0.9975, abs=1)
    assert not o.depth_ok and not o.signal


def test_trade_size_in_pesos_uses_mep_reference():
    v = view_of(bk("S30N6", "CI", bid=127.7, ask=127.8, currency="ARS"),
                bk("S30N6", "24HS", bid=127.8, ask=127.9, currency="ARS"),
                flows={"S30N6": ("ARS", [(date(2026, 11, 30), 129.888)])}, mep=1585.0)
    o = opp(detect_ci_vs_24hs(v, PARAMS), "S30N6", "VENDER_CI_COMPRAR_24HS")
    assert o.nominal == pytest.approx(500 * 1585 / (127.85 / 100), rel=1e-3)


# ---------------------------------------------------------------------------
# Dólar implícito
# ---------------------------------------------------------------------------

def fx_books(base, ars_bid, ars_ask, d_bid, d_ask, st="24HS"):
    return [bk(base, st, bid=ars_bid, ask=ars_ask, currency="ARS", base=base),
            bk(base + "D", st, bid=d_bid, ask=d_ask, base=base)]


def test_implied_mep_rates_include_costs():
    v = view_of(*fx_books("AL30", 83190, 83240, 52.50, 52.75))
    q = next(x for x in implied_fx_quotes(v, PARAMS)
             if x.base == "AL30" and x.ars_settlement == "24HS" and x.usd_settlement == "24HS")
    assert q.buy_usd_rate == pytest.approx(83240 * 1.0011 / (52.50 * 0.9989), abs=0.01)
    assert q.sell_usd_rate == pytest.approx(83190 * 0.9989 / (52.75 * 1.0011), abs=0.01)


def test_mep_round_trip_signal():
    """Dólar barato con X (≈1.500) y caro con Y (≈1.520): ida y vuelta ≈ +0,9% neto."""
    v = view_of(*fx_books("XX30", 74990, 75000, 50.00, 50.05),
                *fx_books("YY30", 76000, 76010, 49.95, 50.00))
    trips = best_round_trips(implied_fx_quotes(v, PARAMS), PARAMS)
    t = next(t for t in trips if t.kind == "MEP" and t.settlement == "24HS")
    assert (t.buy_with, t.sell_with) == ("XX30", "YY30")
    assert t.net_pct == pytest.approx((t.sell_usd_rate / t.buy_usd_rate - 1) * 100, abs=1e-3)
    assert t.net_pct > 0.4 and t.signal


def test_cross_settlement_skipped_when_bond_pays_in_between():
    flows = {"AL30": ("USD", [(THU, 8.24)])}
    v = view_of(*fx_books("AL30", 83190, 83240, 52.5, 52.75, st="CI"),
                *fx_books("AL30", 83190, 83240, 52.5, 52.75, st="24HS"), flows=flows)
    combos = {(q.ars_settlement, q.usd_settlement) for q in implied_fx_quotes(v, PARAMS) if q.kind == "MEP"}
    assert combos == {("CI", "CI"), ("24HS", "24HS")}


# ---------------------------------------------------------------------------
# Ratios
# ---------------------------------------------------------------------------

def test_law_ratio_with_static_calibration(db_session):
    v = view_of(bk("AL30D", "24HS", bid=52.50, ask=52.75), bk("GD30D", "24HS", bid=53.37, ask=54.50))
    r = next(x for x in compute_pair_ratios(db_session, v, PARAMS) if (x.a, x.b) == ("AL30", "GD30"))
    assert r.mid_ratio == pytest.approx(((53.37 + 54.50) / 2) / ((52.50 + 52.75) / 2), abs=1e-4)
    assert r.rotate_a_to_b == pytest.approx(52.50 * 0.9989 / (54.50 * 1.0011), abs=1e-4)
    assert r.calibration == "ESTATICA"


def test_law_ratio_with_real_history(db_session):
    db_session.add_all([Bond(ticker=t, name=t, currency="USD", law="ARG", bond_type="HARD_DOLLAR",
                             maturity_date=date(2030, 7, 9)) for t in ("AL30", "GD30")])
    start = datetime(2026, 9, 1, 15, 0, tzinfo=timezone.utc)
    for i in range(MIN_HISTORY_DAYS + 5):
        ts = start + timedelta(days=i)
        ratio = 1.03 + (0.01 if i % 2 else -0.01)
        db_session.add(PriceSnapshot(ticker="AL30", timestamp=ts, settlement_type="24HS", price_mep=50))
        db_session.add(PriceSnapshot(ticker="GD30", timestamp=ts, settlement_type="24HS", price_mep=50 * ratio))
    db_session.commit()
    v = view_of(bk("AL30D", "24HS", bid=49.9, ask=50.1), bk("GD30D", "24HS", bid=53.4, ask=53.6))
    r = next(x for x in compute_pair_ratios(db_session, v, PARAMS) if (x.a, x.b, x.settlement) == ("AL30", "GD30", "24HS"))
    assert r.calibration.startswith("HISTORICA_")
    assert r.hist_mean == pytest.approx(1.03, abs=0.002)
    assert r.z_score > 3                          # 1,07 contra una media de 1,03


# ---------------------------------------------------------------------------
# Persistencia de señales
# ---------------------------------------------------------------------------

def _add_books(db, ci_bid):
    now = datetime.now(timezone.utc)
    for settlement, bid, ask in (("CI", ci_bid, ci_bid + 0.5), ("24HS", 99.5, 100.0)):
        db.add(BookQuote(timestamp=now, source="BYMA", symbol="AL30D", base_ticker="AL30", currency="MEP",
                         settlement=settlement, bid=bid, bid_qty=1e9, ask=ask, ask_qty=1e9))
    db.commit()


def test_signals_persist_while_active_and_expire(db_session):
    engine = ArbitrageEngine()
    now = datetime(2026, 11, 4, 13, 0, tzinfo=ART)    # sin pagos de AL30 entre hoy y mañana
    _add_books(db_session, ci_bid=101.0)

    first = [s for s in engine.evaluate_all_strategies(db_session, now=now) if s.strategy_name == "CI_24HS"]
    assert len(first) == 1 and len(engine.last_new_signals) >= 1
    sig = first[0]
    assert sig.first_seen is not None and sig.net_profit_pct == pytest.approx(0.78, abs=1e-3)
    assert sig.confirmation == "DEMORA_20MIN"

    second = [s for s in engine.evaluate_all_strategies(db_session, now=now) if s.strategy_name == "CI_24HS"]
    assert [s.id for s in second] == [sig.id]                 # misma señal, no una nueva
    assert not [s for s in engine.last_new_signals if s.strategy_name == "CI_24HS"]

    _add_books(db_session, ci_bid=99.0)                        # la oportunidad desaparece
    engine.evaluate_all_strategies(db_session, now=now)
    db_session.refresh(sig)
    assert sig.status == "EXPIRED"
    assert engine.last_expired_count >= 1


# ---------------------------------------------------------------------------
# Parámetros editables y migración
# ---------------------------------------------------------------------------

def test_trading_settings_api(client):
    assert client.get("/api/v1/settings/trading").json() == {
        "commission_pct": 0.11, "min_net_profit_pct": 0.40, "trade_size_usd": 500.0}
    res = client.put("/api/v1/settings/trading", json={"trade_size_usd": 1000, "min_net_profit_pct": 0.5})
    assert res.json()["trade_size_usd"] == 1000 and res.json()["commission_pct"] == 0.11
    assert client.put("/api/v1/settings/trading", json={"commission_pct": -1}).status_code == 422
    assert client.put("/api/v1/settings/trading", json={"otro": 1}).status_code == 422
    client.put("/api/v1/settings/trading", json={"trade_size_usd": 500, "min_net_profit_pct": 0.4})


def test_scanner_endpoints_with_real_books(client):
    ci = client.get("/api/v1/arbitrage/ci-24hs").json()
    assert ci["params"]["trade_size_usd"] == 500
    al30d = [o for o in ci["opportunities"] if o["symbol"] == "AL30D"]
    assert {o["direction"] for o in al30d} == {"VENDER_CI_COMPRAR_24HS", "COMPRAR_CI_VENDER_24HS"}

    fx = client.get("/api/v1/arbitrage/fx-implied?kind=MEP").json()
    assert fx["best_to_buy_usd"] and fx["best_to_sell_usd"]
    assert all(1000 < q["buy_usd_rate"] < 3000 for q in fx["best_to_buy_usd"])

    ratios = client.get("/api/v1/arbitrage/ratios").json()["ratios"]
    assert any(r["a"] == "AL30" and r["b"] == "GD30" for r in ratios)

    cc = client.get("/api/v1/arbitrage/command-center").json()
    assert len(cc["law_premium_matrix"]) == 5
    assert cc["confirmation"] == "DEMORA_20MIN"


def test_migration_adds_missing_columns():
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:   # tabla con el esquema viejo (v1.0)
        conn.execute(text(
            "CREATE TABLE arbitrage_signals (id INTEGER PRIMARY KEY, timestamp DATETIME, strategy_name VARCHAR(50), "
            "leg_sell_ticker VARCHAR(20), leg_buy_ticker VARCHAR(20), metric_name VARCHAR(40), metric_value NUMERIC, "
            "historical_mean NUMERIC, std_deviations NUMERIC, action_recommended VARCHAR(40), status VARCHAR(20), notes TEXT)"))
        conn.execute(text("INSERT INTO arbitrage_signals (id, strategy_name, status) VALUES (1, 'X', 'EXPIRED')"))
    added = add_missing_columns(engine)
    assert "arbitrage_signals.signal_key" in added and "arbitrage_signals.details" in added
    cols = {c["name"] for c in inspect(engine).get_columns("arbitrage_signals")}
    assert {"first_seen", "last_seen", "net_profit_pct", "confirmation"} <= cols
    with engine.connect() as conn:
        assert conn.execute(text("SELECT strategy_name FROM arbitrage_signals")).scalar() == "X"


def test_legacy_and_duplicate_active_signals_all_expire(db_session):
    """Las señales v1.0 (sin clave) se expiran todas en el primer ciclo, no de a una."""
    for i in range(4):
        db_session.add(ArbitrageSignal(strategy_name="DUAL_TAMAR_CER", leg_sell_ticker="CASH_ARS",
                                       leg_buy_ticker=f"TX{i}", metric_name="X", metric_value=1,
                                       action_recommended="COMPRAR_DUAL", status="ACTIVE"))
    db_session.commit()
    engine = ArbitrageEngine()
    engine.evaluate_all_strategies(db_session, now=datetime(2026, 11, 4, 13, 0, tzinfo=ART))
    assert engine.last_expired_count == 4
    engine.evaluate_all_strategies(db_session, now=datetime(2026, 11, 4, 13, 1, tzinfo=ART))
    assert engine.last_expired_count == 0


def test_statistical_rules_need_real_history(db_session):
    """Sin 20 ruedas de historia, un z-score alto con calibración estática no genera señal."""
    from backend.app.arbitrage.engine import ArbitrageEngine as E
    from backend.app.arbitrage.ratios import PairRatio
    r = PairRatio(a="AL30", b="GD30", kind="LEY", settlement="24HS", mid_ratio=1.11, rotate_a_to_b=0.89,
                  rotate_b_to_a=1.10, z_score=1.7, hist_mean=1.055, hist_std=0.032, calibration="ESTATICA")
    assert E._signals_from_law_ratios([r]) == []
    r.calibration = "HISTORICA_40d"
    assert [s.action_recommended for s in E._signals_from_law_ratios([r])] == ["ROTAR_A_ARG"]
