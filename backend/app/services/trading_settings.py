"""
Parámetros operativos del trader, editables desde el dashboard y persistidos en la base.
Los valores por defecto salen de la configuración (variables de entorno / .env).
"""

from dataclasses import asdict, dataclass
from typing import Any, Dict

from sqlalchemy.orm import Session

from backend.app.config import settings
from backend.app.db.models import UserSetting

KEY = "trading"


@dataclass
class TradingParams:
    commission_pct: float = settings.COMMISSION_PCT        # % por operación, todo incluido
    min_net_profit_pct: float = settings.MIN_NET_PROFIT_PCT  # ganancia neta mínima para alertar
    trade_size_usd: float = settings.TRADE_SIZE_USD        # tamaño a ejecutar en ambas patas

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


LIMITS = {
    "commission_pct": (0.0, 3.0),
    "min_net_profit_pct": (0.0, 20.0),
    "trade_size_usd": (1.0, 10_000_000.0),
}


def validate(values: Dict[str, Any]) -> Dict[str, float]:
    clean: Dict[str, float] = {}
    for k, v in values.items():
        if k not in LIMITS:
            raise ValueError(f"Parámetro desconocido: {k}")
        lo, hi = LIMITS[k]
        f = float(v)
        if not lo <= f <= hi:
            raise ValueError(f"{k} debe estar entre {lo} y {hi}")
        clean[k] = f
    return clean


def get_params(db: Session) -> TradingParams:
    row = db.get(UserSetting, KEY)
    params = TradingParams()
    if row and isinstance(row.value, dict):
        for k, v in row.value.items():
            if k in LIMITS:
                setattr(params, k, float(v))
    return params


def update_params(db: Session, values: Dict[str, Any]) -> TradingParams:
    clean = validate(values)
    current = get_params(db).to_dict()
    current.update(clean)
    row = db.get(UserSetting, KEY)
    if row:
        row.value = current
    else:
        db.add(UserSetting(key=KEY, value=current))
    db.commit()
    return get_params(db)
