"""
Ficha del bono: sensibilidad a la TIR, historia de TIR y paridad recalculada con los flujos de
cada fecha (corte de cupón incluido), flujos CER llevados al CER de la fecha y descarga a demanda.
"""

import asyncio
from datetime import date, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.data.rava_client import RavaClient
from backend.app.db.models import Bond, BondFlowLog, DailyClose, ReferenceBond
from backend.app.db.session import Base
from backend.app.quant.cashflows import generate_cashflows
from backend.app.quant.fixed_income import (
    calculate_accrued_interest, calculate_residual_capital, calculate_ytm,
)
from backend.app.services import bond_profile_service as profile
from backend.app.services.market_calendar import ex_date
from backend.app.services.price_history_service import PriceHistoryService

TODAY = date(2026, 11, 12)      # jueves


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    s = sessionmaker(bind=engine)()
    try:
        yield s
    finally:
        s.close()


def add_bond(db, ticker, bond_type="HARD_DOLLAR", currency="USD", maturity=date(2035, 7, 9), **kw):
    db.add(Bond(ticker=ticker, name=ticker, currency=currency, law="NY", bond_type=bond_type,
                maturity_date=maturity, **kw))
    db.commit()


def add_ref(db, base, flows, currency="ARS", tipo="CER", **kw):
    db.add(ReferenceBond(ticker_base=base, tipo=tipo, currency=currency,
                         flows=[[d.isoformat(), a] for d, a in flows], species=[base], **kw))
    db.commit()


def csv_history(symbol, closes):
    rows = ["especie,apertura,maximo,minimo,ultimo,fecha,volumen,cierre,timestamp"]
    rows += [f"{symbol},{c},{c},{c},{c},{d.isoformat()},1000,{c},0" for d, c in closes]
    return "\n".join(rows)


def business_days(end, n):
    out, d = [], end
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d -= timedelta(days=1)
    return out[::-1]


# ------------------------------------------------------------------ cálculo

def test_settlement_switches_from_48hs_to_24hs():
    assert profile.settlement_for(date(2026, 11, 11)) == date(2026, 11, 12)      # T+1
    assert profile.settlement_for(date(2024, 5, 24)) == date(2024, 5, 28)        # viernes, T+2
    assert profile.settlement_for(date(2024, 5, 27)) == date(2024, 5, 28)        # primer día de T+1


def test_sensitivity_reprices_the_same_flows(db):
    add_bond(db, "GD35", start_date=date(2020, 9, 4))
    model = profile.build_model(db, "GD35", TODAY)
    assert (model.kind, model.price_symbol, model.full_history) == ("PROPIO", "GD35D", True)
    out = profile.valuation(model, 69.77, date(2026, 11, 13))
    # Mismos números que la ficha de bonistas.com para GD35D ese día
    assert out["ytm_pct"] == pytest.approx(12.54, abs=0.02)
    assert out["technical_value"] == pytest.approx(101.42, abs=0.01)
    assert out["parity_pct"] == pytest.approx(68.79, abs=0.02)
    by_shift = {r["shift_pp"]: r["change_pct"] for r in out["sensitivity"]}
    assert set(by_shift) == set(profile.SENSITIVITY_SHIFTS)
    assert by_shift[-1] == pytest.approx(4.7, abs=0.1) and by_shift[1] == pytest.approx(-4.4, abs=0.1)
    assert by_shift[10] == pytest.approx(-34.3, abs=0.2)
    assert by_shift[-3] > by_shift[-2] > by_shift[-1] > 0 > by_shift[1] > by_shift[10]


def test_history_revalues_each_close_with_the_flows_of_that_day(db):
    add_bond(db, "GD35", start_date=date(2020, 9, 4))
    model = profile.build_model(db, "GD35", TODAY)
    day = date(2025, 3, 12)
    hist = profile.compute_history(model, [(day, 66.0)], TODAY)
    s = profile.settlement_for(day)
    expected = calculate_ytm(66.0, generate_cashflows("GD35", s, date(2035, 7, 9)))
    assert hist["ytm"][0] == pytest.approx(expected * 100, abs=0.001)
    vt = calculate_residual_capital("GD35", s) + calculate_accrued_interest("GD35", s)
    assert hist["parity"][0] == pytest.approx(66.0 / vt * 100, abs=0.01)


def test_coupon_is_dropped_from_the_cutoff_settlement(db):
    add_bond(db, "GD35", start_date=date(2020, 9, 4))
    model = profile.build_model(db, "GD35", TODAY)
    pay = date(2026, 7, 9)
    cut = ex_date(pay)                                   # 08/07: primera liquidación sin el pago
    assert pay in [d for d, _ in model.flows_at(cut - timedelta(days=1))]
    assert pay not in [d for d, _ in model.flows_at(cut)]
    # Entre el corte y el pago el valor técnico ya es el de después del pago (sin el cupón corrido)
    assert model.technical_value_at(cut) == pytest.approx(100.0, abs=0.01)
    assert model.technical_value_at(cut - timedelta(days=1)) > 102.0


def test_cer_zero_coupon_flow_is_scaled_to_the_cer_of_each_date(db):
    add_bond(db, "TZX28", bond_type="CER", currency="ARS", maturity=date(2028, 6, 30), coupon_rate=0)
    add_ref(db, "TZX28", [(date(2028, 6, 30), 400.0)], flows_cer_adjusted=True, yield_is_real=True,
            settlement_date=date(2026, 11, 13))
    model = profile.build_model(db, "TZX28", TODAY)
    assert model.cer and model.full_history and model.real_yield
    # CER que se duplica entre un año atrás y hoy
    cer = profile.CerSeries({date(2025, 1, 1): 100.0, date(2026, 6, 1): 200.0})
    old, new = date(2025, 11, 13), date(2026, 11, 13)
    assert model.flows_at(old, cer)[0][1] == pytest.approx(200.0)
    assert model.flows_at(new, cer)[0][1] == pytest.approx(400.0)
    assert model.technical_value_at(old, cer) == pytest.approx(200.0)
    hist = profile.compute_history(model, [(date(2025, 11, 12), 160.0)], TODAY, cer)
    assert hist["parity"][0] == pytest.approx(80.0, abs=0.01)
    assert hist["ytm"][0] is not None
    # Sin la serie del CER no se inventa nada
    assert profile.compute_history(model, [(date(2025, 11, 12), 160.0)], TODAY, None)["ytm"] is None


def test_coupon_bond_with_only_future_flows_has_no_historical_ytm(db):
    add_ref(db, "BPY26", [(date(2027, 2, 28), 30.0), (date(2027, 5, 31), 35.0)], currency="USD",
            tipo="Soberano")
    model = profile.build_model(db, "BPY26", TODAY)
    assert not model.full_history and model.notes
    hist = profile.compute_history(model, [(date(2026, 1, 5), 90.0), (date(2026, 1, 6), 91.0)], TODAY)
    assert hist["price"] == [90.0, 91.0] and hist["ytm"] is None and hist["parity"] is None
    # Con el precio de hoy sí hay TIR y sensibilidad
    assert profile.valuation(model, 60.0, date(2026, 11, 13))["sensitivity"]


def test_logged_payments_complete_the_history(db):
    add_ref(db, "AN29", [(date(2026, 11, 30), 3.25), (date(2029, 11, 30), 103.25)], currency="USD",
            tipo="Soberano")
    db.add_all([BondFlowLog(ticker_base="AN29", pay_date=d, amount=a, currency="USD")
                for d, a in ((date(2026, 5, 30), 3.03), (date(2026, 11, 30), 3.25), (date(2029, 11, 30), 103.25))])
    db.commit()
    model = profile.build_model(db, "AN29", TODAY)
    assert model.full_history
    assert [d for d, _ in model.flows] == [date(2026, 5, 30), date(2026, 11, 30), date(2029, 11, 30)]
    marks = profile.payment_marks(model, date(2026, 1, 1), TODAY)
    assert [(m["date"], m["upcoming"]) for m in marks] == [("2026-05-30", False), ("2026-11-30", True)]


def test_stats_place_the_last_close_in_its_year():
    days = business_days(TODAY, 60)
    values = [10.0 + i * 0.1 for i in range(60)]
    st = profile._stats(days, values, TODAY)
    assert st["min"] == 10.0 and st["max"] == pytest.approx(15.9) and st["percentile"] == 100.0
    assert profile._stats(days[:10], values[:10], TODAY) is None


def test_pair_series_uses_the_engine_band(db):
    days = business_days(TODAY, 60)
    for i, d in enumerate(days):
        db.add(DailyClose(symbol="AL35D", day=d, close=70.0))
        db.add(DailyClose(symbol="GD35D", day=d, close=70.0 * (1.05 + (0.002 if i % 2 else -0.002))))
    db.commit()
    pairs = profile.pair_series(db, "GD35", TODAY)
    law = next(p for p in pairs if (p["a"], p["b"]) == ("AL35", "GD35"))
    assert len(law["days"]) == 60 and law["mean"][0] is None
    assert law["lower"][-1] < law["mean"][-1] < law["upper"][-1]
    assert law["mean"][-1] == pytest.approx(1.05, abs=0.001)


# ------------------------------------------------------------------ descarga a demanda

def test_history_is_downloaded_once_per_day(db):
    calls = []

    class FakeRava(RavaClient):
        async def fetch_text(self, symbol):
            calls.append(symbol)
            if symbol == "NOEXISTE":
                return ""
            return csv_history(symbol, [(date(2026, 11, 10), 50.0), (date(2026, 11, 11), 51.0)])

    svc = PriceHistoryService(client=FakeRava(pause_seconds=0))
    assert asyncio.run(svc.ensure(db, ["gd35d", "NOEXISTE"])) == {"NOEXISTE": "sin filas"}
    assert PriceHistoryService.closes(db, "GD35D") == [(date(2026, 11, 10), 50.0), (date(2026, 11, 11), 51.0)]
    assert asyncio.run(svc.ensure(db, ["GD35D", "NOEXISTE"])) == {"NOEXISTE": "sin datos en Rava"}
    assert calls == ["GD35D", "NOEXISTE"]                # la segunda vez no se consulta nada


# ------------------------------------------------------------------ API

def test_profile_and_history_endpoints(client, monkeypatch):
    from backend.app.api import routes
    days = business_days(date.today() - timedelta(days=1), 40)

    async def fake_text(self, symbol):
        return csv_history(symbol, [(d, 60.0 + i * 0.1) for i, d in enumerate(days)])

    monkeypatch.setattr(RavaClient, "fetch_text", fake_text)
    monkeypatch.setattr(routes.price_history_service.client, "pause_seconds", 0.0)

    p = client.get("/api/v1/bonds/AL30/profile")
    assert p.status_code == 200, p.text
    data = p.json()
    assert data["context"]["price_symbol"] == "AL30D" and data["context"]["flows_kind"] == "PROPIO"
    assert data["context"]["next_payment"]["ex_date"] <= data["context"]["next_payment"]["date"]
    assert data["quote"]["price"] and data["metrics"]["ytm_pct"] is not None
    assert len(data["metrics"]["sensitivity"]) == len(profile.SENSITIVITY_SHIFTS)

    h = client.get("/api/v1/bonds/AL30/history")
    assert h.status_code == 200, h.text
    hist = h.json()
    assert hist["symbol"] == "AL30D" and len(hist["days"]) == 40
    assert all(v is not None for v in hist["ytm"]) and all(v is not None for v in hist["parity"])
    assert hist["stats"]["ytm"]["days"] == 40
    assert any((x["a"], x["b"]) == ("AL30", "GD30") for x in hist["pairs"])

    assert client.get("/api/v1/bonds/NOEXISTE/profile").status_code == 404
    assert client.get("/api/v1/bonds/NOEXISTE/history").status_code == 404


# ------------------------------------------------------------------ simulador de swaps: precios ejecutables

def test_swap_legs_walk_the_book_instead_of_using_the_last_price():
    from backend.app.arbitrage.market_view import Book, Level
    from backend.app.quant.swap_calculator import simulate_bond_swap
    from backend.app.services import swap_pricing

    # Libros reales de AN29D / AO29D (Bull Market, 12/11/2026 12:37)
    an29 = Book("AN29D", "AN29", "MEP", "24HS",
                [Level(80.79, 250), Level(80.78, 500), Level(80.75, 235), Level(80.72, 250)],
                [Level(80.94, 582)], 80.9, None, None, "BULLMARKET")
    ao29 = Book("AO29D", "AO29", "MEP", "24HS", [Level(77.25, 500)],
                [Level(77.31, 1), Level(77.33, 2076), Level(77.35, 459919)], 77.32, None, None, "BULLMARKET")
    fee = 0.0011
    sell = swap_pricing.sell_leg(an29, 1000, last=80.9, symbol="AN29D")
    assert sell.kind == "PUNTAS" and sell.depth_ok and 80.72 < sell.price < 80.79      # promedio de 4 niveles
    cash = 1000 / 100 * sell.price * (1 - fee)
    buy = swap_pricing.buy_leg(ao29, cash, fee, last=77.32, symbol="AO29D")
    assert buy.kind == "PUNTAS" and buy.depth_ok and 77.31 < buy.price <= 77.33
    res = simulate_bond_swap("AN29D", sell.price, 1000, "AO29D", buy.price, broker_commission_pct=0.11, byma_fee_pct=0)
    with_last = simulate_bond_swap("AN29D", 80.9, 1000, "AO29D", 77.32, broker_commission_pct=0.11, byma_fee_pct=0)
    assert res.buy_nominal_acquired < with_last.buy_nominal_acquired          # las puntas dan menos que el último
    assert "1.000 nominales" in res.summary_message and "%" in res.summary_message

    # Sin profundidad suficiente: se avisa y el resto va al último nivel visible
    thin = swap_pricing.sell_leg(an29, 5000, last=80.9, symbol="AN29D")
    assert thin.depth_ok is False and thin.available == 1235
    assert "1.235 nominales" in swap_pricing.describe(thin, "venta")
    # Sin libro: último operado, con aviso
    none = swap_pricing.sell_leg(None, 1000, last=80.9, symbol="AN29D")
    assert (none.kind, none.price) == ("ULTIMO", 80.9) and swap_pricing.describe(none, "venta")


def test_swap_endpoint_reports_where_prices_come_from(client):
    res = client.post("/api/v1/calculator/swap", json={"sell_ticker": "GD30", "buy_ticker": "AL30", "sell_nominal": 1000})
    assert res.status_code == 200, res.text
    data = res.json()
    assert (data["sell_ticker"], data["buy_ticker"]) == ("GD30", "AL30")
    assert data["sell_price_kind"] in ("PUNTAS", "ULTIMO") and data["sell_symbol"] in ("GD30", "GD30D")
    if data["sell_price_kind"] == "PUNTAS":
        assert data["sell_symbol"] == "GD30D" and data["sell_price_source"] in ("BYMA", "BULLMARKET")
