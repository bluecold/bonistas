"""Cronogramas de pago de Bull Market: parseo, consenso de provinciales y pagos próximos (caso TX28)."""

import json
from datetime import date
from pathlib import Path

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.arbitrage.ci_24hs import detect_ci_vs_24hs
from backend.app.arbitrage.market_view import Book, Level, MarketView
from backend.app.data import bullmarket_client as bmc
from backend.app.data.bruno618_client import ProvincialSchedule, ScheduleRow
from backend.app.db.models import ReferenceBond
from backend.app.db.session import Base
from backend.app.services.reference_data_service import ReferenceDataService
from backend.app.services.trading_settings import TradingParams

RAW = json.loads((Path(__file__).parent / "fixtures" / "bullmarket_cashflows.json").read_text(encoding="utf-8"))
TODAY = date(2026, 11, 5)
_REAL_FETCH = bmc.fetch_cashflows          # capturado antes de que conftest lo reemplace


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    s = sessionmaker(bind=engine)()
    try:
        yield s
    finally:
        s.close()


def test_parse_real_response():
    ok, errors = bmc.parse_cashflows(RAW, TODAY)
    assert errors == {}
    ndg = ok["NDG34"]
    assert ndg.currency == "USD" and ndg.payment_currency == "CCL" and len(ndg.rows) == 16
    assert ndg.rows[0] == ScheduleRow(date(2027, 2, 25), 4.19, 0.0, 4.19, 100.0)
    assert sum(r.amortization for r in ndg.rows) == pytest.approx(100.0)
    tx = ok["TX28"]
    assert tx.currency == "ARS" and tx.rows[0].date == date(2026, 11, 9) and tx.rows[0].total == pytest.approx(402.04)
    assert ok["BC37D"].rows[0].coupon == pytest.approx(2.62) and ok["BC37D"].payment_currency == "MEP"


def test_parse_skips_past_and_rejects_inconsistent_rows():
    rows = [dict(RAW["resultCashflowTable"][0])]
    rows[0].update(paymentDate="2027-01-01T00:00:00", rentaInteres=1.0, amortizacionCapital=0.0, ryA=5.0,
                   isPastPayment=False)
    ok, errors = bmc.parse_cashflows({"resultCashflowTable": rows}, TODAY)
    assert ok == {} and "total" in list(errors.values())[0]
    past = [dict(r, isPastPayment=True) for r in RAW["resultCashflowTable"] if r["symbol"] == "CO32"]
    assert bmc.parse_cashflows({"resultCashflowTable": past}, TODAY) == ({}, {})


async def test_fetch_chunks_and_detects_expiry(monkeypatch):
    calls = []
    real_client = httpx.AsyncClient

    def handler(request):
        body = json.loads(request.content)
        calls.append(len(body["symbolQuantityList"]))
        if request.headers.get("cookie") != "a=1":
            return httpx.Response(302, headers={"location": "/Home/Login"})
        return httpx.Response(200, json={"resultCashflowTable": []})

    monkeypatch.setattr(bmc.httpx, "AsyncClient", lambda *a, **k: real_client(*a, transport=httpx.MockTransport(handler), **k))
    ok, _ = await _REAL_FETCH("a=1", [f"B{i}" for i in range(95)], TODAY)
    assert ok == {} and calls == [40, 40, 15]
    with pytest.raises(bmc.SessionExpiredError):
        await _REAL_FETCH("vencida=1", ["NDG34"], TODAY)


def test_imminent_payment_added_tx28(db):
    """CompararBonos ya no lista el pago del 9/11 de TX28: Bull Market sí, y se agrega."""
    db.add(ReferenceBond(ticker_base="TX28", tipo="CER", currency="ARS", species=["TX28"],
                         flows=[["2027-05-10", 399.21], ["2027-11-09", 394.91]], flows_source="COMPARARBONOS"))
    db.commit()
    ok, _ = bmc.parse_cashflows(RAW, TODAY)
    added = ReferenceDataService.add_imminent_flows(db, ok, today=TODAY)
    ref = db.get(ReferenceBond, "TX28")
    assert added == {"TX28": ["2026-11-09"]}
    assert ref.flows[0] == ["2026-11-09", 402.04] and ref.flows_check["pagos_proximos_bullmarket"] == ["2026-11-09"]
    # no se duplica en una segunda pasada
    assert ReferenceDataService.add_imminent_flows(db, ok, today=TODAY) == {}


def test_imminent_flow_turns_false_signal_into_adjusted():
    """Con el pago agregado, TX28 queda AJUSTADO por el cupón: sin señal falsa."""
    b = lambda st, bid, ask: Book("TX28", "TX28", "ARS", st, [Level(bid, 1e9)], [Level(ask, 1e9)], None, None, None, "BULLMARKET")
    v = MarketView(books={("TX28", "CI"): b("CI", 1808, 1836.5), ("TX28", "24HS"): b("24HS", 1426, 1476.5)},
                   today=TODAY, next_bd=date(2026, 11, 6), mep_reference=1585.0, caucion_tna_pct=26.1,
                   flows_by_base={"TX28": ("ARS", [(date(2026, 11, 9), 402.04), (date(2027, 5, 10), 399.21)])})
    o = next(o for o in detect_ci_vs_24hs(v, TradingParams(0.11, 0.40, 500)) if o.direction == "VENDER_CI_COMPRAR_24HS")
    assert o.coupon_status == "AJUSTADO" and o.flow_adjustment == pytest.approx(402.04) and not o.signal
    assert o.gross_pct < 0                      # descontado el pago, la "oportunidad" desaparece


def test_bullmarket_breaks_tie_bc37d(db):
    mine = [(date(2027, 3, 1), 2.62, 0.0, 2.62, 100.0), (date(2027, 9, 1), 2.62, 100.0, 102.62, 0.0)]
    other = [(date(2027, 3, 1), 2.50, 0.0, 2.50, 100.0), (date(2027, 9, 1), 2.50, 100.0, 102.50, 0.0)]
    sch = lambda rows: ProvincialSchedule("BC37D", "USD", None, [ScheduleRow(*r) for r in rows])
    res = ReferenceDataService.merge_provincial_schedules(
        db, {"BRUNO618": {"BC37D": sch(other)}, "MERCADOSARG": {"BC37D": sch(mine)},
             "BULLMARKET": {"BC37D": sch(mine)}}, today=TODAY)
    ref = db.get(ReferenceBond, "BC37D")
    assert res["verified"] == ["BC37D"] and ref.flows_source == "BULLMARKET" and ref.flows_verified
    assert res["disagree"]["BC37D"]["descartado"] == [["BRUNO618"]]


async def test_apply_bullmarket_cashflows_adds_ndg34(db):
    from backend.tests.conftest import TEST_BM_COOKIE
    db.add(ReferenceBond(ticker_base="TX28", tipo="CER", currency="ARS", species=["TX28"],
                         flows=[["2027-05-10", 399.21]], flows_source="COMPARARBONOS"))
    db.commit()
    svc = ReferenceDataService()
    res = await svc.apply_bullmarket_cashflows(db, TEST_BM_COOKIE)
    ndg = db.get(ReferenceBond, "NDG34")
    assert ndg is not None and ndg.flows_source == "BULLMARKET" and ndg.species == ["NDG34", "NDG4D", "NDG4C"]
    assert "TX28" in res["imminent"] and svc.bullmarket_cashflows_day == date.today()
