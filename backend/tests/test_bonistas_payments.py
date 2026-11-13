"""
Calendario de próximos pagos de bonistas.com: lectura de la página, respaldo de los cronogramas
de ON sin sesión de Bull Market y pagos con corte inminente.
"""

import json
from datetime import date
from pathlib import Path

import pytest

from backend.app.data import bonistas_payments_client as bpc
from backend.app.data import bullmarket_client as bmc
from backend.app.data.bonistas_payments_client import (
    BonistasPaymentsCache, BonistasPaymentsClient, BonistasPaymentsError, lookup, parse_payments,
)
from backend.app.services.bullmarket_session import BullMarketSession
from backend.app.services.on_cashflows import OnCashflowService, OnCashflowUnavailable, source_of
from backend.tests.conftest import TEST_BM_COOKIE

FIXTURES = Path(__file__).parent / "fixtures"
HTML = (FIXTURES / "bonistas_proximos_pagos.html").read_text(encoding="utf-8")
DAY = date(2026, 11, 13)


def _page(payments):
    data = {"props": {"pageProps": {"initialPayments": payments}}}
    return f'<html><script id="__NEXT_DATA__" type="application/json">{json.dumps(data)}</script></html>'


def _payment(**kw):
    base = {"symbol": "XX1D", "fecha": "2027-01-11", "moneda": "USD", "cupon": 2.0, "principal": 10.0,
            "total": 12.0, "saldo": 100.0}
    return dict(base, **kw)


# ------------------------------------------------------------------ lectura de la página
def test_parse_real_page():
    ok, errors = parse_payments(HTML, DAY)
    assert errors == {}
    assert "TXMD8" in ok and "TXMD8_CER" not in ok          # la otra pata del dual se descarta
    al30 = ok["AL30D"]
    assert al30.currency == "USD" and al30.payment_currency == "MEP" and al30.source == "BONISTAS"
    first = al30.rows[0]
    assert (first.date, first.coupon, first.amortization, first.total) == (date(2027, 1, 11), 0.24, 8, 8.24)
    assert first.residual == 56                              # saldo 64 antes del pago − 8
    assert al30.rows[-1].residual == 0
    assert ok["GD30D"].payment_currency == "CCL"
    assert ok["TX28"].currency == "ARS" and ok["TX28"].payment_currency == "ARS"
    assert ok["CS47D"].currency == "USD" and ok["CS47D"].payment_currency is None


def test_parse_only_future_payments():
    ok, _ = parse_payments(HTML, date(2027, 1, 11))
    assert ok["AL30D"].rows[0].date == date(2027, 7, 12)
    assert "X30N6" not in ok                                 # letra ya vencida: sin pagos futuros


def test_matches_bullmarket_schedule():
    """Mismo cronograma que Bull Market para YM34 y AL30 (fechas a <= 3 días, montos a <= 0,01)."""
    ok, _ = parse_payments(HTML, DAY)
    bm, _ = bmc.parse_cashflows(json.loads((FIXTURES / "bullmarket_cashflows.json").read_text(encoding="utf-8")), DAY)
    for bm_symbol, symbol in (("YM34O", "YM34D"), ("AL30", "AL30D")):
        a, b = bm[bm_symbol].rows, ok[symbol].rows
        assert len(a) == len(b)
        for x, y in zip(a, b):
            assert abs((x.date - y.date).days) <= 3
            assert abs(x.total - y.total) <= 0.01 and abs(x.residual - y.residual) <= 0.01


def test_parse_rejects_changed_format():
    with pytest.raises(BonistasPaymentsError, match="__NEXT_DATA__"):
        parse_payments("<html>sin datos</html>", DAY)
    with pytest.raises(BonistasPaymentsError, match="listado de pagos"):
        parse_payments('<script id="__NEXT_DATA__" type="application/json">{"props": {}}</script>', DAY)
    with pytest.raises(BonistasPaymentsError, match="vacío"):
        parse_payments(_page([]), DAY)


def test_parse_discards_inconsistent_bonds():
    ok, errors = parse_payments(_page([
        _payment(symbol="OK1D"),
        _payment(symbol="BAD1D", total=15.0),                           # total ≠ renta + amortización
        _payment(symbol="BAD2D", cupon=-1.0, total=9.0),
        _payment(symbol="BAD3D"), _payment(symbol="BAD3D", fecha="2027-07-12", moneda="ARS"),
        _payment(symbol="BAD4D", moneda="EUR"),
        _payment(symbol="BAD5D", fecha="11/01/2027"),
    ]), DAY)
    assert list(ok) == ["OK1D"]
    assert set(errors) == {"BAD1D", "BAD2D", "BAD3D", "BAD4D", "BAD5D"}
    assert "total" in errors["BAD1D"] and "monedas mezcladas" in errors["BAD3D"]


def test_lookup_uses_d_species():
    ok, _ = parse_payments(HTML, DAY)
    assert lookup(ok, "ym34o") is ok["YM34D"] and lookup(ok, "YM34C") is ok["YM34D"]
    assert lookup(ok, "YM34D") is ok["YM34D"]
    assert lookup(ok, "TX28") is ok["TX28"] and lookup(ok, "ZZZ9O") is None


# ------------------------------------------------------------------ cache del día
async def test_cache_one_request_per_day(monkeypatch):
    calls = []

    async def raw(self):
        calls.append(1)
        return HTML
    monkeypatch.setattr(BonistasPaymentsClient, "fetch_raw", raw)
    cache = BonistasPaymentsCache()
    assert "AL30D" in await cache.get(DAY)
    await cache.get(DAY)
    assert len(calls) == 1
    await cache.get(date(2026, 11, 16))
    assert len(calls) == 2


async def test_cache_failure_does_not_raise_nor_retry_every_cycle(monkeypatch):
    calls = []

    async def raw(self):
        calls.append(1)
        raise RuntimeError("caída")
    monkeypatch.setattr(BonistasPaymentsClient, "fetch_raw", raw)
    cache = BonistasPaymentsCache()
    assert await cache.get(DAY) == {} and await cache.get(DAY) == {}
    assert len(calls) == 1                                   # el reintento espera RETRY_SECONDS
    cache._failed_at -= bpc.RETRY_SECONDS + 1
    await cache.get(DAY)
    assert len(calls) == 2


# ------------------------------------------------------------------ cronogramas de ON
@pytest.fixture
def session(tmp_path):
    return BullMarketSession(cookie_file=str(tmp_path / "secrets" / "bm.txt"), env_cookie="")


async def test_on_schedule_without_session_comes_from_bonistas(session):
    svc = OnCashflowService(session, bonistas=BonistasPaymentsCache())
    sch = await svc.get("YM34O", today=DAY)
    assert source_of(sch) == "BONISTAS" and sch.currency == "USD"
    assert sch.rows[0].date == date(2027, 1, 18) and sch.rows[-1].residual == 0
    with pytest.raises(OnCashflowUnavailable, match="iniciá la sesión"):
        await svc.get("ZZZ9O", today=DAY)


async def test_bullmarket_replaces_bonistas_when_session_starts(session):
    svc = OnCashflowService(session, bonistas=BonistasPaymentsCache())
    assert source_of(await svc.get("YM34O", today=DAY)) == "BONISTAS"
    session.set_cookie(TEST_BM_COOKIE)
    session.mark_ok(1)
    sch = await svc.get("YM34O", today=DAY)
    assert source_of(sch) == "BULLMARKET" and sch.payment_currency == "CCL"


async def test_bonistas_covers_what_bullmarket_lacks(session):
    session.set_cookie(TEST_BM_COOKIE)
    session.mark_ok(1)
    svc = OnCashflowService(session, bonistas=BonistasPaymentsCache())
    sch = await svc.get("CS47O", today=DAY)                  # no está en el Bull Market simulado
    assert source_of(sch) == "BONISTAS" and sch.rows[0].date == date(2026, 11, 16)
    with pytest.raises(OnCashflowUnavailable, match="no tiene pagos futuros"):
        await svc.get("ZZZ9O", today=DAY)


async def test_expired_session_falls_back_to_bonistas(session):
    session.set_cookie("cookie=vieja")
    session.mark_ok(1)
    svc = OnCashflowService(session, bonistas=BonistasPaymentsCache())
    assert source_of(await svc.get("YM34O", today=DAY)) == "BONISTAS"
    with pytest.raises(OnCashflowUnavailable, match="venció"):
        await svc.get("ZZZ9O", today=DAY)


async def test_prefetch_mixes_sources(session):
    svc = OnCashflowService(session, bonistas=BonistasPaymentsCache())
    got = await svc.prefetch(["YM34O", "CS47O", "ZZZ9O"], today=DAY)
    assert {t: source_of(s) for t, s in got.items()} == {"YM34O": "BONISTAS", "CS47O": "BONISTAS"}
    assert svc.prefetched_day is None                        # todavía falta la pasada de Bull Market

    session.set_cookie(TEST_BM_COOKIE)
    session.mark_ok(1)
    got = await svc.prefetch(["YM34O", "CS47O", "ZZZ9O"], today=DAY)
    assert {t: source_of(s) for t, s in got.items()} == {"YM34O": "BULLMARKET", "CS47O": "BONISTAS"}
    assert svc.prefetched_day == DAY


# ------------------------------------------------------------------ pagos con corte inminente
def _reference(db, ticker, currency, flows):
    from backend.app.db.models import ReferenceBond
    ref = db.get(ReferenceBond, ticker)
    if ref is None:
        ref = ReferenceBond(ticker_base=ticker, source="COMPARARBONOS", species=[ticker])
        db.add(ref)
    ref.currency, ref.flows, ref.flows_check, ref.species = currency, flows, None, [ticker, ticker + "D"]
    db.commit()
    return ref


async def test_imminent_payment_added_without_session(client):
    from backend.app.db.models import ReferenceBond
    from backend.app.db.session import SessionLocal
    from backend.app.services.reference_data_service import ReferenceDataService

    db = SessionLocal()
    try:
        # CompararBonos ya no lista el pago del 30/11 de TX31 ni el del 30/11 de AO27
        _reference(db, "TX31", "ARS", [["2027-05-31", 22.0]])
        _reference(db, "AO27", "USD", [["2026-12-31", 0.5]])
        _reference(db, "TTD26", "ARS", [])                   # sin flujos: no se le agrega un pago suelto
        svc = ReferenceDataService(bonistas_payments=BonistasPaymentsCache())
        added = await svc.add_bonistas_imminent_flows(db, today=date(2026, 11, 20))
        assert added["TX31"] == ["2026-11-30"] and added["AO27"] == ["2026-11-30"]
        assert "TTD26" not in added and "AL30" not in added  # AL30 paga en enero: fuera de la ventana

        tx31 = db.get(ReferenceBond, "TX31")
        assert tx31.flows[0][0] == "2026-11-30" and tx31.flows[0][1] == pytest.approx(23.17, abs=0.01)
        assert tx31.flows_check["pagos_proximos_bonistas"] == ["2026-11-30"]
        assert db.get(ReferenceBond, "AO27").flows[0] == ["2026-11-30", 0.5]
        assert db.get(ReferenceBond, "TTD26").flows == []

        # Idempotente: una segunda pasada no duplica el pago
        assert await svc.add_bonistas_imminent_flows(db, today=date(2026, 11, 20)) == {}
        assert len(db.get(ReferenceBond, "TX31").flows) == 2
    finally:
        db.close()


async def test_imminent_payment_source_down_is_harmless(client, monkeypatch):
    from backend.app.db.session import SessionLocal
    from backend.app.services.reference_data_service import ReferenceDataService

    async def down(self):
        raise RuntimeError("caída")
    monkeypatch.setattr(BonistasPaymentsClient, "fetch_raw", down)
    db = SessionLocal()
    try:
        svc = ReferenceDataService(bonistas_payments=BonistasPaymentsCache())
        assert await svc.add_bonistas_imminent_flows(db, today=date(2026, 11, 20)) == {}
    finally:
        db.close()


def test_reference_refresh_reports_bonistas(client):
    res = client.post("/api/v1/reference/refresh")
    assert res.status_code == 200, res.text
    assert "imminent_bonistas" in res.json()
