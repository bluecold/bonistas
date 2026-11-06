"""
Vista de mercado para los detectores de arbitraje.

Reúne, para un instante dado:
- Los libros (puntas) por especie y plazo, de una o más fuentes (BYMA con 20 min de demora y
  solo la mejor punta; Bull Market en tiempo real con 5 niveles). Los de Bull Market solo se
  usan si la última consulta correcta es reciente: si la sesión venció, se vuelve a BYMA.
- El tipo de cambio de referencia para convertir el tamaño de operación (USD) a nominales.
- La caución a 1 día (costo normal de financiar un día entre CI y 24hs).
- Los pagos (renta + amortización) que caen entre la liquidación CI y la de 24hs: el precio
  de un plazo los incluye y el del otro no (corte de cupón).

Convenciones:
- Precios por 100 VN, en la moneda de la especie (ARS, USD MEP o USD cable).
- Cantidades en nominales (VN).
- Un flujo con fecha de pago F pertenece al comprador si la liquidación S es anterior al día
  hábil previo a F (ver market_calendar.ex_date). Con S >= ex_date(F) el precio ya es "ex-cupón"
  (regla del trader: si paga mañana y compro hoy en 24hs, ya lo descuenta; y verificado con TX28:
  pago lunes 9/11, la liquidación del viernes 6/11 ya cotizaba ex-cupón).
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Dict, Iterable, List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.db.models import BookQuote, MacroIndicator, ReferenceBond
from backend.app.quant.cashflows import get_hard_dollar_schedule, base_ticker as hd_base
from backend.app.services.market_book_service import MarketBookService
from backend.app.services.market_calendar import ART, ex_date, next_business_day
from backend.app.services.reference_data_service import ReferenceDataService


@dataclass
class Level:
    price: float
    qty: float


@dataclass
class Book:
    symbol: str
    base: str
    currency: str            # ARS / MEP / CCL
    settlement: str          # CI / 24HS
    bids: List[Level]
    asks: List[Level]
    last: Optional[float]
    trade_time: Optional[str]
    timestamp: Optional[datetime]
    source: str
    prev_close: Optional[float] = None

    @property
    def best_bid(self) -> Optional[float]:
        return self.bids[0].price if self.bids else None

    @property
    def best_ask(self) -> Optional[float]:
        return self.asks[0].price if self.asks else None

    @property
    def mid(self) -> Optional[float]:
        if self.best_bid and self.best_ask:
            return (self.best_bid + self.best_ask) / 2.0
        return self.last


@dataclass
class Fill:
    avg_price: Optional[float]   # precio promedio para el nominal pedido (None si no alcanza)
    filled: float                # nominales disponibles hasta cubrir el pedido
    requested: float

    @property
    def complete(self) -> bool:
        return self.avg_price is not None and self.filled >= self.requested - 1e-9


def walk_book(levels: List[Level], nominal: float) -> Fill:
    """Recorre el libro hasta cubrir `nominal`. Si no alcanza, avg_price es None."""
    remaining, cost, filled = nominal, 0.0, 0.0
    for lv in levels:
        if remaining <= 0:
            break
        take = min(lv.qty, remaining)
        cost += take * lv.price
        filled += take
        remaining -= take
    if remaining > 1e-9 or filled <= 0:
        return Fill(None, filled, nominal)
    return Fill(cost / filled, filled, nominal)


def _depth_levels(raw) -> List[Level]:
    out = []
    for item in raw or []:
        try:
            p, qty = float(item[0]), float(item[1] or 0.0)
        except (TypeError, ValueError, IndexError):
            continue
        if p > 0:
            out.append(Level(p, qty))
    return out


def book_from_row(q: BookQuote) -> Book:
    depth = q.depth if isinstance(q.depth, dict) else None
    if depth and (depth.get("bids") or depth.get("asks")):
        bids, asks = _depth_levels(depth.get("bids")), _depth_levels(depth.get("asks"))
    else:
        bids = [Level(q.bid, q.bid_qty or 0.0)] if q.bid else []
        asks = [Level(q.ask, q.ask_qty or 0.0)] if q.ask else []
    return Book(q.symbol, q.base_ticker, q.currency, q.settlement, bids, asks, q.last,
                q.trade_time, q.timestamp, q.source, q.prev_close)


MIXED_SOURCE = "MIXTO"


def combined_source(*books: Optional["Book"]) -> str:
    """Fuente de una operación con varias patas: la común a todas, o MIXTO si difieren."""
    # Las ON de Bull Market se guardan como fuente aparte, pero son el mismo tiempo real
    sources = {"BULLMARKET" if b.source == "BULLMARKET_ON" else b.source for b in books if b is not None}
    if len(sources) == 1:
        return sources.pop()
    return MIXED_SOURCE if sources else "SIN_DATOS"


@dataclass
class MarketView:
    books: Dict[Tuple[str, str], Book]                 # (symbol, settlement) -> Book
    today: date
    next_bd: date
    mep_reference: Optional[float] = None              # ARS por USD MEP, para dimensionar
    caucion_tna_pct: Optional[float] = None
    flows_by_base: Dict[str, Tuple[str, List[Tuple[date, float]]]] = field(default_factory=dict)
    # Bonos cuyos flujos vienen de una sola fuente secundaria (Bruno618 o Mercados Argentina), sin
    # una segunda fuente que confirme las fechas. Cerca de un pago no se emite señal (un error de fecha simularía un desarbitraje).
    unverified_bases: set = field(default_factory=set)

    # ------------------------------------------------------------------ libros
    def book(self, symbol: str, settlement: str) -> Optional[Book]:
        return self.books.get((symbol, settlement))

    def by_base(self) -> Dict[str, Dict[Tuple[str, str], Book]]:
        """base -> {(moneda, plazo): Book}"""
        out: Dict[str, Dict[Tuple[str, str], Book]] = {}
        for b in self.books.values():
            out.setdefault(b.base, {})[(b.currency, b.settlement)] = b
        return out

    @property
    def settlement_days(self) -> int:
        """Días corridos entre la liquidación CI (hoy) y la de 24hs."""
        return (self.next_bd - self.today).days

    # ------------------------------------------------------------------ dimensionamiento
    def nominal_for_usd(self, usd: float, price_per_100: float, currency: str) -> Optional[float]:
        """Nominales equivalentes a `usd` dólares para una especie (precio por 100 VN)."""
        if not price_per_100 or price_per_100 <= 0:
            return None
        if currency in ("MEP", "CCL"):
            amount = usd
        else:
            if not self.mep_reference:
                return None
            amount = usd * self.mep_reference
        return amount / (price_per_100 / 100.0)

    # ------------------------------------------------------------------ flujos / cupones
    def flow_between(self, base: str, currency: str, after: date, upto: date,
                     fx_for_ars: Optional[float] = None) -> Tuple[float, str]:
        """
        Suma de los flujos que cortan entre las dos liquidaciones (after < ex_date(F) <= upto),
        por 100 VN, en la moneda de la especie: el precio de la liquidación `after` los incluye y
        el de `upto` no. Devuelve (monto, estado): 'SIN_PAGOS', 'AJUSTADO' o 'DESCONOCIDO'.
        """
        info = self.flows_by_base.get(base)
        if info is None:
            return 0.0, "DESCONOCIDO"
        if base in self.unverified_bases and any(
                abs((d - after).days) <= UNVERIFIED_FLOW_WINDOW_DAYS for d, _ in info[1]):
            return 0.0, "DESCONOCIDO"
        flow_ccy, flows = info
        amount = sum(a for d, a in flows if after < ex_date(d) <= upto)
        if amount == 0:
            return 0.0, "SIN_PAGOS"
        species_is_usd = currency in ("MEP", "CCL")
        if (flow_ccy == "USD") == species_is_usd:
            return amount, "AJUSTADO"
        # Flujo en USD pero especie en pesos (ej. AL30 en ARS): se convierte con el TC implícito
        if flow_ccy == "USD" and not species_is_usd:
            return (amount * fx_for_ars, "AJUSTADO") if fx_for_ars else (0.0, "DESCONOCIDO")
        return 0.0, "DESCONOCIDO"

    def implied_mep(self, base: str, settlement: str) -> Optional[float]:
        bb = self.by_base().get(base, {})
        ars, mep = bb.get(("ARS", settlement)), bb.get(("MEP", settlement))
        if ars and mep and ars.mid and mep.mid:
            return ars.mid / mep.mid
        return None


def _latest_macro(db: Session, name: str) -> Optional[float]:
    row = db.execute(
        select(MacroIndicator).where(MacroIndicator.name == name).order_by(MacroIndicator.date.desc())
    ).scalars().first()
    return float(row.value) if row else None


UNVERIFIED_FLOW_WINDOW_DAYS = 30


def _flows_for(refs_index: Dict[str, ReferenceBond], base: str,
               symbols: Iterable[str]) -> Optional[Tuple[str, List[Tuple[date, float]]]]:
    schedule = get_hard_dollar_schedule(hd_base(base))
    if schedule:
        flows: List[Tuple[date, float]] = []
        residual = 100.0
        for e in schedule:
            coupon = residual * e["coupon_tna"] / 2.0
            flows.append((e["date"], coupon + e["amort_pct"]))
            residual -= e["amort_pct"]
        return "USD", flows
    for t in [base, *symbols]:
        ref = refs_index.get(t)
        if ref is not None and ref.flows:
            ccy = "USD" if (ref.currency or "").upper() == "USD" else "ARS"
            return ccy, ReferenceDataService.flows_of(ref)
    return None


def build_market_view(
    db: Session,
    sources: Tuple[str, ...] = ("BYMA",),
    now: Optional[datetime] = None,
    book_service: Optional[MarketBookService] = None,
    live_max_age: Optional[Dict[str, float]] = None,
) -> MarketView:
    """
    Arma la vista con la última fila de cada especie/plazo. Si hay varias fuentes, la que
    aparece primero en `sources` tiene prioridad (ej. ("BULLMARKET", "BYMA")).

    `live_max_age` = {fuente: segundos}: para esas fuentes (en tiempo real) solo se usan las
    especies que vinieron en la última consulta correcta, y solo si no es más vieja que el
    límite. Así una sesión de Bull Market vencida no deja puntas viejas "pisando" a BYMA.
    """
    now = now or datetime.now(ART)
    today = now.astimezone(ART).date()
    svc = book_service or MarketBookService()
    live_max_age = live_max_age or {}

    books: Dict[Tuple[str, str], Book] = {}
    for source in reversed(sources):        # la de mayor prioridad sobrescribe al final
        allowed = None
        if source in live_max_age:
            allowed = svc.live_keys(source, live_max_age[source])
            if allowed is None:
                continue
        for q in svc.latest_books(db, source=source):
            if allowed is not None and (q.symbol, q.settlement) not in allowed:
                continue
            books[(q.symbol, q.settlement)] = book_from_row(q)

    view = MarketView(books=books, today=today, next_bd=next_business_day(today))
    view.caucion_tna_pct = _latest_macro(db, "CAUCION_1D_TNA")
    view.mep_reference = view.implied_mep("AL30", "24HS") or _latest_macro(db, "DOLAR_BOLSA")

    symbols_by_base: Dict[str, List[str]] = {}
    for b in books.values():
        symbols_by_base.setdefault(b.base, []).append(b.symbol)
    refs_index: Dict[str, ReferenceBond] = {}
    for ref in db.execute(select(ReferenceBond)).scalars():
        for t in [ref.ticker_base, *(ref.species or [])]:
            refs_index.setdefault(t, ref)
    for base, syms in symbols_by_base.items():
        f = _flows_for(refs_index, base, syms)
        for t in [base, *syms]:
            ref = refs_index.get(t)
            if ref is not None and ref.flows:
                secondary_only = ref.flows_source not in (None, "COMPARARBONOS") and not ref.flows_verified
                if secondary_only and f is not None and not get_hard_dollar_schedule(hd_base(base)):
                    view.unverified_bases.add(base)
                break
        if f is not None:
            view.flows_by_base[base] = f
    return view
