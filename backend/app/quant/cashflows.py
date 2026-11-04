"""
Generador de flujos de fondos (Cash Flows) para títulos públicos de la República Argentina.

Los Bonares (AL/AE) y Globales (GD) de la reestructuración 2020 tienen cronogramas
explícitos (amortizaciones escalonadas y cupones step-up). Las tasas y amortizaciones
futuras fueron verificadas contra los flujos publicados por CompararBonos (nov-2026):
el residual y la tasa implícita de cada pago coinciden exactamente.

Convenciones:
- Pagos el 9 de enero y el 9 de julio.
- El cupón de cada fecha se calcula sobre el residual vigente ANTES de la amortización
  de esa misma fecha: cupón = residual * tasa / 2.
- `coupon_tna` de cada evento es la tasa del período que TERMINA en esa fecha de pago
  (es decir, la que se devenga hasta ese pago).
"""

from dataclasses import dataclass
from datetime import date
from typing import List, Dict, Optional, Tuple


@dataclass
class CashFlowItem:
    date: date
    days_from_settlement: int
    interest_rate: float
    coupon_amount: float
    amortization_amount: float
    total_cashflow: float
    residual_capital: float


# ---------------------------------------------------------------------------
# Especificación de los bonos de la reestructuración 2020
# ---------------------------------------------------------------------------
# coupon_steps: lista de (primera fecha de pago a la que aplica la tasa, tasa anual).
#   La tasa vale para ese pago y todos los siguientes hasta el próximo escalón.
# amort: (primera fecha de amortización, cantidad de cuotas semestrales, primera cuota
#   especial opcional en % del VN original). Las cuotas regulares se reparten en partes
#   iguales y la última absorbe el redondeo para que el total sea exactamente 100.

_FIRST_COUPON = date(2021, 7, 9)

_SPECS: Dict[str, Dict] = {
    "30": {
        "maturity": date(2030, 7, 9),
        "coupon_steps": [
            (date(2021, 7, 9), 0.00125),
            (date(2022, 1, 9), 0.0050),
            (date(2024, 1, 9), 0.0075),
            (date(2028, 1, 9), 0.0175),
        ],
        # 4% en jul-24 y luego 12 cuotas de 8% (ene-25 a jul-30)
        "amort_explicit": [(date(2024, 7, 9), 4.0)],
        "amort_regular": (date(2025, 1, 9), 12, 8.0),
    },
    "29": {
        "maturity": date(2029, 7, 9),
        "coupon_steps": [(date(2021, 7, 9), 0.0100)],
        "amort_regular": (date(2025, 1, 9), 10, 10.0),
    },
    "35": {
        "maturity": date(2035, 7, 9),
        "coupon_steps": [
            (date(2021, 7, 9), 0.00125),
            (date(2022, 1, 9), 0.01125),
            (date(2023, 1, 9), 0.0150),
            (date(2024, 1, 9), 0.03625),
            (date(2025, 1, 9), 0.04125),
            (date(2028, 1, 9), 0.0475),
            (date(2029, 1, 9), 0.0500),
        ],
        "amort_regular": (date(2031, 1, 9), 10, 10.0),
    },
    "38": {
        "maturity": date(2038, 1, 9),
        "coupon_steps": [
            (date(2021, 7, 9), 0.00125),
            (date(2022, 1, 9), 0.0200),
            (date(2023, 1, 9), 0.03875),
            (date(2024, 1, 9), 0.0425),
            (date(2025, 1, 9), 0.0500),
        ],
        "amort_regular": (date(2027, 7, 9), 22, 100.0 / 22),
    },
    "41": {
        "maturity": date(2041, 7, 9),
        "coupon_steps": [
            (date(2021, 7, 9), 0.00125),
            (date(2022, 1, 9), 0.0250),
            (date(2023, 1, 9), 0.0350),
            (date(2030, 1, 9), 0.04875),
        ],
        "amort_regular": (date(2028, 1, 9), 28, 100.0 / 28),
    },
    "46": {
        "maturity": date(2046, 7, 9),
        "coupon_steps": [
            (date(2021, 7, 9), 0.00125),
            (date(2022, 1, 9), 0.01125),
            (date(2023, 1, 9), 0.0150),
            (date(2024, 1, 9), 0.03625),
            (date(2025, 1, 9), 0.04125),
            (date(2028, 1, 9), 0.04375),
            (date(2029, 1, 9), 0.0500),
        ],
        "amort_regular": (date(2025, 1, 9), 44, 100.0 / 44),
    },
}

# Ticker base (sin sufijo de especie) -> clave de especificación.
# AL/GD comparten flujos: solo cambia la legislación.
HARD_DOLLAR_TICKERS: Dict[str, str] = {
    "AL29": "29", "GD29": "29",
    "AL30": "30", "GD30": "30",
    "AL35": "35", "GD35": "35",
    "AE38": "38", "GD38": "38",
    "AL41": "41", "GD41": "41",
    "GD46": "46",
}


def base_ticker(ticker: str) -> str:
    """
    Devuelve el ticker base de un bono hard dollar quitando el sufijo de especie
    final: D (dólar MEP) o C (dólar cable). Ej.: AL30D -> AL30, GD30C -> GD30.

    Solo se quita la ÚLTIMA letra y solo si el resultado es un bono conocido,
    para no romper tickers que contienen D o C en otra posición (GD30, DICP, ...).
    """
    t = (ticker or "").strip().upper()
    if t in HARD_DOLLAR_TICKERS:
        return t
    if len(t) >= 5 and t[-1] in ("D", "C") and t[:-1] in HARD_DOLLAR_TICKERS:
        return t[:-1]
    return t


def _semiannual_dates(start: date, count: int) -> List[date]:
    """Genera `count` fechas semestrales (9-ene / 9-jul) a partir de `start`."""
    dates = []
    y, m = start.year, start.month
    for _ in range(count):
        dates.append(date(y, m, start.day))
        if m == 1:
            m = 7
        else:
            m = 1
            y += 1
    return dates


def _coupon_rate_for(payment_date: date, steps: List[Tuple[date, float]]) -> float:
    rate = steps[0][1]
    for from_date, r in steps:
        if payment_date >= from_date:
            rate = r
    return rate


def get_hard_dollar_schedule(ticker: str) -> List[Dict]:
    """
    Retorna el cronograma completo de pagos (pasados y futuros) para Bonares y Globales,
    en base 100 de valor nominal original. Acepta tickers con sufijo de especie (AL30D, GD30C).
    Cada evento: {"date", "coupon_tna", "amort_pct"}.
    """
    key = HARD_DOLLAR_TICKERS.get(base_ticker(ticker))
    if not key:
        return []
    spec = _SPECS[key]

    amort_by_date: Dict[date, float] = {}
    for d, pct in spec.get("amort_explicit", []):
        amort_by_date[d] = amort_by_date.get(d, 0.0) + pct

    first, count, pct = spec["amort_regular"]
    regular_dates = _semiannual_dates(first, count)
    already = sum(amort_by_date.values())
    for i, d in enumerate(regular_dates):
        if i == count - 1:
            # La última cuota absorbe el redondeo: el total amortizado es exactamente 100
            amount = 100.0 - already - pct * (count - 1)
        else:
            amount = pct
        amort_by_date[d] = amort_by_date.get(d, 0.0) + amount

    maturity = spec["maturity"]
    n_payments = (maturity.year - _FIRST_COUPON.year) * 2 + (1 if maturity.month == 7 else 0)
    payment_dates = [d for d in _semiannual_dates(_FIRST_COUPON, n_payments + 1) if d <= maturity]

    return [
        {
            "date": d,
            "coupon_tna": _coupon_rate_for(d, spec["coupon_steps"]),
            "amort_pct": amort_by_date.get(d, 0.0),
        }
        for d in payment_dates
    ]


def has_verified_schedule(ticker: str) -> bool:
    """True si el bono tiene cronograma propio verificado (hoy: Bonares y Globales 2020)."""
    return bool(get_hard_dollar_schedule(ticker))


def generic_coupon_dates(settlement_date: date, maturity_date: date, frequency: int) -> Tuple[Optional[date], List[date]]:
    """
    Fechas de cupón regulares contadas hacia atrás desde el vencimiento.
    Devuelve (fecha del último cupón pasado o None, lista de fechas futuras ordenadas).
    """
    if frequency <= 0:
        frequency = 1
    months_step = 12 // frequency
    day = maturity_date.day

    def step_back(d: date) -> date:
        y, m = d.year, d.month - months_step
        while m <= 0:
            m += 12
            y -= 1
        # Respetar el día original del vencimiento (con tope de fin de mes)
        for dd in (day, 30, 29, 28):
            try:
                return date(y, m, dd)
            except ValueError:
                continue
        return date(y, m, 28)

    future: List[date] = []
    curr = maturity_date
    while curr > settlement_date:
        future.append(curr)
        curr = step_back(curr)
    future.sort()
    return curr, future


def generate_cashflows(
    ticker: str,
    settlement_date: date,
    maturity_date: date,
    coupon_rate: Optional[float] = None,
    frequency: int = 2,
    base_nominal: float = 100.0,
    is_bullet: bool = True
) -> List[CashFlowItem]:
    """
    Genera el vector futuro de flujos de fondos desde la fecha de liquidación hasta el vencimiento.

    Un flujo con fecha igual a la de liquidación NO se incluye: si liquido el mismo día del
    pago (o después), ese pago ya no me corresponde (precio ex-cupón).
    """
    specific_schedule = get_hard_dollar_schedule(ticker)
    cashflows: List[CashFlowItem] = []

    if specific_schedule:
        factor = base_nominal / 100.0
        current_residual = base_nominal
        for event in specific_schedule:
            if event["date"] <= settlement_date:
                current_residual = max(0.0, current_residual - event["amort_pct"] * factor)

        for event in specific_schedule:
            event_date = event["date"]
            if event_date <= settlement_date:
                continue
            c_rate = event["coupon_tna"]
            coupon_amount = current_residual * (c_rate / 2.0)
            amort_amount = min(event["amort_pct"] * factor, current_residual)
            current_residual = max(0.0, current_residual - amort_amount)
            cashflows.append(
                CashFlowItem(
                    date=event_date,
                    days_from_settlement=(event_date - settlement_date).days,
                    interest_rate=c_rate,
                    coupon_amount=coupon_amount,
                    amortization_amount=amort_amount,
                    total_cashflow=coupon_amount + amort_amount,
                    residual_capital=round(current_residual, 10),
                )
            )
        return cashflows

    # Bono genérico bullet con cupón fijo periódico.
    # ATENCIÓN: no modela LECAP/BONCAP (capitalizables), CER, duales ni dollar linked.
    coupon_tna = float(coupon_rate) if coupon_rate is not None else 0.0
    if frequency <= 0:
        frequency = 1
    _, coupon_dates = generic_coupon_dates(settlement_date, maturity_date, frequency)

    for c_date in coupon_dates:
        is_last = c_date == coupon_dates[-1]
        coupon_amt = base_nominal * (coupon_tna / frequency)
        amort_amt = base_nominal if is_last else 0.0
        cashflows.append(
            CashFlowItem(
                date=c_date,
                days_from_settlement=(c_date - settlement_date).days,
                interest_rate=coupon_tna,
                coupon_amount=coupon_amt,
                amortization_amount=amort_amt,
                total_cashflow=coupon_amt + amort_amt,
                residual_capital=0.0 if is_last else base_nominal,
            )
        )

    return cashflows
