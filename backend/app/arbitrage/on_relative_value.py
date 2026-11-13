"""
Valor relativo de obligaciones negociables (informativo: no genera alertas).

Para cada ON en dólares con cronograma de Bull Market y precio en tiempo real:
- TIR y Modified Duration propias, con el precio de la especie D (MEP) o, si no cotiza, la C.
  Se calculan tres TIR: al precio medio, a la punta vendedora (lo que rinde si la compro) y a la
  compradora (lo que dejo de rendir si la vendo).
- Spread contra su propio emisor: TIR menos la TIR que "le corresponde" por duration según las
  otras ON del mismo emisor (interpolación lineal; sin extrapolar más de MAX_GAP_MD años).
- Spread contra el soberano: TIR menos la curva de Bonares/Globales (bonistas.com) a la misma MD.
- Ideas de canje dentro del mismo emisor: vender la que rinde menos (a la compradora) y comprar
  la que rinde más (a la vendedora), con duration parecida y descontando los costos.

Limitaciones que se informan: Bull Market no publica opciones de rescate anticipado (una ON muy
arriba de la par puede rendir menos de lo que dice la TIR al vencimiento) y el precio en dólares
MEP contra flujos pagados en cable mezcla dos tipos de dólar.
"""

from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

from backend.app.arbitrage.market_view import Book, MarketView
from backend.app.quant.cashflows import CashFlowItem
from backend.app.quant.fixed_income import calculate_duration_and_md, calculate_ytm

SETTLEMENT = "24HS"
LIQUID_MAX_SPREAD_PCT = 2.0      # puntas a más de 2% de distancia: poco líquida
MIN_MD_FOR_CURVE = 0.5           # las muy cortas tienen TIR muy sensible al precio
# Fuera de este rango no entra a las curvas ni a los canjes. TIR negativa: cotiza por encima de lo
# que va a pagar (vencimiento o rescate cercano); muy alta: posible default o dato erróneo.
PLAUSIBLE_TIR = (0.0, 40.0)
MAX_GAP_MD = 1.0                 # extrapolación máxima contra la ON del emisor más cercana
SWAP_MAX_MD_GAP = 1.0
SWAP_MIN_NET_BPS = 50.0
PARITY_CALL_WARNING = 103.0      # precio sobre el valor residual: posible rescate anticipado


@dataclass
class OnRow:
    ticker: str
    issuer: Optional[str]
    price_symbol: Optional[str] = None
    dollar: Optional[str] = None             # MEP / CCL: especie usada para el precio
    payment_currency: Optional[str] = None   # MEP / CCL: en qué dólar paga
    bid: Optional[float] = None
    ask: Optional[float] = None
    price: Optional[float] = None            # medio (o último si falta una punta)
    spread_pct: Optional[float] = None
    liquid: bool = False
    tir_pct: Optional[float] = None
    tir_buy_pct: Optional[float] = None      # comprando a la vendedora
    tir_sell_pct: Optional[float] = None     # vendiendo a la compradora
    md: Optional[float] = None
    residual: Optional[float] = None
    maturity: Optional[date] = None
    next_payment: Optional[date] = None
    tir_bonistas_pct: Optional[float] = None
    issuer_fit_pct: Optional[float] = None
    spread_vs_issuer_bps: Optional[float] = None
    sovereign_fit_pct: Optional[float] = None
    spread_vs_sovereign_bps: Optional[float] = None
    source: str = "BULLMARKET"
    flags: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class OnSwapIdea:
    issuer: str
    sell: str
    buy: str
    sell_tir_pct: float
    buy_tir_pct: float
    sell_md: float
    buy_md: float
    pickup_bps: float          # TIR comprada - TIR vendida (puede incluir alargar duration)
    curve_pickup_bps: float    # lo mismo, descontando lo que paga la curva del emisor por la duration
    cost_bps: float
    net_bps: float             # curve_pickup - costos: el desvío que se captura
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _cashflows(schedule: Any, settle: date) -> List[CashFlowItem]:
    return [
        CashFlowItem(date=r.date, days_from_settlement=(r.date - settle).days, interest_rate=0.0,
                     coupon_amount=r.coupon, amortization_amount=r.amortization,
                     total_cashflow=r.total, residual_capital=r.residual)
        for r in schedule.rows if r.date > settle
    ]


def _tir(price: Optional[float], cfs: List[CashFlowItem]) -> Optional[float]:
    if not price or not cfs:
        return None
    y = calculate_ytm(price, cfs)
    return round(y * 100.0, 3) if y is not None else None


def interpolate(points: List[Tuple[float, float]], x: float, max_gap: Optional[float] = None) -> Optional[float]:
    """Interpolación lineal de (md, tir) en x. Fuera del rango: el extremo, si está a <= max_gap."""
    pts = sorted(points)
    if not pts:
        return None
    if x <= pts[0][0]:
        return pts[0][1] if max_gap is None or pts[0][0] - x <= max_gap else None
    if x >= pts[-1][0]:
        return pts[-1][1] if max_gap is None or x - pts[-1][0] <= max_gap else None
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if x0 <= x <= x1:
            return y0 if x1 == x0 else y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return None


def _price_book(books: Dict[Tuple[str, str], Book]) -> Optional[Book]:
    for ccy in ("MEP", "CCL"):
        b = books.get((ccy, SETTLEMENT))
        if b is not None and (b.best_bid or b.best_ask or b.last):
            return b
    return None


def analyze_ons(
    view: Optional[MarketView],
    schedules: Dict[str, Any],
    issuers: Dict[str, str],
    bonistas_quotes: Dict[str, Any],
    sovereign_points: List[Tuple[float, float]],
    commission_pct: float,
) -> Tuple[List[OnRow], List[OnSwapIdea]]:
    settle = view.next_bd if view is not None else date.today()
    by_base = view.by_base() if view is not None else {}
    rows: List[OnRow] = []

    for ticker, sch in schedules.items():
        if (sch.currency or "").upper() != "USD":
            continue                                     # ON en pesos: otra curva, fuera del análisis
        cfs = _cashflows(sch, settle)
        if not cfs:
            continue
        row = OnRow(ticker=ticker, issuer=issuers.get(ticker),
                    payment_currency=getattr(sch, "payment_currency", None),
                    maturity=cfs[-1].date, next_payment=cfs[0].date,
                    residual=round(cfs[0].residual_capital + cfs[0].amortization_amount, 4))
        book = _price_book(by_base.get(ticker, {}))
        if book is not None:
            row.price_symbol, row.dollar = book.symbol, book.currency
            row.bid, row.ask, row.price = book.best_bid, book.best_ask, book.mid
            if row.bid and row.ask:
                row.spread_pct = round((row.ask - row.bid) / ((row.ask + row.bid) / 2) * 100, 3)
                row.liquid = row.spread_pct <= LIQUID_MAX_SPREAD_PCT
            row.tir_buy_pct = _tir(row.ask, cfs)
            row.tir_sell_pct = _tir(row.bid, cfs)
        else:
            # Sin libro en tiempo real: precio de bonistas.com (con demora) de la especie D
            q = bonistas_quotes.get(ticker[:-1] + "D") if ticker.endswith("O") else None
            if q is not None and q.get("price_mep"):
                row.price_symbol, row.dollar, row.price = q["ticker"], "MEP", q["price_mep"]
                row.source = "BONISTAS"
                row.flags.append("Sin puntas en Bull Market: precio de bonistas.com (con demora).")
        q_d = bonistas_quotes.get(ticker[:-1] + "D") if ticker.endswith("O") else None
        if q_d is not None:
            row.tir_bonistas_pct = q_d.get("ytm_percentage")

        row.tir_pct = _tir(row.price, cfs)
        if row.tir_pct is not None:
            _, md = calculate_duration_and_md(row.price, row.tir_pct / 100.0, cfs)
            row.md = round(md, 3) if md is not None else None
        if row.price and row.residual and row.price > row.residual * PARITY_CALL_WARNING / 100.0:
            row.flags.append("Cotiza sobre la par: si tiene rescate anticipado, la TIR real puede ser menor.")
        if row.dollar == "MEP" and row.payment_currency == "CCL":
            row.flags.append("Se compra con MEP y paga en cable: la TIR no incluye la brecha a favor.")
        if row.tir_pct is not None and row.tir_pct < PLAUSIBLE_TIR[0]:
            row.flags.append("TIR negativa: cotiza por encima de lo que va a pagar (suele indicar "
                             "vencimiento o rescate cercano). Fuera de curvas y canjes.")
        elif row.tir_pct is not None and row.tir_pct > PLAUSIBLE_TIR[1]:
            row.flags.append("TIR muy alta: posible default o dato erróneo. Fuera de curvas y canjes.")
        rows.append(row)

    def in_curve(r: OnRow) -> bool:
        return (r.tir_pct is not None and r.md is not None and r.md >= MIN_MD_FOR_CURVE
                and PLAUSIBLE_TIR[0] <= r.tir_pct <= PLAUSIBLE_TIR[1])

    # Curva del emisor (sin la propia ON) y del soberano
    by_issuer: Dict[str, List[OnRow]] = {}
    for r in rows:
        if r.issuer and in_curve(r):
            by_issuer.setdefault(r.issuer, []).append(r)
    for r in rows:
        if r.md is None or r.tir_pct is None:
            continue
        peers = [(p.md, p.tir_pct) for p in by_issuer.get(r.issuer or "", []) if p.ticker != r.ticker]
        fit = interpolate(peers, r.md, MAX_GAP_MD) if peers else None
        if fit is not None:
            r.issuer_fit_pct = round(fit, 3)
            r.spread_vs_issuer_bps = round((r.tir_pct - fit) * 100.0, 1)
        sov = sovereign_fit(sovereign_points, r.md)
        if sov is not None:
            r.sovereign_fit_pct = round(sov, 3)
            r.spread_vs_sovereign_bps = round((r.tir_pct - sov) * 100.0, 1)

    # Ideas de canje dentro del emisor: solo con puntas reales de las dos ON
    ideas: List[OnSwapIdea] = []
    for issuer, peers in by_issuer.items():
        liquid = [p for p in peers if p.liquid and p.tir_sell_pct is not None and p.tir_buy_pct is not None
                  and p.issuer_fit_pct is not None]
        for a in liquid:
            for b in liquid:
                if a.ticker == b.ticker or abs(a.md - b.md) > SWAP_MAX_MD_GAP:
                    continue
                pickup = (b.tir_buy_pct - a.tir_sell_pct) * 100.0
                # Spread ejecutable de cada una contra la curva del emisor: así no cuenta como
                # "ganancia" el rendimiento extra que paga cualquier ON más larga del mismo emisor
                curve_pickup = ((b.tir_buy_pct - b.issuer_fit_pct) - (a.tir_sell_pct - a.issuer_fit_pct)) * 100.0
                cost = 2 * commission_pct / max(b.md, 0.1) * 100.0   # 2 operaciones, en bps de TIR
                net = curve_pickup - cost
                # También tiene que rendir más en términos absolutos: perder TIR para "ganar contra
                # la curva" no es una idea que se pueda explicar en el broker
                if net < SWAP_MIN_NET_BPS or pickup - cost < 0:
                    continue
                notes = [f"Vender {a.ticker} a {a.bid} ({a.dollar}) y comprar {b.ticker} a {b.ask} ({b.dollar})."]
                if a.payment_currency != b.payment_currency:
                    notes.append(f"Cambia el dólar de pago: {a.payment_currency} → {b.payment_currency}.")
                notes.append("Comparar condiciones (rescate, garantías, prelación) antes de canjear.")
                ideas.append(OnSwapIdea(
                    issuer=issuer, sell=a.ticker, buy=b.ticker, sell_tir_pct=a.tir_sell_pct,
                    buy_tir_pct=b.tir_buy_pct, sell_md=a.md, buy_md=b.md, pickup_bps=round(pickup, 1),
                    curve_pickup_bps=round(curve_pickup, 1), cost_bps=round(cost, 1),
                    net_bps=round(net, 1), notes=notes,
                ))
    ideas.sort(key=lambda i: i.net_bps, reverse=True)
    rows.sort(key=lambda r: ((r.issuer or "~"), r.md if r.md is not None else 99))
    return rows, ideas[:20]


def sovereign_fit(points: List[Tuple[float, float]], md: float) -> Optional[float]:
    """
    TIR soberana a una duration: ajuste TIR = a + b·ln(MD) por mínimos cuadrados sobre Bonares y
    Globales. Unir los puntos de a pares exagera el ruido (AO27 rinde 4% con MD 0.9; AL29 14%).
    Solo dentro del rango de durations de la curva (sin extrapolar).
    """
    import math
    pts = [(math.log(x), y) for x, y in points if x and x > 0]
    if len(pts) < 3 or md <= 0:
        return None
    lo, hi = min(x for x, _ in points), max(x for x, _ in points)
    if not (lo <= md <= hi):
        return None
    n = len(pts)
    mx = sum(x for x, _ in pts) / n
    my = sum(y for _, y in pts) / n
    sxx = sum((x - mx) ** 2 for x, _ in pts)
    if sxx == 0:
        return my
    b = sum((x - mx) * (y - my) for x, y in pts) / sxx
    return my + b * (math.log(md) - mx)


def sovereign_curve(quotes: List[Dict[str, Any]]) -> List[Tuple[float, float]]:
    """(MD, TIR) de Bonares/Globales (especie en pesos de bonistas.com, la de referencia)."""
    return [(q["modified_duration"], q["ytm_percentage"]) for q in quotes
            if q.get("bond_type") == "HARD_DOLLAR" and q.get("price_ars")
            and q.get("modified_duration") and q.get("ytm_percentage")]


def profile_block(base: str, issuer: Optional[str], rows: List[OnRow],
                  quotes: Dict[str, Any]) -> Dict[str, Any]:
    """
    Bloque de obligación negociable para la ficha: la ON contra su emisor y contra el soberano,
    liquidez (puntas y volumen), en qué dólar paga y las demás ON de la misma empresa.

    `rows`: salida de `analyze_ons` para las ON del emisor (incluida la de la ficha, `base`).
    `quotes`: cotizaciones de bonistas.com por especie (paridad y volumen, con demora).
    """
    def stem(t: str) -> str:
        return t[:-1] if t[-1:] in ("O", "D", "C") else t

    def parity(t: str) -> Optional[float]:
        for sym in (stem(t) + "D", t):
            q = quotes.get(sym)
            if q is not None and q.get("parity_percentage"):
                return round(float(q["parity_percentage"]), 2)
        return None

    own = next((r for r in rows if r.ticker == base), None)
    group = [r for r in rows if r.ticker == base or (issuer and r.issuer == issuer)]
    group.sort(key=lambda r: (r.maturity or date.max, r.ticker))
    peers = [{
        "ticker": r.ticker, "price_symbol": r.price_symbol, "current": r.ticker == base,
        "maturity": r.maturity.isoformat() if r.maturity else None,
        "price": r.price, "dollar": r.dollar, "price_source": r.source if r.price else None,
        "tir_pct": r.tir_pct, "md": r.md, "parity_pct": parity(r.ticker),
        "spread_vs_issuer_bps": r.spread_vs_issuer_bps, "spread_pct": r.spread_pct, "liquid": r.liquid,
        "payment_currency": r.payment_currency,
    } for r in group]

    volumes = []
    for suffix in ("O", "D", "C"):
        q = quotes.get(stem(base) + suffix)
        if q is not None and q.get("volume_millions"):
            volumes.append({"symbol": stem(base) + suffix, "millions": round(float(q["volume_millions"]), 4)})

    out: Dict[str, Any] = {
        "base": base, "issuer": issuer, "peers": peers, "other_peers": sum(1 for p in peers if not p["current"]),
        "volumes": volumes, "has_schedule": own is not None,
        "payment_currency": None, "price_dollar": None, "price_source": None, "residual": None,
        "bid": None, "ask": None, "spread_pct": None, "liquid": None,
        "tir_buy_pct": None, "tir_sell_pct": None,
        "issuer_fit_pct": None, "spread_vs_issuer_bps": None,
        "sovereign_fit_pct": None, "spread_vs_sovereign_bps": None, "flags": [],
    }
    if own is not None:
        out.update(
            payment_currency=own.payment_currency, price_dollar=own.dollar, price_source=own.source,
            residual=own.residual, bid=own.bid, ask=own.ask, spread_pct=own.spread_pct,
            liquid=own.liquid if own.spread_pct is not None else None,
            tir_buy_pct=own.tir_buy_pct, tir_sell_pct=own.tir_sell_pct,
            issuer_fit_pct=own.issuer_fit_pct, spread_vs_issuer_bps=own.spread_vs_issuer_bps,
            sovereign_fit_pct=own.sovereign_fit_pct, spread_vs_sovereign_bps=own.spread_vs_sovereign_bps,
            flags=list(own.flags),
        )
    return out
