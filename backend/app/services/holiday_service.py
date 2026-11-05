"""
Feriados de mercado: se descargan de MAE (próximos feriados de Argentina y EE.UU.), se guardan
en la tabla market_holidays (se conservan los ya pasados) y se cargan en el calendario de días
hábiles que usan las liquidaciones (24hs), la caución y el corte de cupón.
"""

import logging
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.data.mae_client import Holiday, MaeClient
from backend.app.db.models import MarketHoliday
from backend.app.services.market_calendar import set_ar_holidays
from backend.app.services.source_health import source_health

logger = logging.getLogger(__name__)


def is_stale(db: Session, today: Optional[date] = None) -> bool:
    """True si nunca se descargaron feriados o la última descarga no es de hoy."""
    from sqlalchemy import func
    last = db.execute(select(func.max(MarketHoliday.fetched_at))).scalar()
    if last is None:
        return True
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    from backend.app.services.market_calendar import ART
    return last.astimezone(ART).date() < (today or date.today())


def load_into_calendar(db: Session) -> int:
    days = [h.day for h in db.execute(select(MarketHoliday).where(MarketHoliday.country == "AR")).scalars()]
    set_ar_holidays(days)
    return len(days)


def store(db: Session, holidays: List[Holiday]) -> int:
    now = datetime.now(timezone.utc)
    for h in holidays:
        row = db.get(MarketHoliday, (h.day, h.country))
        if row is None:
            db.add(MarketHoliday(day=h.day, country=h.country, name=h.name, source="MAE", fetched_at=now))
        else:
            row.name, row.fetched_at = h.name, now
    db.commit()
    return len(holidays)


async def refresh(db: Session, client: Optional[MaeClient] = None, today: Optional[date] = None) -> Dict[str, Any]:
    client = client or MaeClient()
    today = today or date.today()
    try:
        holidays = await client.fetch_holidays(today)
        n = store(db, holidays)
        loaded = load_into_calendar(db)
        source_health.success("MAE", holidays=n)
        return {"fetched": n, "ar_in_calendar": loaded}
    except Exception as e:
        db.rollback()
        source_health.failure("MAE", e)
        logger.warning(f"Feriados MAE: {e}")
        load_into_calendar(db)          # se siguen usando los guardados
        return {"error": str(e)}


def upcoming(db: Session, today: Optional[date] = None, limit: int = 6) -> List[Dict[str, Any]]:
    today = today or date.today()
    rows = db.execute(select(MarketHoliday).where(MarketHoliday.day >= today)
                      .order_by(MarketHoliday.day).limit(limit)).scalars()
    return [{"date": r.day.isoformat(), "country": r.country, "name": r.name} for r in rows]
