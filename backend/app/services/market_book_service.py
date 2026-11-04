"""
Ingesta del libro de órdenes (mejores puntas) desde BYMA Open Data y de la caución a 1 día.

- Solo se guarda una fila nueva por (fuente, especie, plazo) cuando cambió algo relevante
  (puntas, cantidades, último precio, volumen u operaciones). Así la base crece con la
  actividad real del mercado y no con la frecuencia de consulta.
- La caución en pesos al plazo más corto se guarda como indicador macro diario
  `CAUCION_1D_TNA` (en % TNA); es el costo "normal" de un día de diferencia entre CI y 24hs.
"""

import logging
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.data.byma_client import BookRow, BymaClient, pick_overnight_caucion
from backend.app.db.models import BookQuote, MacroIndicator
from backend.app.services.source_health import source_health

logger = logging.getLogger(__name__)

Key = Tuple[str, str, str]  # (source, symbol, settlement)


def _fingerprint(row) -> tuple:
    return (row.bid, row.bid_qty, row.ask, row.ask_qty, row.last, row.volume_nominal, row.trades)


class MarketBookService:
    SOURCE = "BYMA"

    def __init__(self, byma: Optional[BymaClient] = None):
        self.byma = byma or BymaClient()
        self._last: Dict[Key, tuple] = {}
        self._loaded_sources: set = set()

    # ------------------------------------------------------------------ helpers
    def _ensure_cache(self, db: Session, source: str) -> None:
        """Carga la última fila guardada por especie/plazo para comparar sin consultar la base."""
        if source in self._loaded_sources:
            return
        for q in self.latest_books(db, source=source):
            self._last[(source, q.symbol, q.settlement)] = _fingerprint(q)
        self._loaded_sources.add(source)

    def store_rows(self, db: Session, rows: List[BookRow], source: str) -> Dict[str, int]:
        self._ensure_cache(db, source)
        now = datetime.now(timezone.utc)
        stored = unchanged = empty = 0
        for r in rows:
            if r.bid is None and r.ask is None and r.last is None:
                empty += 1
                continue
            key = (source, r.symbol, r.settlement)
            fp = _fingerprint(r)
            if self._last.get(key) == fp:
                unchanged += 1
                continue
            db.add(BookQuote(
                timestamp=now, source=source, symbol=r.symbol, base_ticker=r.base_ticker,
                currency=r.currency, settlement=r.settlement, bid=r.bid, bid_qty=r.bid_qty,
                ask=r.ask, ask_qty=r.ask_qty, last=r.last, prev_close=r.prev_close,
                volume_nominal=r.volume_nominal, volume_amount=r.volume_amount, trades=r.trades,
                trade_time=r.trade_time, maturity_date=r.maturity_date,
            ))
            self._last[key] = fp
            stored += 1
        db.commit()
        return {"stored": stored, "unchanged": unchanged, "empty": empty}

    @staticmethod
    def _upsert_macro(db: Session, name: str, day: date, value: float, source: str) -> None:
        existing = db.execute(
            select(MacroIndicator).where(MacroIndicator.date == day, MacroIndicator.name == name)
        ).scalar_one_or_none()
        if existing:
            existing.value = Decimal(str(value))
            existing.source = source
        else:
            db.add(MacroIndicator(date=day, name=name, value=Decimal(str(value)), source=source))

    # ------------------------------------------------------------------ ingesta
    async def ingest_byma(self, db: Session) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        try:
            rows = await self.byma.fetch_bond_books()
            result["books"] = self.store_rows(db, rows, self.SOURCE)
            source_health.success("BYMA", rows=len(rows), **result["books"])
        except Exception as e:
            db.rollback()
            source_health.failure("BYMA", e)
            logger.error(f"BYMA libros: {e}")
            result["books_error"] = str(e)

        try:
            caucion = pick_overnight_caucion(await self.byma.fetch_cauciones_raw())
            if caucion:
                self._upsert_macro(db, "CAUCION_1D_TNA", date.today(), caucion["tna_pct"], "BYMA")
                db.commit()
            result["caucion"] = caucion
        except Exception as e:
            db.rollback()
            logger.warning(f"BYMA cauciones: {e}")
            result["caucion_error"] = str(e)
        return result

    # ------------------------------------------------------------------ consultas
    def latest_books(
        self,
        db: Session,
        source: str = "BYMA",
        settlement: Optional[str] = None,
        base_ticker: Optional[str] = None,
    ) -> List[BookQuote]:
        """Última fila de cada especie (y plazo) para una fuente."""
        sub = select(func.max(BookQuote.id).label("max_id")).where(BookQuote.source == source)
        if settlement:
            sub = sub.where(BookQuote.settlement == settlement.upper())
        if base_ticker:
            sub = sub.where(BookQuote.base_ticker == base_ticker.upper())
        sub = sub.group_by(BookQuote.symbol, BookQuote.settlement).subquery()
        q = select(BookQuote).join(sub, BookQuote.id == sub.c.max_id).order_by(BookQuote.symbol)
        return list(db.execute(q).scalars())
