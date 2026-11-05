"""Horario de renta fija: el de BYMA se acota a 10:30–17:00 (acciones/CEDEARs pueden ir hasta 18:00)."""

from datetime import date, datetime, time

import pytest

from backend.app.data.byma_client import MarketTime
from backend.app.services.market_calendar import ART, MarketCalendar

DAY = date(2026, 11, 5)


class FakeByma:
    def __init__(self, opening, closing):
        self.mt = MarketTime(is_working_day=True, opening=opening, closing=closing)

    async def fetch_market_time(self):
        return self.mt


def _at(h, m):
    return datetime(DAY.year, DAY.month, DAY.day, h, m, tzinfo=ART)


@pytest.mark.parametrize("opening,closing,expected", [
    (time(10, 30), time(18, 0), (time(10, 30), time(17, 0))),   # horario de acciones/CEDEARs → 17:00
    (time(10, 30), time(17, 0), (time(10, 30), time(17, 0))),
    (time(11, 0), time(14, 0), (time(11, 0), time(14, 0))),     # rueda reducida informada por BYMA
    (time(10, 0), time(17, 0), (time(10, 30), time(17, 0))),
])
async def test_window_clamped_to_fixed_income(opening, closing, expected):
    w = await MarketCalendar(FakeByma(opening, closing)).today(_at(12, 0))
    assert (w.opening, w.closing) == expected


async def test_no_realtime_polling_after_fixed_income_close(monkeypatch):
    from backend.app.config import settings
    monkeypatch.setattr(settings, "MARKET_HOURS_ONLY", True)
    cal = MarketCalendar(FakeByma(time(10, 30), time(18, 0)))
    assert await cal.is_trading(_at(16, 59))
    assert not await cal.is_trading(_at(17, 30))     # acciones siguen, bonos ya cerraron
    assert await cal.should_poll(_at(17, 20))        # BYMA demora 20 min: se captura el cierre
    assert not await cal.should_poll(_at(17, 45))
