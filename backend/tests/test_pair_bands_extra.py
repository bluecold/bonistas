"""
Pares nuevos sobre el motor de bandas (CER en pesos, Tesoro en dólares), ajuste de la historia por
pagos de cupón (AO29/AN29) y pase de dólar cable a MEP con un mismo título.
"""

from datetime import date, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.arbitrage.engine import ArbitrageEngine
from backend.app.arbitrage.fx_implied import cable_to_mep_quotes
from backend.app.arbitrage.market_view import Book, Level, MarketView
from backend.app.arbitrage.ratios import (
    adjust_for_flows, compute_pair_ratios, pair_specs, pending_cutoff, ratio_history,
)
from backend.app.db.models import BondFlowLog, DailyClose, ReferenceBond
from backend.app.db.session import Base
from backend.app.services.price_history_service import history_symbols
from backend.app.services.trading_settings import TradingParams

PARAMS = TradingParams(commission_pct=0.11, min_net_profit_pct=0.40, trade_size_usd=500)
TODAY = date(2026, 11, 4)       # miércoles


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    s = sessionmaker(bind=engine)()
    try:
        yield s
    finally:
        s.close()


def bk(symbol, bid, ask, currency="ARS", base=None, settlement="24HS"):
    return Book(symbol=symbol, base=base or symbol, currency=currency, settlement=settlement,
                bids=[Level(bid, 1e9)], asks=[Level(ask, 1e9)], last=None, trade_time=None,
                timestamp=None, source="BULLMARKET")


def view_of(*books, today=TODAY):
    return MarketView(books={(b.symbol, b.settlement): b for b in books}, today=today,
                      next_bd=today + timedelta(days=1), mep_reference=1585.0, caucion_tna_pct=26.0,
                      flows_by_base={})


def stable_series(n=300):
    return [1.05 if i % 25 == 24 else 1.03 + (0.002 if i % 2 else -0.002) for i in range(n)]


def load(db, sym_a, sym_b, ratios, base_price=100.0, end=TODAY):
    start = end - timedelta(days=len(ratios))
    for i, r in enumerate(ratios):
        day = start + timedelta(days=i)
        db.add(DailyClose(symbol=sym_a, day=day, close=base_price))
        db.add(DailyClose(symbol=sym_b, day=day, close=base_price * r))
    db.commit()


def pair(ratios, a, b):
    return next(r for r in ratios if (r.a, r.b, r.settlement) == (a, b, "24HS"))


# ---------------------------------------------------------------------------
# Pares CER en pesos
# ---------------------------------------------------------------------------

def test_history_symbols_include_peso_and_dollar_species():
    syms = history_symbols()
    assert {"AL30D", "TZX28", "TZXS8", "DICP", "DIP0", "AO29D", "AN29D"} <= set(syms)
    assert "TZX28D" not in syms and "AO29" not in syms
    assert len({(s.a, s.b) for s in pair_specs()}) == len(pair_specs())


def test_cer_pair_uses_peso_species_and_emits_pair_band_signal(db):
    load(db, "TZXS8", "TZXM9", stable_series())
    v = view_of(bk("TZXS8", 99.95, 100.05), bk("TZXM9", 105.95, 106.05))      # ratio 1,06
    r = pair(compute_pair_ratios(db, v, PARAMS), "TZXS8", "TZXM9")
    assert (r.kind, r.symbol_a, r.symbol_b, r.history_source) == ("CER", "TZXS8", "TZXM9", "RAVA")
    assert r.band_signal == "B_TO_A" and r.reliable and r.expected_net_pct > 2
    sig = ArbitrageEngine._signals_from_pair_bands([r])
    assert [(s.strategy_name, s.leg_sell_ticker, s.leg_buy_ticker, s.action_recommended) for s in sig] == \
        [("PAIR_BAND", "TZXM9", "TZXS8", "ROTAR_A_TZXS8")]
    assert sig[0].net_profit_pct is None and "No es ganancia asegurada" in sig[0].notes
    assert ArbitrageEngine._signals_from_law_ratios([r]) == []


def test_cer_pair_low_side_and_unreliable_pair(db):
    load(db, "TZXS8", "TZXM9", [x + 0.05 for x in stable_series()])
    v = view_of(bk("TZXS8", 99.95, 100.05), bk("TZXM9", 104.95, 105.05))
    r = pair(compute_pair_ratios(db, v, PARAMS), "TZXS8", "TZXM9")
    sig = ArbitrageEngine._signals_from_pair_bands([r])
    assert [(s.leg_sell_ticker, s.leg_buy_ticker) for s in sig] == [("TZXS8", "TZXM9")]
    r.reliable = False
    assert ArbitrageEngine._signals_from_pair_bands([r]) == []


def test_curve_pairs_stay_informative(db):
    load(db, "GD38D", "GD41D", stable_series())
    v = view_of(bk("GD38D", 99.95, 100.05, "MEP", "GD38"), bk("GD41D", 105.95, 106.05, "MEP", "GD41"))
    r = pair(compute_pair_ratios(db, v, PARAMS), "GD38", "GD41")
    assert r.band_signal == "B_TO_A" and r.reliable
    assert ArbitrageEngine._signals_from_pair_bands([r]) == []


# ---------------------------------------------------------------------------
# Ajuste por pagos (AO29 / AN29)
# ---------------------------------------------------------------------------

def business_days(end, n):
    out, d = [], end
    while len(out) < n:
        d -= timedelta(days=1)
        if d.weekday() < 5:
            out.append(d)
    return sorted(out)


def test_adjust_for_flows_removes_the_coupon_drop():
    days = business_days(date(2026, 6, 12), 20)           # pago lunes 1/6: corta el viernes 29/5
    cut = date(2026, 5, 29)
    closes = {d: (96.75 if d < cut else 93.5) for d in days}
    partner = {d: 90.0 for d in days}
    adj = adjust_for_flows(closes, partner, [(date(2026, 5, 30), 3.25)], before=date(2026, 6, 12))
    assert all(v == pytest.approx(93.5, abs=0.01) for v in adj.values())
    # un pago que todavía no pasó no toca la historia
    assert adjust_for_flows(closes, partner, [(date(2026, 6, 30), 3.25)], before=date(2026, 6, 12)) == closes


def test_adjust_picks_the_earlier_cutoff_day_when_the_drop_is_there():
    days = business_days(date(2026, 6, 12), 20)
    cut = date(2026, 5, 28)                               # corta dos ruedas antes del pago
    closes = {d: (96.75 if d < cut else 93.5) for d in days}
    adj = adjust_for_flows(closes, {d: 90.0 for d in days}, [(date(2026, 5, 30), 3.25)], before=date(2026, 6, 12))
    assert all(v == pytest.approx(93.5, abs=0.01) for v in adj.values())


def test_pending_cutoff_window():
    flows = [(date(2026, 11, 30), 3.25)]                  # lunes: ruedas de corte posibles 26 y 27
    assert pending_cutoff(flows, date(2026, 11, 25)) is None
    assert pending_cutoff(flows, date(2026, 11, 26)) == date(2026, 11, 30)
    assert pending_cutoff(flows, date(2026, 11, 30)) == date(2026, 11, 30)
    assert pending_cutoff(flows, date(2026, 12, 1)) == date(2026, 11, 30)   # una rueda de margen
    assert pending_cutoff(flows, date(2026, 12, 2)) is None


def test_an29_coupon_does_not_fake_a_band_signal(db):
    """AN29 paga 3,25: sin corregir, el ratio AN29/AO29 cae 3% el día del corte y parece señal."""
    end = date(2026, 12, 9)
    days = business_days(end, 60)
    cut = date(2026, 11, 27)
    for i, d in enumerate(days):
        wiggle = 0.1 if i % 2 else -0.1
        db.add(DailyClose(symbol="AO29D", day=d, close=95.0))
        db.add(DailyClose(symbol="AN29D", day=d, close=(99.0 if d < cut else 95.75) + wiggle))
    db.add(BondFlowLog(ticker_base="AN29", pay_date=date(2026, 11, 30), amount=3.25, currency="USD"))
    db.add(BondFlowLog(ticker_base="AO29", pay_date=date(2027, 6, 30), amount=0.5, currency="USD"))
    db.commit()

    raw, _ = ratio_history(db, "AO29", "AN29", before=end)
    adj, src = ratio_history(db, "AO29", "AN29", before=end, adjust_flows=True)
    assert max(raw) - min(raw) > 0.03 and src == "RAVA"
    assert max(adj) - min(adj) < 0.006

    v = view_of(bk("AO29D", 94.95, 95.05, "MEP", "AO29"), bk("AN29D", 95.70, 95.80, "MEP", "AN29"), today=end)
    r = pair(compute_pair_ratios(db, v, PARAMS), "AO29", "AN29")
    assert r.flow_adjusted and r.calibration.startswith("BANDA_")
    assert r.band_lower < r.mid_ratio < r.band_upper and r.band_signal is None

    # durante la ventana del corte no hay banda
    v2 = view_of(bk("AO29D", 94.95, 95.05, "MEP", "AO29"), bk("AN29D", 95.70, 95.80, "MEP", "AN29"),
                 today=date(2026, 11, 27))
    r2 = pair(compute_pair_ratios(db, v2, PARAMS), "AO29", "AN29")
    assert r2.calibration == "CORTE_CUPON" and r2.band_signal is None
    assert any("Corte de cupón en curso" in n for n in r2.notes)


def test_flow_adjusted_pair_without_payment_history_has_no_band(db):
    load(db, "AO29D", "AN29D", stable_series())
    v = view_of(bk("AO29D", 99.95, 100.05, "MEP", "AO29"), bk("AN29D", 105.95, 106.05, "MEP", "AN29"))
    r = pair(compute_pair_ratios(db, v, PARAMS), "AO29", "AN29")
    assert r.calibration == "SIN_PAGOS" and r.band_signal is None
    assert any("faltan los pagos" in n for n in r.notes)


def test_payment_history_from_bullmarket_is_stored_for_adjusted_bonds(db):
    from backend.app.data.bullmarket_client import parse_payment_history
    from backend.app.services.reference_data_service import ReferenceDataService
    raw = {"resultCashflowTable": [
        {"symbol": "AN29", "paymentDate": "2026-05-30T00:00:00", "ryA": 3.03, "isPastPayment": True, "paymentsCurrency": "MEP"},
        {"symbol": "AN29", "paymentDate": "2026-11-30T00:00:00", "ryA": 3.25, "isPastPayment": False, "paymentsCurrency": "MEP"},
        {"symbol": "DICP", "paymentDate": "2026-06-30T00:00:00", "ryA": 5064.24, "isPastPayment": True, "paymentsCurrency": "ARS"},
        {"symbol": "AL30", "paymentDate": "2026-07-09T00:00:00", "ryA": 8.0, "isPastPayment": True, "paymentsCurrency": "MEP"},
    ]}
    history = parse_payment_history(raw)
    assert history["AN29"] == ("USD", [(date(2026, 5, 30), 3.03), (date(2026, 11, 30), 3.25)])
    assert ReferenceDataService.store_payment_history(db, history) == 3
    assert ReferenceDataService.store_payment_history(db, history) == 3      # reemplaza, no duplica
    rows = db.query(BondFlowLog).order_by(BondFlowLog.ticker_base, BondFlowLog.pay_date).all()
    assert [(r.ticker_base, r.pay_date, r.amount, r.currency) for r in rows] == [
        ("AN29", date(2026, 5, 30), 3.03, "USD"), ("AN29", date(2026, 11, 30), 3.25, "USD"),
        ("DICP", date(2026, 6, 30), 5064.24, "ARS")]                          # AL30 no se ajusta: no se guarda


# ---------------------------------------------------------------------------
# Cable -> MEP
# ---------------------------------------------------------------------------

def test_cable_to_mep_net_of_two_fees():
    v = view_of(bk("GD30C", 60.90, 61.00, "CCL", "GD30"), bk("GD30D", 61.50, 61.60, "MEP", "GD30"),
                bk("AL30C", 60.00, 60.10, "CCL", "AL30"), bk("AL30D", 60.00, 60.10, "MEP", "AL30"),
                bk("GD35D", 70.00, 70.10, "MEP", "GD35"))
    out = cable_to_mep_quotes(v, PARAMS)
    assert [c.base for c in out] == ["GD30", "AL30"]                     # GD35 no tiene especie C
    best = out[0]
    assert (best.cable_symbol, best.mep_symbol, best.buy_price, best.sell_price) == ("GD30C", "GD30D", 61.00, 61.50)
    assert best.net_pct == pytest.approx((61.50 * 0.9989 / (61.00 * 1.0011) - 1) * 100, abs=0.002)
    assert best.net_pct > 0 and best.depth_ok
    assert out[1].net_pct < 0                                            # sin canje, solo se pagan costos
