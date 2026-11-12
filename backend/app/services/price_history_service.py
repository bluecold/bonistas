"""
Historia de cierres diarios (Rava).

- Bonos que participan de los ratios: una descarga por día y por especie. Alimenta las bandas de
  21 ruedas y la media de un año de cada par (`arbitrage/ratios.py`); sin esta historia las bandas
  recién existirían después de ~21 ruedas de uso propio.
- Cualquier otra especie: a demanda, cuando se abre su ficha (`ensure`), y queda guardada por el día.
- Serie del CER (BCRA), también a demanda, para los flujos ajustados en fechas pasadas.
"""

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from backend.app.arbitrage.ratios import pair_specs
from backend.app.data.rava_client import RavaClient
from backend.app.data.bcra_client import BcraClient
from backend.app.db.models import DailyClose, IndexDaily
from backend.app.services.market_calendar import ART

logger = logging.getLogger(__name__)


def history_symbols() -> List[str]:
    """Especies de todos los bonos con ratio (D para los pares en dólares, pesos para los CER)."""
    return sorted({s for spec in pair_specs() for s in (spec.symbol_a, spec.symbol_b)})


class PriceHistoryService:
    def __init__(self, client: Optional[RavaClient] = None, bcra: Optional[BcraClient] = None):
        self.client = client or RavaClient()
        self.bcra = bcra or BcraClient()
        # Especies que Rava no tiene: no se vuelven a pedir en el día
        self._missing: Dict[str, date] = {}

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

    async def ensure(self, db: Session, symbols: Iterable[str],
                     today: Optional[date] = None) -> Dict[str, str]:
        """
        Deja en la base la historia de las especies pedidas si no se descargó hoy. Devuelve los
        errores por especie; si la descarga falla y hay historia de un día anterior, se usa esa.
        """
        today = today or datetime.now(ART).date()
        symbols = list(dict.fromkeys(s.upper() for s in symbols))
        last = dict(db.execute(
            select(DailyClose.symbol, func.max(DailyClose.fetched_at))
            .where(DailyClose.symbol.in_(symbols)).group_by(DailyClose.symbol)).all())
        pending: List[str] = []
        errors: Dict[str, str] = {}
        for sym in symbols:
            ts = last.get(sym)
            if ts is not None and ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if ts is not None and ts.astimezone(ART).date() >= today:
                continue
            if self._missing.get(sym) == today:
                errors[sym] = "sin datos en Rava"
                continue
            pending.append(sym)
        if not pending:
            return errors
        histories, fetch_errors = await self.client.fetch_histories(pending)
        now = datetime.now(timezone.utc)
        for sym, rows in histories.items():
            db.execute(delete(DailyClose).where(DailyClose.symbol == sym))
            db.add_all([DailyClose(symbol=sym, day=d, close=c, source="RAVA", fetched_at=now)
                        for d, c in rows])
        db.commit()
        for sym, err in fetch_errors.items():
            errors[sym] = err
            if err in ("HTTP 502", "HTTP 404", "sin filas"):
                self._missing[sym] = today
        return errors

    @staticmethod
    def closes(db: Session, symbol: str) -> List[Tuple[date, float]]:
        rows = db.execute(
            select(DailyClose.day, DailyClose.close)
            .where(DailyClose.symbol == symbol.upper(), DailyClose.close > 0)
            .order_by(DailyClose.day)).all()
        return [(d, float(c)) for d, c in rows]

    async def ensure_cer(self, db: Session, today: Optional[date] = None, years: int = 6) -> Dict[date, float]:
        """Serie diaria del CER (BCRA). Se descarga si falta o no llega hasta hoy."""
        today = today or datetime.now(ART).date()
        first, last = db.execute(
            select(func.min(IndexDaily.day), func.max(IndexDaily.day)).where(IndexDaily.name == "CER")).one()
        wanted_from = today - timedelta(days=365 * years)
        if last is None or last < today or first > wanted_from + timedelta(days=10):
            since = wanted_from if (last is None or first > wanted_from + timedelta(days=10)) else last - timedelta(days=5)
            try:
                rows = await self.bcra.fetch_series("CER", since, today + timedelta(days=45))
                if rows:
                    db.execute(delete(IndexDaily).where(IndexDaily.name == "CER", IndexDaily.day >= rows[0][0]))
                    db.add_all([IndexDaily(name="CER", day=d, value=v) for d, v in rows])
                    db.commit()
            except Exception as e:
                db.rollback()
                logger.warning(f"Serie del CER (BCRA): {e}")
        return {d: float(v) for d, v in db.execute(
            select(IndexDaily.day, IndexDaily.value).where(IndexDaily.name == "CER")).all()}
