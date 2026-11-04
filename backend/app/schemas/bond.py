from pydantic import BaseModel, ConfigDict
from typing import Optional
from datetime import date
from decimal import Decimal

class BondBase(BaseModel):
    ticker: str
    name: str
    isin: Optional[str] = None
    currency: str
    law: str
    bond_type: str
    amortization_type: Optional[str] = None
    start_date: Optional[date] = None
    maturity_date: date
    coupon_rate: Optional[Decimal] = None
    base_nominal: Optional[Decimal] = Decimal("100.0")
    description: Optional[str] = None
    short_description: Optional[str] = None

class BondCreate(BondBase):
    pass

class BondUpdate(BaseModel):
    name: Optional[str] = None
    coupon_rate: Optional[Decimal] = None
    description: Optional[str] = None
    short_description: Optional[str] = None

class BondResponse(BondBase):
    model_config = ConfigDict(from_attributes=True)

