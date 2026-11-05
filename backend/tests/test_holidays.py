"""Feriados de mercado (MAE): parseo, calendario de días hábiles y efecto en liquidación y cupón."""

from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.arbitrage.ci_24hs import detect_ci_vs_24hs
from backend.app.arbitrage.market_view import Book, Level, MarketView
from backend.app.data.mae_client import Holiday, infer_date, parse_holidays
from backend.app.db.models import MarketHoliday
from backend.app.db.session import Base
from backend.app.services import holiday_service
from backend.app.services.market_calendar import ex_date, next_business_day, set_ar_holidays
from backend.app.services.trading_settings import TradingParams
from backend.tests.conftest import _load

TODAY = date(2026, 11, 5)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    s = sessionmaker(bind=engine)()
    try:
        yield s
    finally:
        s.close()


def test_infer_year_from_text():
    assert infer_date("9 de noviembre", TODAY) == date(2026, 11, 9)
    assert infer_date("1 de enero", TODAY) == date(2027, 1, 1)          # ya pasó este año
    assert infer_date("5 de noviembre", TODAY) == date(2026, 11, 5)
    assert infer_date("31 de febrero", TODAY) is None and infer_date("mañana", TODAY) is None


def test_parse_real_response():
    hs = parse_holidays(_load("mae_feriados.json"), TODAY)
    assert Holiday(date(2026, 11, 9), "AR", "Visita de Su Santidad el Papa León XIV") in hs
    assert any(h.country == "US" and h.day == date(2026, 11, 26) for h in hs)
    assert all(h.country in ("AR", "US") for h in hs)


def test_business_days_skip_ar_holidays_only():
    set_ar_holidays([date(2026, 11, 9)])
    assert next_business_day(date(2026, 11, 6)) == date(2026, 11, 10)   # viernes -> martes
    assert next_business_day(date(2026, 11, 5)) == date(2026, 11, 6)
    # pago en feriado: se paga el martes; el corte es el viernes anterior
    assert ex_date(date(2026, 11, 9)) == date(2026, 11, 6)
    assert ex_date(date(2026, 11, 10)) == date(2026, 11, 6)
    set_ar_holidays([])
    assert next_business_day(date(2026, 11, 6)) == date(2026, 11, 9)


def test_caucion_days_include_holiday():
    set_ar_holidays([date(2026, 11, 9)])
    fri, tue = date(2026, 11, 6), next_business_day(date(2026, 11, 6))
    b = lambda st, bid, ask: Book("XX27D", "XX27", "MEP", st, [Level(bid, 1e9)], [Level(ask, 1e9)], None, None, None, "BYMA")
    v = MarketView(books={("XX27D", "CI"): b("CI", 101.0, 101.5), ("XX27D", "24HS"): b("24HS", 99.5, 100.0)},
                   today=fri, next_bd=tue, mep_reference=1585.0, caucion_tna_pct=26.1,
                   flows_by_base={"XX27": ("USD", [(date(2027, 6, 30), 100.0)])})
    params = TradingParams(commission_pct=0.11, min_net_profit_pct=0.40, trade_size_usd=500)
    o = next(o for o in detect_ci_vs_24hs(v, params) if o.direction == "COMPRAR_CI_VENDER_24HS")
    assert o.days == 4 and o.carry_pct == pytest.approx(26.1 * 4 / 365, abs=1e-4)


async def test_refresh_stores_and_loads(db):
    res = await holiday_service.refresh(db, today=TODAY)
    assert res["fetched"] == 7 and res["ar_in_calendar"] == 5
    assert next_business_day(date(2026, 11, 6)) == date(2026, 11, 10)
    assert db.get(MarketHoliday, (date(2026, 11, 26), "US")).name.startswith("Día de Acción")
    up = holiday_service.upcoming(db, TODAY, limit=2)
    assert up[0] == {"date": "2026-11-09", "country": "AR", "name": "Visita de Su Santidad el Papa León XIV"}


async def test_refresh_failure_keeps_stored(db, monkeypatch):
    db.add(MarketHoliday(day=date(2026, 12, 25), country="AR", name="Navidad", source="MAE"))
    db.commit()
    from backend.app.data.mae_client import MaeClient

    async def boom(self):
        raise RuntimeError("sin conexión")

    monkeypatch.setattr(MaeClient, "fetch_raw", boom)
    res = await holiday_service.refresh(db, today=TODAY)
    assert "error" in res and next_business_day(date(2026, 12, 24)) == date(2026, 12, 28)


def test_status_lists_holidays(client):
    st = client.get("/api/v1/status").json()
    assert "settlement_24hs" in st and isinstance(st["holidays"], list)


async def test_is_stale(db):
    assert holiday_service.is_stale(db, TODAY)
    await holiday_service.refresh(db, today=TODAY)
    assert not holiday_service.is_stale(db, date.today())

