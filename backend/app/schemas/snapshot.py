from pydantic import BaseModel, ConfigDict
from typing import Optional
from datetime import datetime
from decimal import Decimal

class PriceSnapshotBase(BaseModel):
    ticker: str
    settlement_type: str = "24HS"
    price_ars: Optional[Decimal] = None
    price_mep: Optional[Decimal] = None
    price_ccl: Optional[Decimal] = None
    last_price: Optional[Decimal] = None
    day_difference: Optional[Decimal] = None
    volume_millions: Optional[Decimal] = None
    technical_value: Optional[Decimal] = None
    parity_percentage: Optional[Decimal] = None
    ytm_percentage: Optional[Decimal] = None
    tem_percentage: Optional[Decimal] = None
    tna_percentage: Optional[Decimal] = None
    modified_duration: Optional[Decimal] = None

class PriceSnapshotCreate(PriceSnapshotBase):
    timestamp: Optional[datetime] = None

class PriceSnapshotResponse(PriceSnapshotBase):
    id: int
    timestamp: datetime
    model_config = ConfigDict(from_attributes=True)

class BondQuoteView(BaseModel):
    ticker: str
    name: str
    bond_type: str
    law: str
    settlement_type: str
    price_ars: Optional[float] = None
    price_mep: Optional[float] = None
    price_ccl: Optional[float] = None
    last_price: Optional[float] = None
    day_difference: Optional[float] = None
    volume_millions: Optional[float] = None
    technical_value: Optional[float] = None
    parity_percentage: Optional[float] = None
    ytm_percentage: Optional[float] = None
    tem_percentage: Optional[float] = None
    tna_percentage: Optional[float] = None
    modified_duration: Optional[float] = None
    timestamp: Optional[datetime] = None

