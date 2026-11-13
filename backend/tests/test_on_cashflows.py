from datetime import date

import pytest

from backend.app.data import bullmarket_client as bmc
from backend.app.services.bullmarket_session import BullMarketSession
from backend.app.services.on_cashflows import OnCashflowService, OnCashflowUnavailable
from backend.tests.conftest import TEST_BM_COOKIE


@pytest.fixture
def session(tmp_path):
    s = BullMarketSession(cookie_file=str(tmp_path / "secrets" / "bm.txt"), env_cookie="")
    return s


async def test_without_session_explains(session):
    with pytest.raises(OnCashflowUnavailable, match="iniciá la sesión"):
        await OnCashflowService(session).get("YM34O", today=date(2026, 11, 6))


async def test_real_schedule_and_daily_cache(session, monkeypatch):
    session.set_cookie(TEST_BM_COOKIE)
    session.mark_ok(1)
    calls = []
    real = bmc.fetch_cashflows

    async def counting(cookie, symbols, after, **kw):
        calls.append(symbols)
        return await real(cookie, symbols, after, **kw)
    monkeypatch.setattr(bmc, "fetch_cashflows", counting)

    svc = OnCashflowService(session)
    sch = await svc.get("ym34o", today=date(2026, 11, 6))
    assert sch.currency == "USD" and sch.payment_currency == "CCL"
    assert sch.rows[0].date == date(2027, 1, 17) and sch.rows[-1].residual == 0
    assert abs(sum(r.amortization for r in sch.rows) - 100) < 0.05
    await svc.get("YM34O", today=date(2026, 11, 6))
    assert len(calls) == 1                                    # mismo día: desde el cache
    await svc.get("YM34O", today=date(2026, 11, 9))
    assert len(calls) == 2                                    # día nuevo: se vuelve a pedir


async def test_expired_session(session):
    session.set_cookie("cookie=vieja")
    session.mark_ok(1)
    with pytest.raises(OnCashflowUnavailable, match="venció"):
        await OnCashflowService(session).get("YM34O", today=date(2026, 11, 6))


async def test_unknown_symbol(session):
    session.set_cookie(TEST_BM_COOKIE)
    session.mark_ok(1)
    with pytest.raises(OnCashflowUnavailable, match="no tiene pagos futuros"):
        await OnCashflowService(session).get("ZZZ9O", today=date(2026, 11, 6))


def test_ficha_route_for_on(client, monkeypatch):
    from datetime import date as _d
    from backend.app.api import routes
    from backend.app.db.models import Bond
    from backend.app.db.session import SessionLocal

    db = SessionLocal()
    if db.get(Bond, "YM34O") is None:
        db.add(Bond(ticker="YM34O", name="YPF 2034", currency="USD", law="NY", bond_type="ON",
                    maturity_date=_d(2034, 1, 17)))
        db.commit()
    db.close()

    # Sin sesión y sin la ON en bonistas.com: mensaje claro, no el genérico de "sin flujos"
    from backend.app.data import bonistas_payments_client as bpc
    monkeypatch.setattr(routes.on_cashflow_service.session, "get_cookie", lambda: None)
    routes.on_cashflow_service._cache.clear()
    with monkeypatch.context() as mp:
        async def nothing(self, after):
            return {}, {}
        mp.setattr(bpc.BonistasPaymentsClient, "fetch_schedules", nothing)
        mp.setattr(bpc.bonistas_payments, "_day", None)
        res = client.get("/api/v1/bonds/YM34O/cashflows")
        assert res.status_code == 422 and "Bull Market" in res.json()["detail"]
    monkeypatch.setattr(bpc.bonistas_payments, "_day", None)

    # Sin sesión: respaldo de bonistas.com (publica la especie D: YM34D)
    res = client.get("/api/v1/bonds/YM34O/cashflows")
    assert res.status_code == 200, res.text
    assert {r["source"] for r in res.json()} == {"BONISTAS"} and res.json()[-1]["residual_capital"] == 0
    routes.on_cashflow_service._cache.clear()

    # Con sesión activa: cronograma real de Bull Market
    monkeypatch.setattr(routes.on_cashflow_service.session, "get_cookie", lambda: TEST_BM_COOKIE)
    monkeypatch.setattr(routes.on_cashflow_service.session, "status", "ACTIVA")
    res = client.get("/api/v1/bonds/YM34O/cashflows")
    assert res.status_code == 200, res.text
    cfs = res.json()
    assert cfs[0]["source"] == "BULLMARKET" and cfs[0]["currency"] == "USD" and cfs[0]["payment_currency"] == "CCL"
    assert cfs[-1]["residual_capital"] == 0
