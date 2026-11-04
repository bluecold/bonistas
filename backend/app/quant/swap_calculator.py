"""
Simulador de Swaps y Arbitrajes de Cartera para Bonos Argentinos.
Calcula el impacto neto de rotaciones entre bonos considerando comisiones de broker y aranceles BYMA.
"""

from dataclasses import dataclass
from typing import Dict, Any, Optional

@dataclass
class SwapSimulationResult:
    sell_ticker: str
    sell_nominal: float
    sell_price: float
    sell_gross_amount: float
    sell_fees: float
    sell_net_proceeds: float
    
    buy_ticker: str
    buy_nominal_acquired: float
    buy_price: float
    buy_net_cost: float
    buy_fees: float
    cash_leftover: float
    
    nominal_expansion_ratio: float
    nominal_pickup: float
    yield_pickup_bps: Optional[float]
    duration_change: Optional[float]
    summary_message: str

def simulate_bond_swap(
    sell_ticker: str,
    sell_price: float,
    sell_nominal: float,
    buy_ticker: str,
    buy_price: float,
    broker_commission_pct: float = 0.5,
    byma_fee_pct: float = 0.04,
    ytm_sell: Optional[float] = None,
    ytm_buy: Optional[float] = None,
    md_sell: Optional[float] = None,
    md_buy: Optional[float] = None
) -> SwapSimulationResult:
    """
    Calcula la rotación de cartera:
    1. Venta de sell_nominal de sell_ticker al precio sell_price (base 100).
    2. Deducción de comisión broker y aranceles BYMA.
    3. Con el neto, compra de la mayor cantidad nominal entera de buy_ticker al precio buy_price.
    4. Cálculo de nominales ganados, remanente de liquidez, yield pickup y variación de duration.
    """
    total_fee_rate = (broker_commission_pct + byma_fee_pct) / 100.0

    # Venta:
    # Precio cotiza por cada 100 nominales
    sell_gross = (sell_nominal / 100.0) * sell_price
    sell_fees = sell_gross * total_fee_rate
    sell_net = sell_gross - sell_fees

    # Compra:
    # Cada unidad nominal de buy_ticker cuesta (buy_price / 100.0) * (1 + total_fee_rate)
    cost_per_nominal = (buy_price / 100.0) * (1.0 + total_fee_rate)
    
    if cost_per_nominal > 0:
        buy_nominal = float(int(sell_net / cost_per_nominal)) # Cantidad entera de nominales
    else:
        buy_nominal = 0.0

    buy_gross = (buy_nominal / 100.0) * buy_price
    buy_fees = buy_gross * total_fee_rate
    total_buy_outlay = buy_gross + buy_fees
    cash_leftover = round(sell_net - total_buy_outlay, 2)

    # Ratios de expansión
    nominal_expansion_ratio = round(buy_nominal / sell_nominal, 4) if sell_nominal > 0 else 1.0
    nominal_pickup = round(buy_nominal - sell_nominal, 2)

    # Yield pickup
    yield_pickup_bps = None
    if ytm_buy is not None and ytm_sell is not None:
        yield_pickup_bps = round((ytm_buy - ytm_sell) * 10000.0, 1)

    # Duration change
    duration_change = None
    if md_buy is not None and md_sell is not None:
        duration_change = round(md_buy - md_sell, 3)

    summary = (
        f"Al vender {sell_nominal:,.0f} nominales de {sell_ticker} y rotar a {buy_ticker}, "
        f"se obtienen {buy_nominal:,.0f} nominales ({'+' if nominal_pickup >= 0 else ''}{nominal_pickup:,.0f} nominales, "
        f"ratio {nominal_expansion_ratio:.4f}) con un remanente en efectivo de ${cash_leftover:,.2f}."
    )

    return SwapSimulationResult(
        sell_ticker=sell_ticker,
        sell_nominal=sell_nominal,
        sell_price=round(sell_price, 4),
        sell_gross_amount=round(sell_gross, 2),
        sell_fees=round(sell_fees, 2),
        sell_net_proceeds=round(sell_net, 2),
        buy_ticker=buy_ticker,
        buy_nominal_acquired=buy_nominal,
        buy_price=round(buy_price, 4),
        buy_net_cost=round(total_buy_outlay, 2),
        buy_fees=round(buy_fees, 2),
        cash_leftover=cash_leftover,
        nominal_expansion_ratio=nominal_expansion_ratio,
        nominal_pickup=nominal_pickup,
        yield_pickup_bps=yield_pickup_bps,
        duration_change=duration_change,
        summary_message=summary
    )

