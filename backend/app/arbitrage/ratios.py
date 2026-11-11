"""
Ratios entre bonos con puntas (misma especie y mismo plazo) y su banda histórica. Pares: AL/GD,
curva en dólares, CER casi sustitutos (en pesos) y bonos del Tesoro en dólares (ver pair_specs).

- Ratio medio = medio(B) / medio(A).
- Rotar A -> B (vender A a la compradora, comprar B a la vendedora): nominales de B que se
  obtienen por cada nominal de A, costos incluidos  =  compradora_A * (1-c) / (vendedora_B * (1+c)).
- Banda propia de cada par: media móvil de las últimas BAND_DAYS ruedas ± BAND_K desvíos (bandas
  de Bollinger sobre el ratio). La historia sale de los cierres diarios de Rava (tabla
  daily_closes); si no están, de la serie propia guardada en la base. Sin MIN_HISTORY_DAYS ruedas
  no hay banda ni z-score: no se usan valores fijos, porque el nivel de cada par cambia con el tiempo.
- Señal de banda: el ratio medio sale de la banda Y rotar ahora a las puntas, y volver cuando el
  ratio regrese a su media, deja al menos la ganancia neta mínima después de las 4 operaciones.
- Prueba histórica (último año de cierres): cuántas veces la banda dio señal en ese par y cuánto
  dejó. Si no fue rentable (el par vino cambiando de nivel), la señal queda como informativa.
"""

from collections import OrderedDict
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from statistics import mean, stdev
from typing import Dict, List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.arbitrage.market_view import MarketView, combined_source
from backend.app.db.models import BondFlowLog, DailyClose, PriceSnapshot
from backend.app.services.market_calendar import (
    ART, ex_date, is_business_day, next_business_day, previous_business_day,
)
from backend.app.services.trading_settings import TradingParams

LAW_PAIRS: List[Tuple[str, str]] = [
    ("AL29", "GD29"), ("AL30", "GD30"), ("AL35", "GD35"), ("AE38", "GD38"), ("AL41", "GD41"),
]
# Pares que el trader seguía en su monitor (temporal/MonitorMercado.ps1, "ratios agresivos")
CURVE_PAIRS: List[Tuple[str, str]] = [
    ("AE38", "GD35"), ("AE38", "GD41"), ("GD38", "GD41"), ("GD35", "GD38"),
]
# Bonos CER casi sustitutos, en pesos: cupón cero de vencimientos contiguos (el ratio de precios no
# tiene saltos por cupones), DICP/DIP0 (exactamente el mismo flujo) y TX31/DICP (amortizables de
# plazo parecido; se ajusta por los pagos de cada uno).
CER_PAIRS: List[Tuple[str, str]] = [
    ("TZXM7", "TZX27"), ("TZX27", "TZXD7"), ("TZXD7", "TZX28"), ("TZX28", "TZXS8"), ("TZXS8", "TZXM9"),
    ("TZXS7", "TZXO7"), ("DICP", "DIP0"), ("TX31", "DICP"),
]
# Bonos del Tesoro en dólares ley local, especie D. AO28/AO29 pagan el mismo día casi el mismo monto.
# AO29 (renta mensual) contra AN29 (semestral) se ajusta por los pagos: ver adjust_flows.
TREASURY_USD_PAIRS: List[Tuple[str, str]] = [("AO28", "AO29"), ("AO29", "AN29")]
FLOW_ADJUSTED_PAIRS = {("AO29", "AN29"), ("TX31", "DICP")}


@dataclass(frozen=True)
class PairSpec:
    a: str
    b: str
    kind: str                 # 'LEY' | 'CURVA' | 'CER' | 'TESORO_USD'
    suffix: str = "D"         # especie que se compara: 'D' (dólar MEP) o '' (pesos)
    adjust_flows: bool = False

    @property
    def symbol_a(self) -> str:
        return self.a + self.suffix

    @property
    def symbol_b(self) -> str:
        return self.b + self.suffix


def pair_specs() -> List[PairSpec]:
    out = [PairSpec(a, b, "LEY") for a, b in LAW_PAIRS]
    out += [PairSpec(a, b, "CURVA") for a, b in CURVE_PAIRS]
    out += [PairSpec(a, b, "CER", suffix="", adjust_flows=(a, b) in FLOW_ADJUSTED_PAIRS) for a, b in CER_PAIRS]
    out += [PairSpec(a, b, "TESORO_USD", adjust_flows=(a, b) in FLOW_ADJUSTED_PAIRS)
            for a, b in TREASURY_USD_PAIRS]
    return out

MIN_HISTORY_DAYS = 20
BAND_DAYS = 21            # ventana de la banda (ruedas)
BAND_K = 1.5              # desvíos de la banda
LONG_DAYS = 252           # media de un año: contexto, no dispara nada
BACKTEST_HOLD_DAYS = 30   # la prueba histórica cierra a las 30 ruedas si el ratio no volvió a la media
BACKTEST_MIN_SIGNALS = 5
BACKTEST_MIN_AVG_NET_PCT = 0.5
BACKTEST_MIN_WIN_RATE = 0.7


def flow_adjusted_bases() -> List[str]:
    """Bonos que necesitan su historia de pagos (tabla bond_flow_log, desde Bull Market)."""
    return sorted({t for spec in pair_specs() if spec.adjust_flows for t in (spec.a, spec.b)})


@dataclass
class PairRatio:
    a: str
    b: str
    kind: str                       # 'LEY' | 'CURVA'
    settlement: str
    mid_ratio: Optional[float]      # medio(B) / medio(A)
    rotate_a_to_b: Optional[float]  # nominales de B por nominal de A (costos incluidos)
    rotate_b_to_a: Optional[float]  # nominales de A por nominal de B (costos incluidos)
    z_score: Optional[float]        # desvíos contra la media de la banda
    hist_mean: Optional[float]      # media de la banda
    hist_std: Optional[float]       # desvío de la banda
    calibration: str                # 'BANDA_<n>r' | 'SIN_HISTORIA'
    price_a: Optional[Tuple[Optional[float], Optional[float]]] = None   # (compradora, vendedora)
    price_b: Optional[Tuple[Optional[float], Optional[float]]] = None
    notes: List[str] = field(default_factory=list)
    source: str = "BYMA"
    band_lower: Optional[float] = None
    band_upper: Optional[float] = None
    long_mean: Optional[float] = None         # media de hasta un año
    history_days: int = 0
    history_source: Optional[str] = None      # 'RAVA' | 'PROPIA'
    band_signal: Optional[str] = None         # 'B_TO_A' (ratio alto: vender B, comprar A) | 'A_TO_B'
    expected_net_pct: Optional[float] = None  # nominales ganados si el ratio vuelve a la media, neto de 4 operaciones
    backtest: Optional[Dict] = None
    reliable: bool = False                    # la banda fue rentable en este par el último año
    symbol_a: Optional[str] = None            # especies que se comparan (AL30D, TZX28...)
    symbol_b: Optional[str] = None
    flow_adjusted: bool = False               # historia corregida por los pagos de cada bono

    def to_dict(self) -> Dict:
        return asdict(self)


def daily_series(db: Session, ticker: str, column, settlement: str = "24HS",
                 max_days: int = 252) -> "OrderedDict[date, float]":
    """Último valor de cada rueda (fecha ART) para una columna de PriceSnapshot."""
    rows = db.execute(
        select(PriceSnapshot.timestamp, column)
        .where(PriceSnapshot.ticker == ticker, PriceSnapshot.settlement_type == settlement,
               column.is_not(None))
        .order_by(PriceSnapshot.id)
    ).all()
    out: "OrderedDict[date, float]" = OrderedDict()
    for ts, v in rows:
        if ts.tzinfo is None:
            from datetime import timezone
            ts = ts.replace(tzinfo=timezone.utc)
        out[ts.astimezone(ART).date()] = float(v)
    while len(out) > max_days:
        out.popitem(last=False)
    return out


def history_stats(values: List[float]) -> Tuple[Optional[float], Optional[float]]:
    if len(values) < MIN_HISTORY_DAYS:
        return None, None
    s = stdev(values)
    return mean(values), (s if s > 1e-12 else None)


def _cutoff_window(pay: date) -> Tuple[date, date]:
    """
    Ruedas entre las que el precio de 24hs deja de incluir un pago: desde dos ruedas antes de la
    fecha efectiva de pago hasta la rueda siguiente. No es siempre la misma (TX28 de nov-2026 cortó
    dos ruedas antes; AN29 de may-2026, una; DICP de dic-2025, el día del pago) y la fecha
    publicada puede correrse un día por feriados, así que se toma toda la ventana.
    """
    effective = pay
    while not is_business_day(effective):
        effective += timedelta(days=1)
    return previous_business_day(ex_date(pay)), next_business_day(effective)


def logged_flows(db: Session, base: str, currency: str) -> List[Tuple[date, float]]:
    rows = db.execute(
        select(BondFlowLog.pay_date, BondFlowLog.amount)
        .where(BondFlowLog.ticker_base == base, BondFlowLog.currency == currency)
        .order_by(BondFlowLog.pay_date)
    ).all()
    return [(d, float(a)) for d, a in rows]


def pending_cutoff(flows: List[Tuple[date, float]], today: date) -> Optional[date]:
    """Fecha de pago si hoy cae en la ventana del corte (no se sabe si el precio ya es ex-cupón)."""
    for pay, _ in flows:
        first, last = _cutoff_window(pay)
        if first <= today <= last:
            return pay
    return None


def adjust_for_flows(closes: Dict[date, float], partner: Dict[date, float],
                     flows: List[Tuple[date, float]], before: date) -> Dict[date, float]:
    """
    Descuenta de los cierres anteriores a cada pago ya cortado el monto pagado (como un precio
    ajustado por dividendos), para que el ratio no salte el día del corte. La rueda exacta del
    corte se elige dentro de la ventana posible: la de mayor caída contra el otro bono del par.
    """
    days = sorted(closes)
    cuts: List[Tuple[date, float]] = []
    for pay, amount in flows:
        first, last = _cutoff_window(pay)
        if last >= before:
            continue                               # todavía no pasó: lo cubre pending_cutoff
        best = None
        for i, c in enumerate(days):
            if i == 0 or not (first <= c <= last):
                continue
            p = days[i - 1]
            excess = closes[c] / closes[p] - (partner[c] / partner[p] if c in partner and p in partner else 1.0)
            if best is None or excess < best[0]:
                best = (excess, c, closes[p])
        if best and best[2] > amount:
            cuts.append((best[1], 1.0 - amount / best[2]))
    out = dict(closes)
    for cut, factor in cuts:
        for d in days:
            if d < cut:
                out[d] *= factor
    return out


def ratio_history(db: Session, a: str, b: str, settlement: str = "24HS",
                  before: Optional[date] = None, suffix: str = "D",
                  adjust_flows: bool = False) -> Tuple[List[float], Optional[str]]:
    """
    Serie diaria del ratio B/A (misma especie), en orden cronológico, y de dónde sale. Excluye la
    rueda en curso (`before`): la banda se arma con ruedas cerradas y se compara contra el ratio de
    hoy. Con `adjust_flows`, la historia se corrige por los pagos de cada bono.
    """
    rows = db.execute(
        select(DailyClose.symbol, DailyClose.day, DailyClose.close)
        .where(DailyClose.symbol.in_((a + suffix, b + suffix)), DailyClose.close > 0)
    ).all()
    ca = {d: c for sym, d, c in rows if sym == a + suffix and (before is None or d < before)}
    cb = {d: c for sym, d, c in rows if sym == b + suffix and (before is None or d < before)}
    if adjust_flows and before is not None:
        ccy = "USD" if suffix else "ARS"
        raw_a, raw_b = ca, cb
        ca = adjust_for_flows(raw_a, raw_b, logged_flows(db, a, ccy), before)
        cb = adjust_for_flows(raw_b, raw_a, logged_flows(db, b, ccy), before)
    days = sorted(d for d in ca if d in cb)
    if len(days) >= MIN_HISTORY_DAYS:
        return [cb[d] / ca[d] for d in days][-(LONG_DAYS + BAND_DAYS):], "RAVA"
    if adjust_flows:
        return [], None                            # la serie propia no está corregida por pagos
    column = PriceSnapshot.price_mep if suffix else PriceSnapshot.price_ars
    sa = daily_series(db, a, column, settlement)
    sb = daily_series(db, b, column, settlement)
    own = [sb[d] / sa[d] for d in sa if d in sb and sa[d] > 0 and (before is None or d < before)]
    return own, ("PROPIA" if own else None)


def band_of(values: List[float]) -> Tuple[Optional[float], Optional[float]]:
    """Media y desvío de las últimas BAND_DAYS ruedas (None si no alcanza la historia)."""
    if len(values) < MIN_HISTORY_DAYS:
        return None, None
    window = values[-BAND_DAYS:]
    s = stdev(window)
    return mean(window), (s if s > 1e-12 else None)


def backtest_band(values: List[float], roundtrip_cost_pct: float, min_net_pct: float) -> Optional[Dict]:
    """
    ¿Qué habría pasado operando la banda en este par? Con cierres diarios: entra cuando el ratio
    sale de la banda y el desvío contra la media cubre costos + ganancia mínima; sale cuando el
    ratio cruza su media móvil o a las BACKTEST_HOLD_DAYS ruedas. Resultado en % de nominales,
    neto de las 4 operaciones. Es orientativo: usa cierres, no puntas.
    """
    if len(values) < BAND_DAYS + MIN_HISTORY_DAYS:
        return None
    results: List[float] = []
    i = BAND_DAYS
    while i < len(values) - 1:
        window = values[i - BAND_DAYS:i]
        m, sd = mean(window), stdev(window)
        dev = values[i] - m
        if sd > 1e-12 and abs(dev) >= BAND_K * sd and abs(dev) / m * 100.0 >= roundtrip_cost_pct + min_net_pct:
            j = i + 1
            while j < len(values) - 1 and j < i + BACKTEST_HOLD_DAYS:
                if (values[j] - mean(values[j - BAND_DAYS:j])) * dev <= 0:
                    break
                j += 1
            gross = (values[i] / values[j] - 1.0) if dev > 0 else (values[j] / values[i] - 1.0)
            results.append(gross * 100.0 - roundtrip_cost_pct)
            i = j + 1
        else:
            i += 1
    n = len(results)
    wins = sum(1 for x in results if x > 0)
    avg = mean(results) if results else None
    reliable = bool(n >= BACKTEST_MIN_SIGNALS and avg >= BACKTEST_MIN_AVG_NET_PCT
                    and wins / n >= BACKTEST_MIN_WIN_RATE)
    return {"signals": n, "wins": wins, "avg_net_pct": round(avg, 2) if avg is not None else None,
            "worst_pct": round(min(results), 2) if results else None,
            "best_pct": round(max(results), 2) if results else None,
            "days": len(values) - BAND_DAYS, "reliable": reliable}


def compute_pair_ratios(db: Session, view: MarketView, params: TradingParams,
                        settlements: Tuple[str, ...] = ("CI", "24HS")) -> List[PairRatio]:
    fee = params.commission_pct / 100.0
    back_leg = (1 - fee) / (1 + fee)            # costo de la rotación de vuelta, cuando el ratio regrese
    out: List[PairRatio] = []
    for spec in pair_specs():
        a, b, kind = spec.a, spec.b, spec.kind
        cutoff, missing_flows = None, False
        if spec.adjust_flows:
            ccy = "USD" if spec.suffix else "ARS"
            fa, fb = logged_flows(db, a, ccy), logged_flows(db, b, ccy)
            missing_flows = not fa or not fb
            cutoff = pending_cutoff(fa + fb, view.today)
        if cutoff or missing_flows:
            hist, hist_source = [], None
        else:
            hist, hist_source = ratio_history(db, a, b, before=view.today, suffix=spec.suffix,
                                              adjust_flows=spec.adjust_flows)
        b_mean, b_std = band_of(hist)
        has_band = b_mean is not None and b_std is not None
        long_mean = mean(hist[-LONG_DAYS:]) if len(hist) >= MIN_HISTORY_DAYS else None
        test = backtest_band(hist, 4 * params.commission_pct, params.min_net_profit_pct)
        reliable = bool(test and test["reliable"])
        lower = b_mean - BAND_K * b_std if has_band else None
        upper = b_mean + BAND_K * b_std if has_band else None
        calib = f"BANDA_{min(len(hist), BAND_DAYS)}r" if has_band else ("SIN_PAGOS" if missing_flows else "CORTE_CUPON" if cutoff else "SIN_HISTORIA")
        for st in settlements:
            ba, bb = view.book(spec.symbol_a, st), view.book(spec.symbol_b, st)
            if not ba or not bb:
                continue
            mid = bb.mid / ba.mid if ba.mid and bb.mid else None
            a_to_b = (ba.best_bid * (1 - fee)) / (bb.best_ask * (1 + fee)) if ba.best_bid and bb.best_ask else None
            b_to_a = (bb.best_bid * (1 - fee)) / (ba.best_ask * (1 + fee)) if bb.best_bid and ba.best_ask else None
            z = round((mid - b_mean) / b_std, 2) if mid and has_band else None

            notes: List[str] = []
            band_signal, expected = None, None
            if missing_flows:
                notes.append("Sin banda: faltan los pagos históricos de estos bonos, que se descargan de "
                             "Bull Market una vez por día con la sesión activa.")
            elif cutoff:
                notes.append(f"Corte de cupón en curso (pago del {cutoff:%d/%m}): sin banda hasta que pase, "
                             f"porque el precio de uno de los dos bonos está dejando de incluir el pago.")
            elif not has_band:
                notes.append(f"Sin banda hasta tener {MIN_HISTORY_DAYS} ruedas de historia ({len(hist)} disponibles).")
            elif mid and mid >= upper and b_to_a:
                # Ratio alto: vender B y comprar A ahora; deshacer cuando el ratio vuelva a la media
                expected = (b_to_a * back_leg / b_mean - 1.0) * 100.0
                if expected >= params.min_net_profit_pct:
                    band_signal = "B_TO_A"
                else:
                    notes.append(f"Sobre la banda, pero volver a la media dejaría {expected:+.2f}% neto: no cubre el mínimo.")
            elif mid and mid <= lower and a_to_b:
                expected = (a_to_b * b_mean * back_leg - 1.0) * 100.0
                if expected >= params.min_net_profit_pct:
                    band_signal = "A_TO_B"
                else:
                    notes.append(f"Bajo la banda, pero volver a la media dejaría {expected:+.2f}% neto: no cubre el mínimo.")
            if band_signal and not reliable:
                if test and test["signals"]:
                    notes.append(
                        f"Fuera de banda, pero en este par la banda no fue confiable el último año "
                        f"({test['wins']} de {test['signals']} señales con ganancia, neto medio "
                        f"{test['avg_net_pct']:+.2f}%, peor {test['worst_pct']:+.2f}%): informativo.")
                else:
                    notes.append("Fuera de banda, pero sin historia suficiente para probar la banda en este par: informativo.")
            out.append(PairRatio(
                a=a, b=b, kind=kind, settlement=st,
                mid_ratio=round(mid, 4) if mid else None,
                rotate_a_to_b=round(a_to_b, 4) if a_to_b else None,
                rotate_b_to_a=round(b_to_a, 4) if b_to_a else None,
                z_score=z, hist_mean=round(b_mean, 4) if has_band else None,
                hist_std=round(b_std, 4) if has_band else None, calibration=calib,
                price_a=(ba.best_bid, ba.best_ask), price_b=(bb.best_bid, bb.best_ask), notes=notes,
                source=combined_source(ba, bb),
                band_lower=round(lower, 4) if has_band else None,
                band_upper=round(upper, 4) if has_band else None,
                long_mean=round(long_mean, 4) if long_mean else None,
                history_days=len(hist), history_source=hist_source,
                band_signal=band_signal,
                expected_net_pct=round(expected, 3) if expected is not None else None,
                backtest=test, reliable=reliable,
                symbol_a=spec.symbol_a, symbol_b=spec.symbol_b, flow_adjusted=spec.adjust_flows,
            ))
    return out


def ytm_spread_stats(db: Session, a: str, b: str) -> Tuple[Optional[float], Optional[float], int]:
    """Media y desvío del spread de TIR (A - B, en bps) con la serie diaria real."""
    sa = daily_series(db, a, PriceSnapshot.ytm_percentage)
    sb = daily_series(db, b, PriceSnapshot.ytm_percentage)
    spreads = [(sa[d] - sb[d]) * 100.0 for d in sa if d in sb]
    m, s = history_stats(spreads)
    return m, s, len(spreads)
