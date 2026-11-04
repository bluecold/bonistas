"""
Motor de cálculo financiero de renta fija para bonos soberanos y subsoberanos argentinos.
Calcula Valor Técnico, Paridad, TIR/YTM con resolución Newton-Raphson / Brentq, Duración y Modified Duration.
"""

import math
import logging
from datetime import date
from typing import List, Optional, Tuple
from scipy.optimize import brentq

from backend.app.quant.cashflows import CashFlowItem, get_hard_dollar_schedule

logger = logging.getLogger(__name__)

def calculate_accrued_interest(
    ticker: str,
    settlement_date: date,
    coupon_rate: Optional[float] = None,
    base_nominal: float = 100.0,
    frequency: int = 2
) -> float:
    """
    Calcula los intereses corridos devengados desde el último cupón hasta la fecha de liquidación.
    Convención de mercado argentino: Actual/365 sobre capital residual vigente.
    """
    schedule = get_hard_dollar_schedule(ticker)
    
    if schedule:
        # Encontrar el último cupón pasado y el próximo futuro
        last_coupon_date: Optional[date] = None
        next_coupon: Optional[dict] = None
        current_residual = base_nominal

        for event in schedule:
            d = event["date"]
            if d <= settlement_date:
                last_coupon_date = d
                current_residual -= (event["amort_pct"] / 100.0) * base_nominal
                current_residual = max(0.0, current_residual)
            else:
                next_coupon = event
                break

        if not last_coupon_date or not next_coupon or current_residual <= 0:
            return 0.0

        days_accrued = (settlement_date - last_coupon_date).days
        c_rate = next_coupon["coupon_tna"]
        
        # Interés corrido = Residual * TNA * (días / 365)
        accrued = current_residual * c_rate * (days_accrued / 365.0)
        return float(round(accrued, 4))

    # Genérico para bonos regulares
    c_rate = float(coupon_rate) if coupon_rate is not None else 0.0
    if c_rate <= 0:
        return 0.0
    
    # Estimación semestral estándar (182.5 días promedio)
    return float(round(base_nominal * c_rate * (30.0 / 365.0), 4))


def calculate_residual_capital(ticker: str, settlement_date: date, base_nominal: float = 100.0) -> float:
    """Calcula el capital residual después de amortizaciones históricas."""
    schedule = get_hard_dollar_schedule(ticker)
    if not schedule:
        return base_nominal

    residual = base_nominal
    for event in schedule:
        if event["date"] <= settlement_date:
            residual -= (event["amort_pct"] / 100.0) * base_nominal
            residual = max(0.0, residual)
    return float(round(residual, 4))


def calculate_technical_value(residual_capital: float, accrued_interest: float) -> float:
    """Valor Técnico = Capital Residual + Intereses Corridos."""
    return float(round(residual_capital + accrued_interest, 4))


def calculate_parity(price: float, technical_value: float) -> float:
    """Paridad (%) = (Precio / Valor Técnico) * 100."""
    if technical_value <= 0 or price <= 0:
        return 0.0
    return float(round((price / technical_value) * 100.0, 3))


def calculate_ytm(
    price: float,
    cashflows: List[CashFlowItem],
    max_iter: int = 100,
    tol: float = 1e-6
) -> Optional[float]:
    """
    Calcula la Tasa Interna de Retorno (TIR / YTM) anualizada.
    Resuelve: Precio = sum( CF_i / (1 + r)^(d_i / 365) )
    Usa el algoritmo Newton-Raphson con fallback robusto a Brentq de SciPy.
    """
    if price <= 0 or not cashflows:
        return None

    # Función de valor presente y su derivada
    def pv(r: float) -> float:
        if r <= -1.0:
            return 1e9
        total = 0.0
        for cf in cashflows:
            t = cf.days_from_settlement / 365.0
            total += cf.total_cashflow / ((1.0 + r) ** t)
        return total

    def pv_derivative(r: float) -> float:
        if r <= -1.0:
            return -1e9
        total = 0.0
        for cf in cashflows:
            t = cf.days_from_settlement / 365.0
            total -= t * cf.total_cashflow / ((1.0 + r) ** (t + 1.0))
        return total

    # 1. Intento con Newton-Raphson
    r = 0.15 # Estimación inicial razonable (15% anual)
    for _ in range(max_iter):
        f_val = pv(r) - price
        if abs(f_val) < tol:
            return float(round(r, 6))
        f_prime = pv_derivative(r)
        if abs(f_prime) < 1e-12:
            break
        r_next = r - f_val / f_prime
        if r_next <= -0.99 or r_next > 10.0:
            break
        if abs(r_next - r) < tol:
            return float(round(r_next, 6))
        r = r_next

    # 2. Fallback a Brentq garantizado en intervalo [-0.90, 5.0] (hasta 500% TIR)
    try:
        def objective(x: float) -> float:
            return pv(x) - price

        # Verificar cambio de signo
        low, high = -0.80, 5.0
        f_low = objective(low)
        f_high = objective(high)

        if f_low * f_high < 0:
            root = brentq(objective, low, high, xtol=tol)
            return float(round(root, 6))
        elif objective(0.01) * objective(15.0) < 0:
            root = brentq(objective, 0.01, 15.0, xtol=tol)
            return float(round(root, 6))
    except Exception as e:
        logger.debug(f"Brentq solver exception: {e}")

    return None


def calculate_duration_and_md(
    price: float,
    ytm: float,
    cashflows: List[CashFlowItem],
    frequency: int = 2
) -> Tuple[Optional[float], Optional[float]]:
    """
    Calcula la Duración de Macaulay y la Modified Duration (MD).
    MD = Macaulay Duration / (1 + YTM / frequency)
    """
    if price <= 0 or ytm is None or ytm <= -1.0 or not cashflows:
        return None, None

    weighted_pv_sum = 0.0
    for cf in cashflows:
        t = cf.days_from_settlement / 365.0
        pv_cf = cf.total_cashflow / ((1.0 + ytm) ** t)
        weighted_pv_sum += t * pv_cf

    macaulay_duration = weighted_pv_sum / price
    
    if frequency <= 0:
        frequency = 1
    
    modified_duration = macaulay_duration / (1.0 + (ytm / frequency))
    
    return float(round(macaulay_duration, 4)), float(round(modified_duration, 4))


def calculate_tem(ytm: float) -> float:
    """Tasa Efectiva Mensual: TEM = (1 + YTM)^(1/12) - 1."""
    if ytm is None or ytm <= -1.0:
        return 0.0
    return float(round(((1.0 + ytm) ** (1.0 / 12.0)) - 1.0, 6))


def calculate_tna(tem: float) -> float:
    """Tasa Nominal Anual a partir de la TEM: TNA = TEM * 12."""
    if tem is None:
        return 0.0
    return float(round(tem * 12.0, 6))

