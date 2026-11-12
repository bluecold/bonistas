"""
Ficha de un bono: contexto, métricas al precio actual, sensibilidad a la TIR e historia
(precio, TIR, paridad y ratio contra su par).

La historia se arma revaluando cada cierre diario (Rava) con los flujos que el bono tenía por
delante ESE día. Eso solo se puede hacer cuando se conocen todos los pagos, pasados y futuros:

- Bonares / Globales 2020: cronograma propio verificado (TIR, valor técnico y paridad).
- LECAP / BONCAP y CER cupón cero: un único pago al vencimiento.
- Bonos con historia de pagos guardada (`bond_flow_log`, desde Bull Market).
- CER: los flujos de la referencia vienen ajustados al CER de hoy; para una fecha pasada se
  llevan al CER de esa fecha (serie del BCRA, con el rezago de 10 días hábiles).

Para el resto solo se conocen los pagos futuros: se muestra la historia de precios, sin TIR.
"""

from bisect import bisect_right
from dataclasses import dataclass, field
from datetime import date, timedelta
from statistics import mean, stdev
from typing import Any, Callable, Dict, List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.arbitrage.ratios import (
    BAND_DAYS, BAND_K, adjust_for_flows, logged_flows, pair_specs,
)
from backend.app.db.models import Bond, DailyClose, ReferenceBond
from backend.app.quant.cashflows import (
    CashFlowItem, base_ticker, generate_cashflows, get_hard_dollar_schedule, has_verified_schedule,
)
from backend.app.quant.fixed_income import (
    calculate_accrued_interest, calculate_duration_and_md, calculate_residual_capital,
    calculate_technical_value, calculate_ytm,
)
from backend.app.services.market_calendar import ex_date, next_business_day, previous_business_day
from backend.app.services.reference_data_service import ReferenceDataService

# Desde el 27/05/2024 el plazo normal es 24hs (T+1); antes era 48hs (T+2)
T1_SINCE = date(2024, 5, 27)
CER_LAG_BUSINESS_DAYS = 10
SENSITIVITY_SHIFTS = (-3, -2, -1, 1, 2, 3, 5, 10)
SINGLE_FLOW_TYPES = {"LECAP", "BONCAP"}
STATS_DAYS = 365


def settlement_for(day: date) -> date:
    """Liquidación del plazo normal para una rueda pasada."""
    s = next_business_day(day)
    return s if day >= T1_SINCE else next_business_day(s)


class CerSeries:
    def __init__(self, values: Dict[date, float]):
        self.days = sorted(values)
        self.values = [values[d] for d in self.days]

    def __bool__(self) -> bool:
        return bool(self.days)

    def at(self, d: date) -> Optional[float]:
        i = bisect_right(self.days, d)
        return self.values[i - 1] if i else None

    def for_settlement(self, s: date) -> Optional[float]:
        """CER que ajusta un pago o una liquidación: el de 10 días hábiles antes."""
        d = s
        for _ in range(CER_LAG_BUSINESS_DAYS):
            d = previous_business_day(d)
        return self.at(d)


@dataclass
class BondModel:
    ticker: str
    base: str
    kind: str                                  # PROPIO | REFERENCIA | ON | SIN_FLUJOS
    flow_currency: str                         # USD | ARS
    price_symbol: str                          # especie cuyo precio se compara contra los flujos
    bond: Optional[Bond] = None
    ref: Optional[ReferenceBond] = None
    # Todos los pagos conocidos (fecha, monto por 100 VN). `nominal_past`: pagos ya hechos de un
    # bono CER, en pesos de la fecha de pago.
    flows: List[Tuple[date, float]] = field(default_factory=list)
    nominal_past: List[Tuple[date, float]] = field(default_factory=list)
    full_history: bool = False                 # se conocen también los pagos pasados
    cer: bool = False                          # flujos ajustados al CER de `cer_anchor`
    cer_anchor: Optional[date] = None
    real_yield: bool = False
    flows_source: Optional[str] = None
    notes: List[str] = field(default_factory=list)

    def cer_factor(self, s: date, cer: Optional[CerSeries]) -> Optional[float]:
        if not self.cer:
            return 1.0
        if not cer or self.cer_anchor is None:
            return None
        a, b = cer.for_settlement(s), cer.for_settlement(self.cer_anchor)
        return a / b if a and b else None

    def flows_at(self, s: date, cer: Optional[CerSeries] = None) -> Optional[List[Tuple[date, float]]]:
        """Pagos que cobra quien liquida la compra en `s` (corte: día hábil previo al pago)."""
        k = self.cer_factor(s, cer)
        if k is None:
            return None
        out = [(d, a * k) for d, a in self.flows if s < ex_date(d)]
        if self.nominal_past:
            now_cer = cer.for_settlement(s)
            for d, a in self.nominal_past:
                paid_cer = cer.for_settlement(d)
                if s < ex_date(d) and now_cer and paid_cer:
                    out.append((d, a * now_cer / paid_cer))
        return sorted(out)

    def technical_value_at(self, s: date, cer: Optional[CerSeries] = None) -> Optional[float]:
        if self.kind == "PROPIO":
            # Entre el corte y el pago el precio ya es ex-cupón: se valúa como después del pago
            ref_day = s
            for ev in get_hard_dollar_schedule(self.base):
                if ex_date(ev["date"]) <= s < ev["date"]:
                    ref_day = ev["date"]
                    break
            residual = calculate_residual_capital(self.base, ref_day)
            vt = calculate_technical_value(residual, calculate_accrued_interest(self.base, ref_day))
            return vt if vt > 0 else None
        if self.cer and self.full_history and len(self.flows) == 1 and not self.nominal_past:
            k = self.cer_factor(s, cer)
            return self.flows[0][1] * k if k else None
        return None


def find_bond(db: Session, ticker: str) -> Optional[Bond]:
    t = ticker.strip().upper()
    bond = db.get(Bond, t)
    if bond is None and base_ticker(t) != t:
        bond = db.get(Bond, base_ticker(t))
    return bond


def _usd_symbol(requested: str, candidates: List[str]) -> str:
    """Especie en dólar MEP (termina en D) entre las candidatas; si no, la pedida."""
    if requested.endswith("D") and requested in candidates:
        return requested
    for c in candidates:
        if c.endswith("D"):
            return c
    return requested


def build_model(db: Session, ticker: str, today: date, on_schedule: Any = None) -> BondModel:
    t = ticker.strip().upper()
    bond = find_bond(db, t)

    if bond is not None and has_verified_schedule(bond.ticker):
        base = base_ticker(bond.ticker)
        issue = bond.start_date or date(2020, 9, 4)
        flows = [(cf.date, cf.total_cashflow) for cf in generate_cashflows(base, issue, bond.maturity_date)]
        return BondModel(ticker=t, base=base, kind="PROPIO", flow_currency="USD", price_symbol=base + "D",
                         bond=bond, flows=flows, full_history=True, flows_source="PROPIO")

    if bond is not None and bond.bond_type == "ON":
        stem = t[:-1] if t[-1:] in ("O", "D", "C") else t
        if on_schedule is not None:
            usd = on_schedule.currency == "USD"
            return BondModel(
                ticker=t, base=bond.ticker, kind="ON", flow_currency="USD" if usd else "ARS",
                price_symbol=(stem + "D") if usd else bond.ticker, bond=bond,
                flows=[(r.date, r.total) for r in on_schedule.rows if r.date > today],
                flows_source="BULLMARKET",
                notes=["Solo se conocen los pagos futuros de esta ON: hay historia de precios, sin TIR histórica."])
        usd = (bond.currency or "").upper() == "USD"
        return BondModel(ticker=t, base=bond.ticker, kind="SIN_FLUJOS", flow_currency="USD" if usd else "ARS",
                         price_symbol=(stem + "D") if usd else bond.ticker, bond=bond,
                         notes=["Los flujos de las ON salen de Bull Market: sin la sesión activa no hay TIR ni sensibilidad."])

    ref = ReferenceDataService.get_reference(db, t)
    if ref is None or not ref.flows:
        usd = ((ref.currency if ref is not None else None) or (bond.currency if bond is not None else "") or "").upper() == "USD"
        base = ref.ticker_base if ref is not None else (bond.ticker if bond is not None else t)
        species = list((ref.species if ref is not None else None) or [])
        symbol = _usd_symbol(t, species or [base + "D"]) if usd else base
        return BondModel(ticker=t, base=base, kind="SIN_FLUJOS", flow_currency="USD" if usd else "ARS",
                         price_symbol=symbol, bond=bond, ref=ref,
                         notes=["Este título no publica flujos proyectables: hay historia de precios, sin TIR."])

    usd = (ref.currency or "").upper() == "USD"
    base = ref.ticker_base
    bond = bond or db.get(Bond, base)
    symbol = _usd_symbol(t, list(ref.species or []) or [base + "D"]) if usd else base
    future = ReferenceDataService.flows_of(ref)
    model = BondModel(
        ticker=t, base=base, kind="REFERENCIA", flow_currency="USD" if usd else "ARS", price_symbol=symbol,
        bond=bond, ref=ref, flows=future, cer=bool(ref.flows_cer_adjusted),
        cer_anchor=ref.settlement_date or today, real_yield=bool(ref.yield_is_real),
        flows_source=ref.flows_source or "COMPARARBONOS")

    logged = logged_flows(db, base, "USD" if usd else "ARS")
    zero_coupon = len(future) == 1 and (
        (ref.tipo or "").upper() in SINGLE_FLOW_TYPES
        or (bond is not None and bond.coupon_rate is not None and float(bond.coupon_rate) == 0.0))
    if zero_coupon:
        model.full_history = True
    elif logged:
        first_future = min(d for d, _ in future)
        past = [(d, a) for d, a in logged if d < first_future - timedelta(days=5)]
        if model.cer:
            model.nominal_past = past
        else:
            model.flows = sorted(past + future)
        model.full_history = True
    else:
        model.notes.append("Solo se conocen los pagos futuros de este bono: hay historia de precios, sin TIR histórica.")
    return model


# ------------------------------------------------------------------ valuación

def _items(flows: List[Tuple[date, float]], s: date) -> List[CashFlowItem]:
    return [CashFlowItem(date=d, days_from_settlement=(d - s).days, interest_rate=0.0, coupon_amount=0.0,
                         amortization_amount=0.0, total_cashflow=a, residual_capital=0.0)
            for d, a in flows if d > s]


def present_value(cfs: List[CashFlowItem], rate: float) -> float:
    return sum(cf.total_cashflow / ((1.0 + rate) ** (cf.days_from_settlement / 365.0)) for cf in cfs)


def sensitivity(price: float, ytm: float, cfs: List[CashFlowItem],
                shifts: Tuple[int, ...] = SENSITIVITY_SHIFTS) -> List[Dict[str, float]]:
    """Precio que resulta si la TIR se mueve `shift` puntos porcentuales, con los mismos flujos."""
    out = []
    for sh in shifts:
        y = ytm + sh / 100.0
        if y <= -0.99 or price <= 0:
            continue
        p = present_value(cfs, y)
        out.append({"shift_pp": sh, "ytm_pct": round(y * 100.0, 2), "price": round(p, 4),
                    "change_pct": round((p / price - 1.0) * 100.0, 2)})
    return out


def valuation(model: BondModel, price: Optional[float], s: date,
              cer: Optional[CerSeries] = None) -> Dict[str, Any]:
    """Métricas propias al precio dado (None en lo que no se puede calcular)."""
    out: Dict[str, Any] = {"ytm_pct": None, "modified_duration": None, "macaulay_duration": None,
                           "technical_value": None, "parity_pct": None, "residual_capital": None,
                           "accrued_interest": None, "sensitivity": []}
    if model.kind == "PROPIO":
        out["residual_capital"] = calculate_residual_capital(model.base, s)
        out["accrued_interest"] = calculate_accrued_interest(model.base, s)
    vt = model.technical_value_at(s, cer)
    if vt:
        out["technical_value"] = round(vt, 4)
    if not price or price <= 0:
        return out
    if vt:
        out["parity_pct"] = round(price / vt * 100.0, 3)
    flows = model.flows_at(s, cer) if model.flows or model.nominal_past else None
    if not flows:
        return out
    cfs = _items(flows, s)
    ytm = calculate_ytm(price, cfs)
    if ytm is None:
        return out
    d_mac, md = calculate_duration_and_md(price, ytm, cfs)
    out.update(ytm_pct=round(ytm * 100.0, 4), modified_duration=md, macaulay_duration=d_mac,
               sensitivity=sensitivity(price, ytm, cfs))
    return out


# ------------------------------------------------------------------ historia

def _stats(days: List[date], values: List[Optional[float]], today: date,
           current: Optional[float] = None) -> Optional[Dict[str, Any]]:
    """Media, mínimo y máximo del último año, y en qué percentil de ese año está el valor actual."""
    since = today - timedelta(days=STATS_DAYS)
    window = [v for d, v in zip(days, values) if v is not None and d >= since]
    if len(window) < 20:
        return None
    cur = current if current is not None else window[-1]
    return {"days": len(window), "mean": round(mean(window), 3), "min": round(min(window), 3),
            "max": round(max(window), 3), "current": round(cur, 3),
            "percentile": round(100.0 * sum(1 for v in window if v <= cur) / len(window), 1)}


def compute_history(model: BondModel, closes: List[Tuple[date, float]], today: date,
                    cer: Optional[CerSeries] = None,
                    settle: Callable[[date], date] = settlement_for) -> Dict[str, Any]:
    days = [d for d, _ in closes]
    prices = [c for _, c in closes]
    ytm: List[Optional[float]] = []
    parity: List[Optional[float]] = []
    if model.full_history:
        for day, close in closes:
            s = settle(day)
            flows = model.flows_at(s, cer)
            y = calculate_ytm(close, _items(flows, s)) if flows else None
            ytm.append(round(y * 100.0, 3) if y is not None else None)
            vt = model.technical_value_at(s, cer)
            parity.append(round(close / vt * 100.0, 3) if vt else None)
    has_ytm = any(v is not None for v in ytm)
    has_parity = any(v is not None for v in parity)
    return {
        "symbol": model.price_symbol,
        "days": [d.isoformat() for d in days],
        "price": prices,
        "ytm": ytm if has_ytm else None,
        "parity": parity if has_parity else None,
        "stats": {
            "price": _stats(days, prices, today),
            "ytm": _stats(days, ytm, today) if has_ytm else None,
            "parity": _stats(days, parity, today) if has_parity else None,
        },
    }


def payment_marks(model: BondModel, since: Optional[date], today: date) -> List[Dict[str, Any]]:
    """Pagos dentro de la historia (y el próximo), con su fecha de corte, para marcar en los gráficos."""
    out = []
    upcoming_done = False
    for d, a in sorted(model.flows + model.nominal_past):
        if since is not None and d < since:
            continue
        if d > today:
            if upcoming_done:
                break
            upcoming_done = True
        out.append({"date": d.isoformat(), "ex_date": ex_date(d).isoformat(), "amount": round(a, 4),
                    "upcoming": d > today})
    return out


def pair_series(db: Session, base: str, today: date) -> List[Dict[str, Any]]:
    """Ratio B/A de cada par del que participa el bono, con su banda móvil (igual que el motor)."""
    out = []
    for spec in pair_specs():
        if base not in (spec.a, spec.b):
            continue
        rows = db.execute(
            select(DailyClose.symbol, DailyClose.day, DailyClose.close)
            .where(DailyClose.symbol.in_((spec.symbol_a, spec.symbol_b)), DailyClose.close > 0)).all()
        ca = {d: c for sym, d, c in rows if sym == spec.symbol_a}
        cb = {d: c for sym, d, c in rows if sym == spec.symbol_b}
        if spec.adjust_flows:
            ccy = "USD" if spec.suffix else "ARS"
            fa, fb = logged_flows(db, spec.a, ccy), logged_flows(db, spec.b, ccy)
            if not fa or not fb:
                continue
            ca, cb = adjust_for_flows(ca, cb, fa, today), adjust_for_flows(cb, ca, fb, today)
        days = sorted(d for d in ca if d in cb)
        if len(days) < BAND_DAYS + 1:
            continue
        ratio = [cb[d] / ca[d] for d in days]
        mid: List[Optional[float]] = []
        lower: List[Optional[float]] = []
        upper: List[Optional[float]] = []
        for i in range(len(ratio)):
            if i < BAND_DAYS:
                mid.append(None); lower.append(None); upper.append(None)
                continue
            window = ratio[i - BAND_DAYS:i]
            m, sd = mean(window), stdev(window)
            mid.append(round(m, 5)); lower.append(round(m - BAND_K * sd, 5)); upper.append(round(m + BAND_K * sd, 5))
        out.append({"a": spec.a, "b": spec.b, "kind": spec.kind, "symbol_a": spec.symbol_a,
                    "symbol_b": spec.symbol_b, "flow_adjusted": spec.adjust_flows,
                    "band_days": BAND_DAYS, "band_k": BAND_K,
                    "days": [d.isoformat() for d in days], "ratio": [round(r, 5) for r in ratio],
                    "mean": mid, "lower": lower, "upper": upper})
    return out


# ------------------------------------------------------------------ contexto

def context(model: BondModel, today: date) -> Dict[str, Any]:
    bond, ref = model.bond, model.ref
    coupon = None
    if model.kind == "PROPIO":
        nxt = next((ev for ev in get_hard_dollar_schedule(model.base) if ev["date"] > today), None)
        coupon = round(nxt["coupon_tna"] * 100.0, 4) if nxt else None
    upcoming = next(((d, a) for d, a in sorted(model.flows) if d > today), None)
    next_payment = None
    if upcoming:
        cut = ex_date(upcoming[0])
        next_payment = {"date": upcoming[0].isoformat(), "amount": round(upcoming[1], 4),
                        "ex_date": cut.isoformat(), "days": (upcoming[0] - today).days,
                        # Última rueda en la que comprar en 24hs todavía cobra el pago
                        "last_day_24hs": previous_business_day(previous_business_day(cut)).isoformat()
                        if cut > today else None}
    return {
        "ticker": model.ticker, "base": model.base, "price_symbol": model.price_symbol,
        "name": bond.name if bond is not None else model.base,
        "description": (bond.short_description or bond.description) if bond is not None else None,
        "bond_type": bond.bond_type if bond is not None else (ref.tipo if ref is not None else None),
        "law": bond.law if bond is not None else None,
        "currency": model.flow_currency,
        "issue_date": bond.start_date.isoformat() if bond is not None and bond.start_date else None,
        "maturity_date": bond.maturity_date.isoformat() if bond is not None and bond.maturity_date else (
            max(d for d, _ in model.flows).isoformat() if model.flows else None),
        "amortization_type": bond.amortization_type if bond is not None else None,
        "coupon_pct": coupon,
        "species": list(ref.species or []) if ref is not None else [],
        "flows_kind": model.kind, "flows_source": model.flows_source,
        "cer_adjusted": model.cer, "real_yield": model.real_yield,
        "remaining_payments": sum(1 for d, _ in model.flows if d > today),
        "next_payment": next_payment,
        "notes": list(model.notes),
    }
