"""
Precios ejecutables para el simulador de swaps.

Una rotación se hace contra las puntas: se vende a la compradora y se compra a la vendedora,
recorriendo el libro hasta cubrir la cantidad. El último operado puede quedar lejos de eso (en
AN29D/AO29D del 12/11/2026 daba 1,0417 nominales por nominal cuando con puntas eran 1,0384).

Orden de fuentes por pata: Bull Market en tiempo real (5 niveles) si la última consulta es
reciente; si no, BYMA del día (solo la mejor punta, 20 min de demora); si no hay libro, el
último operado de bonistas.com.
"""

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.arbitrage.market_view import Book, Level, book_from_row
from backend.app.db.models import BookQuote
from backend.app.services.market_book_service import MarketBookService
from backend.app.services.market_calendar import ART


@dataclass
class LegPrice:
    symbol: str
    price: float
    kind: str                       # 'PUNTAS' | 'ULTIMO'
    source: str                     # 'BULLMARKET' | 'BYMA' | 'BONISTAS'
    depth_ok: Optional[bool] = None
    available: Optional[float] = None       # nominales visibles en el libro, si no alcanzan


def _latest_row(db: Session, source: str, symbol: str, settlement: str) -> Optional[BookQuote]:
    return db.execute(
        select(BookQuote).where(BookQuote.source == source, BookQuote.symbol == symbol,
                                BookQuote.settlement == settlement)
        .order_by(BookQuote.id.desc())).scalars().first()


def find_book(db: Session, svc: MarketBookService, symbol: str, settlement: str,
              live_max_age: float, today: Optional[date] = None) -> Optional[Book]:
    for source in (svc.BULLMARKET, svc.BULLMARKET_ON):
        keys = svc.live_keys(source, max_age_seconds=live_max_age)
        if keys and (symbol, settlement) in keys:
            row = _latest_row(db, source, symbol, settlement)
            if row is not None:
                return book_from_row(row)
    row = _latest_row(db, "BYMA", symbol, settlement)
    if row is None or row.timestamp is None:
        return None
    ts = row.timestamp if row.timestamp.tzinfo else row.timestamp.replace(tzinfo=timezone.utc)
    today = today or datetime.now(ART).date()
    return book_from_row(row) if ts.astimezone(ART).date() == today else None


def book_for_leg(db: Session, svc: MarketBookService, ticker: str, currency: str, settlement: str,
                 live_max_age: float, today: Optional[date] = None) -> Optional[Book]:
    """Libro de la especie en la moneda de la operación (AL30 en dólares => AL30D)."""
    wanted = "MEP" if currency == "USD" else "ARS"
    candidates = [ticker] + ([ticker + "D"] if currency == "USD" and not ticker.endswith("D") else [])
    for symbol in candidates:
        book = find_book(db, svc, symbol, settlement, live_max_age, today)
        if book is not None and book.currency == wanted:
            return book
    return None


def _average(levels: List[Level], nominal: float):
    """Precio promedio recorriendo el libro. Si no alcanza, el resto se valúa al último nivel visible."""
    remaining, cost, visible = nominal, 0.0, 0.0
    for lv in levels:
        if remaining <= 0:
            break
        take = min(lv.qty, remaining)
        cost += take * lv.price
        visible += take
        remaining -= take
    if remaining > 1e-9:
        cost += remaining * levels[-1].price
        return cost / nominal, False, visible
    return cost / nominal, True, None


def _source(book: Book) -> str:
    return "BULLMARKET" if book.source.startswith("BULLMARKET") else book.source


def sell_leg(book: Optional[Book], nominal: float, last: float, symbol: str) -> LegPrice:
    """Vender `nominal` contra la punta compradora."""
    if book is None or not book.bids or nominal <= 0:
        return LegPrice(symbol, last, "ULTIMO", "BONISTAS")
    price, ok, visible = _average(book.bids, nominal)
    return LegPrice(book.symbol, price, "PUNTAS", _source(book), ok, visible)


def buy_leg(book: Optional[Book], cash: float, fee_rate: float, last: float, symbol: str) -> LegPrice:
    """Comprar con `cash` contra la punta vendedora (la cantidad depende del precio: se itera)."""
    if book is None or not book.asks or cash <= 0:
        return LegPrice(symbol, last, "ULTIMO", "BONISTAS")
    price, ok, visible = book.asks[0].price, True, None
    for _ in range(4):
        nominal = cash / ((price / 100.0) * (1.0 + fee_rate))
        price, ok, visible = _average(book.asks, nominal)
    return LegPrice(book.symbol, price, "PUNTAS", _source(book), ok, visible)


def describe(leg: LegPrice, side: str) -> Optional[str]:
    """Aviso para el usuario sobre el precio de una pata (None si no hay nada que avisar)."""
    if leg.kind == "ULTIMO":
        return (f"{leg.symbol}: sin puntas disponibles, se usa el último operado de bonistas.com. "
                f"El precio real de {side} puede ser distinto.")
    if leg.depth_ok is False:
        return (f"{leg.symbol}: el libro visible cubre solo {leg.available:,.0f} nominales".replace(",", ".")
                + f" para la {side}; el resto se calculó al último nivel visible.")
    if leg.source == "BYMA":
        return f"{leg.symbol}: puntas de BYMA con 20 minutos de demora (sin sesión de Bull Market)."
    return None
