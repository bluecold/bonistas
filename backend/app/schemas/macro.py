from pydantic import BaseModel, ConfigDict
from typing import Optional
from datetime import date, datetime
from decimal import Decimal

class MacroIndicatorBase(BaseModel):
    date: date
    name: str
    value: Decimal
    source: Optional[str] = None

class MacroIndicatorCreate(MacroIndicatorBase):
    pass

class MacroIndicatorResponse(MacroIndicatorBase):
    id: int
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)

class DolarQuote(BaseModel):
    moneda: str
    casa: str
    nombre: str
    compra: float
    venta: float
    fechaActualizacion: str

