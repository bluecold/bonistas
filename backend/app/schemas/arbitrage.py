from pydantic import BaseModel, ConfigDict
from typing import Optional, Any, Dict
from datetime import datetime
from decimal import Decimal

class ArbitrageSignalBase(BaseModel):
    strategy_name: str
    leg_sell_ticker: str
    leg_buy_ticker: str
    metric_name: str
    metric_value: Decimal
    historical_mean: Optional[Decimal] = None
    std_deviations: Optional[Decimal] = None
    action_recommended: str
    status: str = "ACTIVE"
    notes: Optional[str] = None
    net_profit_pct: Optional[float] = None
    confirmation: Optional[str] = None
    details: Optional[Dict[str, Any]] = None

class ArbitrageSignalCreate(ArbitrageSignalBase):
    timestamp: Optional[datetime] = None

class ArbitrageSignalResponse(ArbitrageSignalBase):
    id: int
    timestamp: datetime
    first_seen: Optional[datetime] = None
    last_seen: Optional[datetime] = None
    model_config = ConfigDict(from_attributes=True)

