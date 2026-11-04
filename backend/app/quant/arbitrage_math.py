"""
Cálculos matemáticos para arbitrajes, spreads, breakeven inflacionario y tipos de cambio implícitos.
"""

from typing import Optional, Dict, List
import numpy as np

def calculate_implied_fx(
    price_ars: Optional[float],
    price_mep: Optional[float],
    price_ccl: Optional[float]
) -> Dict[str, Optional[float]]:
    """
    Calcula los tipos de cambio financieros implícitos para un mismo título:
    - MEP: ARS / Especie D
    - CCL: ARS / Especie C
    - Canje (%): (CCL / MEP - 1) * 100
    """
    mep = None
    ccl = None
    canje_pct = None

    if price_ars and price_mep and price_mep > 0:
        mep = round(price_ars / price_mep, 2)

    if price_ars and price_ccl and price_ccl > 0:
        ccl = round(price_ars / price_ccl, 2)

    if mep and ccl and mep > 0:
        canje_pct = round(((ccl / mep) - 1.0) * 100.0, 3)

    return {
        "mep_implied": mep,
        "ccl_implied": ccl,
        "canje_pct": canje_pct
    }


def calculate_breakeven_inflation(
    fixed_ytm: float,
    cer_ytm: float
) -> Dict[str, float]:
    """
    Calcula el Breakeven de Inflación (Fisher Equation) entre Tasa Fija y CER:
    Breakeven_Anual = ((1 + TIR_TF) / (1 + TIR_CER)) - 1
    Breakeven_Mensual = (1 + Breakeven_Anual)^(1/12) - 1
    """
    if cer_ytm <= -1.0 or fixed_ytm <= -1.0:
        return {"breakeven_annual": 0.0, "breakeven_monthly": 0.0, "breakeven_monthly_pct": 0.0}

    # Fisher equation
    breakeven_annual = ((1.0 + fixed_ytm) / (1.0 + cer_ytm)) - 1.0
    breakeven_monthly = ((1.0 + breakeven_annual) ** (1.0 / 12.0)) - 1.0

    return {
        "breakeven_annual": round(breakeven_annual, 6),
        "breakeven_annual_pct": round(breakeven_annual * 100.0, 3),
        "breakeven_monthly": round(breakeven_monthly, 6),
        "breakeven_monthly_pct": round(breakeven_monthly * 100.0, 3)
    }


def calculate_law_spread(
    price_gd: float,
    price_al: float,
    ytm_gd: Optional[float] = None,
    ytm_al: Optional[float] = None
) -> Dict[str, Optional[float]]:
    """
    Métricas de la prima de legislación (Law Premium) entre Globales (GD) y Bonares (AL):
    - Price Ratio: P_GD / P_AL
    - Price Spread (%): ((P_GD / P_AL) - 1) * 100
    - Yield Spread (bps): (TIR_AL - TIR_GD) * 10,000
    """
    if price_al <= 0 or price_gd <= 0:
        return {"price_ratio": None, "price_spread_pct": None, "yield_spread_bps": None}

    ratio = round(price_gd / price_al, 4)
    spread_pct = round(((price_gd / price_al) - 1.0) * 100.0, 3)
    
    yield_spread_bps = None
    if ytm_al is not None and ytm_gd is not None:
        yield_spread_bps = round((ytm_al - ytm_gd) * 10000.0, 1)

    return {
        "price_ratio": ratio,
        "price_spread_pct": spread_pct,
        "yield_spread_bps": yield_spread_bps
    }


def calculate_z_score(
    current_value: float,
    history: List[float]
) -> Dict[str, Optional[float]]:
    """
    Calcula el Z-Score de una serie temporal:
    Z = (x - mean) / std
    """
    if not history or len(history) < 5:
        return {"z_score": None, "mean": None, "std": None}

    arr = np.array(history, dtype=np.float64)
    mean_val = float(np.mean(arr))
    std_val = float(np.std(arr, ddof=1))

    if std_val < 1e-8:
        return {"z_score": 0.0, "mean": round(mean_val, 4), "std": round(std_val, 4)}

    z = float((current_value - mean_val) / std_val)
    return {
        "z_score": round(z, 2),
        "mean": round(mean_val, 4),
        "std": round(std_val, 4)
    }

