"""
Curvas de rendimiento agrupadas por familia de bonos (como las muestran las pantallas
profesionales), con curva ajustada y desvío de cada bono contra su curva.

Clasificación: la de CompararBonos (campo `tipo` de los datos de referencia diarios), que
separa soberanos, provinciales, LECAP/BONCAP, CER, dollar linked, TAMAR, duales y además
trae soberanos de la región y Treasuries de EE.UU. Las ONs no entran en ninguna curva.

Un punto por bono (no por especie): TIR y duration de Bonistas (intradiario) de la especie
preferida (la D para bonos en dólares, la de pesos para bonos en pesos); si no hay, los
valores diarios de CompararBonos.

Si un bono no tiene TIR publicada (ej. provinciales), se calcula con el motor propio: flujos
de CompararBonos + precio de BYMA (medio de las puntas o último, especie D, 24hs), con
liquidación al día hábil siguiente. Los precios argentinos se cotizan "sucios" (con corrido).

Curva ajustada por mínimos cuadrados: y = a + b·ln(x) + c·ln(x)² con 5 puntos o más (capta la
"joroba" típica de la curva soberana), o y = a + b·ln(x) con 3 o 4 puntos. Desvío = observado − ajustado, en puntos básicos: positivo = rinde más que la
curva (relativamente barato), negativo = rinde menos (relativamente caro).

Exclusiones (se informan, no se ocultan en silencio):
- menos de MIN_DAYS días al vencimiento (la TIR se dispara y no es comparable);
- TIR fuera de rango razonable;
- sin TIR ni duration.
"""

import math
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from typing import Dict, List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.db.models import Bond, ReferenceBond
from backend.app.services.market_calendar import ART

MIN_DAYS = 20
MIN_FIT_POINTS = 3
YTM_RANGE = (-30.0, 80.0)


@dataclass
class CurvePoint:
    ticker: str
    species: str
    x: float
    y: float
    ytm: Optional[float]
    md: Optional[float]
    tem: Optional[float]
    days: Optional[int]
    maturity: Optional[str]
    price: Optional[float]
    parity: Optional[float]
    source: str
    residual_bps: Optional[float] = None
    fitted: Optional[float] = None
    spread_ust_bps: Optional[float] = None


@dataclass
class CurveSeries:
    name: str
    color: str
    symbol: str = "circle"
    points: List[CurvePoint] = field(default_factory=list)
    fit: List[Tuple[float, float]] = field(default_factory=list)
    line: bool = False            # unir los puntos (curvas de referencia: UST, países)


@dataclass
class CurveGroup:
    id: str
    title: str
    description: str
    x_label: str
    y_label: str
    series: List[CurveSeries] = field(default_factory=list)
    excluded: List[Dict[str, str]] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return asdict(self)


GROUPS = [
    ("SOBERANOS_USD", "Soberanos en dólares",
     "Bonares (ley local) vs Globales (ley NY) y BOPREAL. TIR en dólares MEP (especie D).",
     "Duration modificada (años)", "TIR (%)"),
    ("TASA_FIJA", "Tasa fija en pesos",
     "LECAP y BONCAP: TEM según días al vencimiento.", "Días al vencimiento", "TEM (%)"),
    ("CER", "Ajustables por CER",
     "TIR real (por encima de la inflación).", "Duration modificada (años)", "TIR real (%)"),
    ("PROVINCIALES_USD", "Provinciales en dólares",
     "Bonos provinciales y de CABA en dólares.", "Duration modificada (años)", "TIR (%)"),
    ("DOLAR_LINKED", "Dollar linked",
     "Ajustan por el dólar oficial (A3500): TIR por encima de la devaluación.", "Días al vencimiento", "TIR (%)"),
    ("TAMAR_DUALES", "TAMAR y duales",
     "Tasa variable (TAMAR) y duales TAMAR / tasa fija.", "Días al vencimiento", "TIR (%)"),
    ("REGION", "Argentina vs región",
     "Globales argentinos contra soberanos de Latinoamérica y Treasuries de EE.UU. "
     "El spread contra la curva de Treasuries es el riesgo país por tramo.",
     "Duration modificada (años)", "TIR (%)"),
]

REGION_COUNTRIES = {"BR": ("Brasil", "#22c55e"), "MX": ("México", "#ef4444"), "CO": ("Colombia", "#eab308"),
                    "CL": ("Chile", "#3b82f6"), "PE": ("Perú", "#a855f7"), "UY": ("Uruguay", "#14b8a6"),
                    "PY": ("Paraguay", "#f97316"), "PA": ("Panamá", "#ec4899")}


# --------------------------------------------------------------------------- ajuste
QUADRATIC_MIN_POINTS = 5


def log_fit(points: List[CurvePoint]) -> Optional[List[float]]:
    """Coeficientes [a, b(, c)] de y = a + b·u (+ c·u²) con u = ln(x)."""
    pts = [(math.log(p.x), p.y) for p in points if p.x > 0]
    if len(pts) < MIN_FIT_POINTS:
        return None
    degree = 2 if len(pts) >= QUADRATIC_MIN_POINTS else 1
    us = [u for u, _ in pts]
    if max(us) - min(us) < 1e-6:
        return None
    try:
        import numpy as np
        coef = np.polyfit(us, [y for _, y in pts], degree)   # mayor grado primero
    except Exception:
        return None
    return [float(c) for c in coef[::-1]]


def fit_value(coef: List[float], x: float) -> float:
    u = math.log(x)
    return sum(c * u ** i for i, c in enumerate(coef))


def apply_fit(series: CurveSeries, samples: int = 40) -> None:
    coef = log_fit(series.points)
    if coef is None:
        return
    for p in series.points:
        p.fitted = round(fit_value(coef, p.x), 4)
        p.residual_bps = round((p.y - p.fitted) * 100.0, 1)
    xs = sorted(p.x for p in series.points)
    lo, hi = xs[0], xs[-1]
    series.fit = [(round(x, 4), round(fit_value(coef, x), 4))
                  for x in (lo * (hi / lo) ** (i / (samples - 1)) for i in range(samples))]


def own_yield(flows: List[Tuple[date, float]], price: float,
              settlement: date) -> Tuple[Optional[float], Optional[float]]:
    """TIR (%) y duration modificada con el motor propio, a partir de flujos y precio sucio."""
    from backend.app.quant.cashflows import CashFlowItem
    from backend.app.quant.fixed_income import calculate_duration_and_md, calculate_ytm
    items = [CashFlowItem(d, (d - settlement).days, 0.0, 0.0, 0.0, amt, 0.0)
             for d, amt in flows if d > settlement and amt]
    if not items or not price or price <= 0:
        return None, None
    ytm = calculate_ytm(price, items)
    if ytm is None:
        return None, None
    _, md = calculate_duration_and_md(price, ytm, items)
    return ytm * 100.0, md


def interp(curve: List[Tuple[float, float]], x: float) -> Optional[float]:
    """Interpolación lineal (con extrapolación plana en los extremos)."""
    if not curve:
        return None
    curve = sorted(curve)
    if x <= curve[0][0]:
        return curve[0][1]
    if x >= curve[-1][0]:
        return curve[-1][1]
    for (x0, y0), (x1, y1) in zip(curve, curve[1:]):
        if x0 <= x <= x1:
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0) if x1 > x0 else y0
    return None


# --------------------------------------------------------------------------- armado
def _maturity(ref: ReferenceBond, bonds: Dict[str, Bond]) -> Optional[date]:
    if ref.flows:
        try:
            return date.fromisoformat(str(ref.flows[-1][0]))
        except (TypeError, ValueError, IndexError):
            pass
    for t in [ref.ticker_base, *(ref.species or [])]:
        b = bonds.get(t)
        if b is not None and b.maturity_date:
            return b.maturity_date
    return None


def _group_of(ref: ReferenceBond) -> Optional[str]:
    tipo = (ref.tipo or "").upper()
    ccy = (ref.currency or "").upper()
    if tipo == "SOBERANO":
        return "SOBERANOS_USD"
    if tipo in ("LECAP", "BONCAP", "FIJA"):
        return "TASA_FIJA"
    if tipo == "CER":
        return "CER" if ref.yield_is_real else None
    if tipo == "PROVINCIAL" and ccy == "USD":
        return "PROVINCIALES_USD"
    if tipo == "DL":
        return "DOLAR_LINKED"
    if tipo in ("TAMAR", "DUAL"):
        return "TAMAR_DUALES"
    if tipo in ("INTERNATIONAL", "TREASURY"):
        return "REGION"
    return None


def _preferred_species(ref: ReferenceBond) -> List[str]:
    species = list(ref.species or [])
    usd = (ref.currency or "").upper() == "USD"
    d = [s for s in species if s.endswith("D") and s != ref.ticker_base]
    rest = [s for s in species if s not in d]
    ordered = (d + [ref.ticker_base] + rest) if usd else ([ref.ticker_base] + rest + d)
    seen, out = set(), []
    for s in ordered:
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out


def build_curves(db: Session, quotes: Dict[str, object], today: Optional[date] = None,
                 book_prices: Optional[Dict[str, float]] = None) -> List[CurveGroup]:
    """
    `quotes`: ticker -> BondQuoteView (último snapshot de Bonistas, 24hs).
    `book_prices`: especie -> precio por 100 VN (BYMA, 24hs) para calcular la TIR propia.
    """
    from backend.app.services.market_calendar import next_business_day
    from backend.app.services.reference_data_service import ReferenceDataService
    today = today or datetime.now(ART).date()
    settlement = next_business_day(today)
    book_prices = book_prices or {}
    bonds = {b.ticker: b for b in db.execute(select(Bond)).scalars()}
    refs = list(db.execute(select(ReferenceBond)).scalars())

    groups: Dict[str, CurveGroup] = {g[0]: CurveGroup(*g) for g in GROUPS}
    buckets: Dict[Tuple[str, str], List[CurvePoint]] = {}

    for ref in refs:
        gid = _group_of(ref)
        if gid is None:
            continue
        group = groups[gid]
        maturity = _maturity(ref, bonds)
        days = (maturity - today).days if maturity else None

        q, species = None, ref.ticker_base
        for s in _preferred_species(ref):
            cand = quotes.get(s)
            if cand is not None and cand.ytm_percentage is not None:
                q, species = cand, s
                break
        if q is not None:
            ytm, md, tem, source = q.ytm_percentage, q.modified_duration, q.tem_percentage, "BONISTAS"
            price = q.price_mep if species.endswith("D") and q.price_mep else (q.price_ars or q.price_mep or q.last_price)
            parity = q.parity_percentage
        elif ref.ref_ytm_pct is not None:
            ytm, md, tem, source = ref.ref_ytm_pct, ref.ref_duration, None, "COMPARARBONOS"
            price, parity = None, None
        else:
            ytm = md = tem = price = parity = None
            source = "PROPIO"
            for s in _preferred_species(ref):
                if book_prices.get(s):
                    price, species = book_prices[s], s
                    break
            if price and ref.flows and not ref.flows_cer_adjusted:
                ytm, md = own_yield(ReferenceDataService.flows_of(ref), price, settlement)
        if tem is None and ytm is not None and ytm > -100:
            tem = ((1 + ytm / 100.0) ** (1 / 12.0) - 1) * 100.0

        label = ref.ticker_base
        if ytm is None:
            group.excluded.append({"ticker": label, "reason": "sin TIR publicada ni flujos para calcularla"})
            continue
        if days is not None and days < MIN_DAYS:
            group.excluded.append({"ticker": label, "reason": f"vence en {days} días"})
            continue
        if not YTM_RANGE[0] <= ytm <= YTM_RANGE[1]:
            group.excluded.append({"ticker": label, "reason": f"TIR {ytm:.1f}% fuera de rango"})
            continue

        uses_days = group.x_label.startswith("Días")
        x = float(days) if uses_days else md
        y = tem if gid == "TASA_FIJA" else ytm
        if x is None or x <= 0 or y is None:
            group.excluded.append({"ticker": label, "reason": "sin duration / vencimiento"})
            continue

        point = CurvePoint(
            ticker=label, species=species, x=round(x, 4), y=round(y, 4), ytm=round(ytm, 3),
            md=round(md, 3) if md is not None else None, tem=round(tem, 3) if tem is not None else None,
            days=days, maturity=maturity.isoformat() if maturity else None,
            price=round(price, 4) if price else None,
            parity=round(parity, 2) if parity else None, source=source,
        )

        if gid == "SOBERANOS_USD":
            key = "BOPREAL" if label.startswith("BP") else ("GLOBALES" if label.startswith("GD") else "BONARES")
        elif gid == "REGION":
            if (ref.tipo or "").upper() == "TREASURY":
                key = "UST"
            else:
                key = label.split("_")[0]
        elif gid == "TAMAR_DUALES":
            key = (ref.tipo or "").upper()
        else:
            key = gid
        buckets.setdefault((gid, key), []).append(point)

    # Series y estilos
    style = {
        ("SOBERANOS_USD", "BONARES"): ("Bonares (ley local)", "#10b981", "circle", True),
        ("SOBERANOS_USD", "GLOBALES"): ("Globales (ley NY)", "#06b6d4", "diamond", True),
        ("SOBERANOS_USD", "BOPREAL"): ("BOPREAL (BCRA)", "#f59e0b", "square", False),
        ("TASA_FIJA", "TASA_FIJA"): ("LECAP / BONCAP", "#10b981", "circle", True),
        ("CER", "CER"): ("Bonos CER", "#a78bfa", "circle", True),
        ("PROVINCIALES_USD", "PROVINCIALES_USD"): ("Provinciales USD", "#f472b6", "circle", True),
        ("DOLAR_LINKED", "DOLAR_LINKED"): ("Dollar linked", "#38bdf8", "circle", True),
        ("TAMAR_DUALES", "TAMAR"): ("TAMAR", "#f59e0b", "circle", False),
        ("TAMAR_DUALES", "DUAL"): ("Duales", "#a78bfa", "diamond", False),
    }
    for (gid, key), pts in sorted(buckets.items()):
        pts.sort(key=lambda p: p.x)
        if gid == "REGION":
            if key == "UST":
                s = CurveSeries("Treasuries EE.UU.", "#e2e8f0", "x", pts, line=True)
            else:
                name, color = REGION_COUNTRIES.get(key, (key, "#64748b"))
                s = CurveSeries(name, color, "circle", pts, line=True)
        else:
            name, color, symbol, fit = style.get((gid, key), (key, "#94a3b8", "circle", False))
            s = CurveSeries(name, color, symbol, pts)
            if fit:
                apply_fit(s)
        groups[gid].series.append(s)

    # Región: Globales argentinos + spread contra Treasuries
    region = groups["REGION"]
    ust = next((s for s in region.series if s.name.startswith("Treasuries")), None)
    globales = next((s for s in groups["SOBERANOS_USD"].series if s.name.startswith("Globales")), None)
    if globales is not None:
        arg = CurveSeries("Argentina (Globales)", "#06b6d4", "diamond",
                          [CurvePoint(**asdict(p)) for p in globales.points], line=True)
        ust_curve = [(p.x, p.y) for p in ust.points] if ust else []
        for p in arg.points:
            p.residual_bps = p.fitted = None
            base = interp(ust_curve, p.x)
            if base is not None:
                p.spread_ust_bps = round((p.y - base) * 100.0)
        region.series.insert(0, arg)
        if ust_curve:
            region.notes.append("Spread vs UST = TIR del Global − TIR de la curva de Treasuries a la misma duration.")
    for s in region.series:
        if s.name.startswith("Argentina"):
            continue
        for p in s.points:
            if ust and s is not ust:
                base = interp([(u.x, u.y) for u in ust.points], p.x)
                p.spread_ust_bps = round((p.y - base) * 100.0) if base is not None else None

    for g in groups.values():
        if any(s.fit for s in g.series):
            g.notes.append("Desvío vs curva: positivo = rinde más que sus vecinos (relativamente barato); "
                           "negativo = rinde menos (relativamente caro).")
        if g.id == "TASA_FIJA":
            g.notes.append("TEM = tasa efectiva mensual (convención habitual para LECAP/BONCAP).")
    return [groups[g[0]] for g in GROUPS if groups[g[0]].series]
