from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import date

class CashFlowItemResponse(BaseModel):
    date: date
    days_from_settlement: int
    interest_rate: Optional[float] = None
    coupon_amount: Optional[float] = None
    amortization_amount: Optional[float] = None
    total_cashflow: float
    residual_capital: Optional[float] = None
    source: str = "PROPIO"   # PROPIO (cronograma verificado) o COMPARARBONOS (solo flujo total)
    currency: Optional[str] = None          # moneda de los montos (USD / ARS), cuando se conoce
    payment_currency: Optional[str] = None  # ON: dólar de pago (MEP / CCL) según Bull Market

class ValuationRequest(BaseModel):
    ticker: str = Field(..., description="Ticker del bono, ej: AL30, GD30, GD29")
    price: float = Field(..., gt=0, description="Precio sucio (dirty price) en USD o ARS")
    settlement_date: Optional[date] = Field(None, description="Fecha de liquidación (si se indica, prevalece)")
    settlement: str = Field("24HS", pattern="^(?i:CI|24HS)$",
                            description="Plazo si no se indica fecha: CI = hoy, 24HS = próximo día hábil")

class ValuationResponse(BaseModel):
    ticker: str
    price: float
    settlement_date: date
    residual_capital: Optional[float] = None
    accrued_interest: Optional[float] = None
    technical_value: Optional[float] = None
    parity_percentage: Optional[float] = None
    ytm_percentage: Optional[float] = None
    tem_percentage: Optional[float] = None
    tna_percentage: Optional[float] = None
    macaulay_duration: Optional[float] = None
    modified_duration: Optional[float] = None
    source: str = "PROPIO"
    yield_is_real: bool = False   # True para CER: la TIR es real (sobre inflación)

class BreakevenResponse(BaseModel):
    fixed_ticker: Optional[str] = None
    fixed_ytm_percentage: float
    cer_ticker: Optional[str] = None
    cer_ytm_percentage: float
    breakeven_annual_percentage: float
    breakeven_monthly_percentage: float
    description: str

class LawSpreadPair(BaseModel):
    al_ticker: str
    gd_ticker: str
    price_al: Optional[float] = None
    price_gd: Optional[float] = None
    price_ratio: Optional[float] = None
    price_spread_percentage: Optional[float] = None
    ytm_al: Optional[float] = None
    ytm_gd: Optional[float] = None
    yield_spread_bps: Optional[float] = None
    status: str

class SwapRequest(BaseModel):
    sell_ticker: str = Field(..., description="Ticker del bono a vender, ej: GD30")
    buy_ticker: str = Field(..., description="Ticker del bono a comprar, ej: AL30")
    sell_nominal: float = Field(10000.0, gt=0, description="Cantidad nominal a vender")
    broker_commission_pct: float = Field(
        0.11, ge=0.0, le=5.0,
        description="Costo por operación en % (comisión + derechos + impuestos). Default: 0,11% todo incluido"
    )
    byma_fee_pct: float = Field(
        0.0, ge=0.0, le=1.0,
        description="Derechos de mercado adicionales en %, solo si NO están incluidos en la comisión"
    )
    settlement: str = Field("24HS", pattern="^(?i:CI|24HS)$", description="Plazo de liquidación: CI o 24HS")

class SwapResponse(BaseModel):
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
    yield_pickup_bps: Optional[float] = None
    duration_change: Optional[float] = None
    summary_message: str
    currency: str = "USD"
    settlement: str = "24HS"

