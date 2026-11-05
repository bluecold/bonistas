"""
Ingesta del libro de órdenes: BYMA Open Data (mejores puntas, 20 min de demora), Bull Market
(5 niveles, tiempo real, con la sesión del trader) y la caución a 1 día.

- Solo se guarda una fila nueva por (fuente, especie, plazo) cuando cambió algo relevante
  (puntas, cantidades, último precio, volumen u operaciones). Así la base crece con la
  actividad real del mercado y no con la frecuencia de consulta.
- La caución en pesos al plazo más corto se guarda como indicador macro diario
  `CAUCION_1D_TNA` (en % TNA); es el costo "normal" de un día de diferencia entre CI y 24hs.
"""

import logging
from datetime import date, datetime, timezone
from decimal import Decimal
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set, Tuple

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.data.bullmarket_client import BullMarketClient, BullMarketError, SessionExpiredError
from backend.app.data.byma_client import BookRow, BymaClient, pick_overnight_caucion
from backend.app.services.bullmarket_session import BullMarketSession
from backend.app.db.models import BookQuote, MacroIndicator
from backend.app.services.source_health import source_health

logger = logging.getLogger(__name__)

Key = Tuple[str, str, str]  # (source, symbol, settlement)


def _depth_of(row) -> Optional[Dict[str, list]]:
    """Profundidad como JSON (solo si la fuente publica más de la mejor punta)."""
    bids, asks = getattr(row, "bids", None), getattr(row, "asks", None)
    if bids is None and asks is None:
        return None
    return {"bids": [list(x) for x in (bids or [])], "asks": [list(x) for x in (asks or [])]}


def _fingerprint(row) -> tuple:
    depth = row.depth if isinstance(row, BookQuote) else _depth_of(row)
    depth_fp = (tuple(map(tuple, depth.get("bids", []))), tuple(map(tuple, depth.get("asks", [])))) if depth else None
    return (row.bid, row.bid_qty, row.ask, row.ask_qty, row.last, row.volume_nominal, row.trades, depth_fp)


@dataclass
class LiveSnapshot:
    """Qué especies/plazos trajo la última consulta correcta de una fuente en tiempo real."""
    fetched_at: datetime
    keys: Set[Tuple[str, str]]   # (symbol, settlement)


class MarketBookService:
    SOURCE = "BYMA"

    BULLMARKET = "BULLMARKET"

    def __init__(self, byma: Optional[BymaClient] = None,
                 bullmarket: Optional[BullMarketClient] = None,
                 bm_session: Optional[BullMarketSession] = None):
        self.byma = byma or BymaClient()
        self.bullmarket = bullmarket or BullMarketClient()
        self.bm_session = bm_session or BullMarketSession()
        self._last: Dict[Key, tuple] = {}
        self._loaded_sources: set = set()
        self.live: Dict[str, LiveSnapshot] = {}
        self.bm_just_expired = False     # para la notificación de la etapa 5

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
                trade_time=r.trade_time, maturity_date=r.maturity_date, depth=_depth_of(r),
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

    async def ingest_bullmarket(self, db: Session) -> Dict[str, Any]:
        """
        Libros de bonos de Bull Market (CI y 24hs). Si la sesión está vencida o no hay cookie,
        no consulta. Si Bull Market rechaza la cookie, la marca como vencida y deja de insistir.
        """
        self.bm_just_expired = False
        sess = self.bm_session
        if not sess.should_poll:
            return {"skipped": sess.status}
        cookie = sess.get_cookie()
        try:
            rows = await self.bullmarket.fetch_books(cookie)
        except SessionExpiredError as e:
            self.live.pop(self.BULLMARKET, None)
            self.bm_just_expired = sess.mark_expired(str(e))
            source_health.failure(self.BULLMARKET, e)
            return {"error": str(e), "status": sess.status}
        except BullMarketError as e:
            sess.mark_error(str(e))
            source_health.failure(self.BULLMARKET, e)
            logger.warning(f"Bull Market: {e}")
            return {"error": str(e), "status": sess.status}
        try:
            stats = self.store_rows(db, rows, self.BULLMARKET)
        except Exception as e:
            db.rollback()
            source_health.failure(self.BULLMARKET, e)
            logger.error(f"Bull Market (guardado): {e}")
            return {"error": str(e), "status": sess.status}
        self.live[self.BULLMARKET] = LiveSnapshot(
            fetched_at=datetime.now(timezone.utc),
            keys={(r.symbol, r.settlement) for r in rows
                  if r.bid is not None or r.ask is not None or r.last is not None},
        )
        sess.mark_ok(len(rows))
        source_health.success(self.BULLMARKET, rows=len(rows), **stats)
        return {"books": stats, "rows": len(rows), "status": sess.status}

    def live_keys(self, source: str, max_age_seconds: float,
                  now: Optional[datetime] = None) -> Optional[Set[Tuple[str, str]]]:
        """Especies vigentes de una fuente en tiempo real, o None si la última consulta es vieja."""
        snap = self.live.get(source)
        if snap is None:
            return None
        now = now or datetime.now(timezone.utc)
        if (now - snap.fetched_at).total_seconds() > max_age_seconds:
            return None
        return snap.keys

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
