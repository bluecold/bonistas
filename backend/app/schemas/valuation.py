from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import date

class CashFlowItemResponse(BaseModel):
    date: date
    days_from_settlement: int
    interest_rate: float
    coupon_amount: float
    amortization_amount: float
    total_cashflow: float
    residual_capital: float

class ValuationRequest(BaseModel):
    ticker: str = Field(..., description="Ticker del bono, ej: AL30, GD30, GD29")
    price: float = Field(..., gt=0, description="Precio sucio (dirty price) en USD o ARS")
    settlement_date: Optional[date] = Field(None, description="Fecha de liquidación (default: hoy)")

class ValuationResponse(BaseModel):
    ticker: str
    price: float
    settlement_date: date
    residual_capital: float
    accrued_interest: float
    technical_value: float
    parity_percentage: float
    ytm_percentage: Optional[float] = None
    tem_percentage: Optional[float] = None
    tna_percentage: Optional[float] = None
    macaulay_duration: Optional[float] = None
    modified_duration: Optional[float] = None

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
    broker_commission_pct: float = Field(0.5, ge=0.0, le=5.0, description="Comisión del broker en %")
    byma_fee_pct: float = Field(0.04, ge=0.0, le=1.0, description="Derechos de mercado BYMA en %")

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

