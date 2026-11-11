"""
Historia de cierres diarios (Rava) de los bonos que participan de los ratios.

Una descarga por día y por especie. Alimenta las bandas de 21 ruedas y la media de un año de
cada par (`arbitrage/ratios.py`); sin esta historia las bandas recién existirían después de
~21 ruedas de uso propio.
"""

import logging
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from backend.app.arbitrage.ratios import pair_specs
from backend.app.data.rava_client import RavaClient
from backend.app.db.models import DailyClose
from backend.app.services.market_calendar import ART

logger = logging.getLogger(__name__)


def history_symbols() -> List[str]:
    """Especies de todos los bonos con ratio (D para los pares en dólares, pesos para los CER)."""
    return sorted({s for spec in pair_specs() for s in (spec.symbol_a, spec.symbol_b)})


class PriceHistoryService:
    def __init__(self, client: Optional[RavaClient] = None):
        self.client = client or RavaClient()

    @staticmethod
    def is_stale(db: Session, today: Optional[date] = None) -> bool:
        """Falta alguna especie o la última descarga no es de hoy."""
        today = today or datetime.now(ART).date()
        rows = dict(db.execute(
            select(DailyClose.symbol, func.max(DailyClose.fetched_at)).group_by(DailyClose.symbol)).all())
        for symbol in history_symbols():
            last = rows.get(symbol)
            if last is None:
                return True
            if last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)
            if last.astimezone(ART).date() < today:
                return True
        return False

    async def refresh(self, db: Session) -> Dict[str, Any]:
        histories, errors = await self.client.fetch_histories(history_symbols())
        now = datetime.now(timezone.utc)
        for symbol, rows in histories.items():
            db.execute(delete(DailyClose).where(DailyClose.symbol == symbol))
            db.add_all([DailyClose(symbol=symbol, day=d, close=c, source="RAVA", fetched_at=now)
                        for d, c in rows])
        db.commit()
        if errors:
            logger.warning(f"Historia de Rava con errores: {errors}")
        return {"symbols": len(histories), "rows": sum(len(r) for r in histories.values()), "errors": errors}
