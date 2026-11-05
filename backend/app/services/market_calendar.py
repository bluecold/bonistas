"""
Calendario de mercado: decide si corresponde consultar fuentes de cotizaciones.

Usa el endpoint `market-time` de BYMA (informa si hoy es día hábil y el horario de rueda),
consultado una vez por día. Si BYMA no responde, se asume lunes a viernes 10:30–17:00.
La ventana de consulta se extiende `delay_minutes` después del cierre porque BYMA Open Data
publica con 20 minutos de demora.
"""

import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from backend.app.config import settings
from backend.app.data.byma_client import BymaClient, MarketTime

logger = logging.getLogger(__name__)

ART = ZoneInfo(settings.TIMEZONE)
DEFAULT_OPEN = time(10, 30)
DEFAULT_CLOSE = time(17, 0)


@dataclass
class MarketWindow:
    day: date
    is_working_day: bool
    opening: time
    closing: time
    source: str  # 'BYMA' o 'FALLBACK'

    def is_open_for_polling(self, now: datetime, lead_minutes: int = 5, delay_minutes: int = 25) -> bool:
        if not self.is_working_day:
            return False
        local = now.astimezone(ART)
        start = datetime.combine(self.day, self.opening, ART) - timedelta(minutes=lead_minutes)
        end = datetime.combine(self.day, self.closing, ART) + timedelta(minutes=delay_minutes)
        return start <= local <= end

    def to_dict(self, now: Optional[datetime] = None) -> dict:
        now = now or datetime.now(ART)
        return {
            "date": self.day.isoformat(),
            "is_working_day": self.is_working_day,
            "opening": self.opening.strftime("%H:%M"),
            "closing": self.closing.strftime("%H:%M"),
            "source": self.source,
            "polling_active": self.is_open_for_polling(now),
        }


def next_business_day(d: date) -> date:
    """Siguiente día hábil (solo saltea fines de semana; los feriados los informa BYMA día a día)."""
    nxt = d + timedelta(days=1)
    while nxt.weekday() >= 5:
        nxt += timedelta(days=1)
    return nxt


def previous_business_day(d: date) -> date:
    nxt = d - timedelta(days=1)
    while nxt.weekday() >= 5:
        nxt -= timedelta(days=1)
    return nxt


def ex_date(payment: date) -> date:
    """
    Primer día de liquidación que ya NO cobra el pago ("ex-cupón"): el día hábil anterior a la
    fecha efectiva de pago (si el pago cae en fin de semana, se paga el día hábil siguiente).
    Verificado con TX28 (pago lun 9/11/2026): la operación en 24hs que liquida el vie 6/11 ya
    cotizaba ex-cupón, y la de CI que liquida el jue 5/11 todavía incluía el pago.
    """
    effective = payment
    while effective.weekday() >= 5:
        effective += timedelta(days=1)
    return previous_business_day(effective)


class MarketCalendar:
    def __init__(self, byma: Optional[BymaClient] = None):
        self.byma = byma or BymaClient()
        self._cached: Optional[MarketWindow] = None

    async def today(self, now: Optional[datetime] = None) -> MarketWindow:
        now = now or datetime.now(ART)
        today = now.astimezone(ART).date()
        if self._cached and self._cached.day == today and self._cached.source == "BYMA":
            return self._cached
        try:
            mt: MarketTime = await self.byma.fetch_market_time()
            window = MarketWindow(today, mt.is_working_day, mt.opening, mt.closing, "BYMA")
        except Exception as e:
            logger.warning(f"No se pudo consultar el horario de BYMA, se asume L-V 10:30-17:00: {e}")
            window = MarketWindow(today, today.weekday() < 5, DEFAULT_OPEN, DEFAULT_CLOSE, "FALLBACK")
        self._cached = window
        return window

    async def should_poll(self, now: Optional[datetime] = None) -> bool:
        if not settings.MARKET_HOURS_ONLY:
            return True
        now = now or datetime.now(ART)
        return (await self.today(now)).is_open_for_polling(now)

    async def is_trading(self, now: Optional[datetime] = None) -> bool:
        """Rueda abierta (con 5 min de anticipación y 2 de gracia), para fuentes en tiempo real."""
        if not settings.MARKET_HOURS_ONLY:
            return True
        now = now or datetime.now(ART)
        return (await self.today(now)).is_open_for_polling(now, lead_minutes=5, delay_minutes=2)
