"""
Ratios entre bonos con puntas (especie D contra especie D, mismo plazo) y z-score histórico.

- Ratio medio = medio(B) / medio(A).
- Rotar A -> B (vender A a la compradora, comprar B a la vendedora): nominales de B que se
  obtienen por cada nominal de A, costos incluidos  =  compradora_A * (1-c) / (vendedora_B * (1+c)).
- Z-score: con la serie diaria real (último ratio de cada rueda, guardado en la base) cuando hay
  al menos MIN_HISTORY_DAYS ruedas; si no, calibración estática de mercado (y se informa).
"""

from collections import OrderedDict
from dataclasses import asdict, dataclass, field
from datetime import date
from statistics import mean, stdev
from typing import Dict, List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.arbitrage.market_view import MarketView, combined_source
from backend.app.db.models import PriceSnapshot
from backend.app.services.market_calendar import ART
from backend.app.services.trading_settings import TradingParams

LAW_PAIRS: List[Tuple[str, str]] = [
    ("AL29", "GD29"), ("AL30", "GD30"), ("AL35", "GD35"), ("AE38", "GD38"), ("AL41", "GD41"),
]
# Pares que el trader seguía en su monitor (temporal/MonitorMercado.ps1, "ratios agresivos")
CURVE_PAIRS: List[Tuple[str, str]] = [
    ("AE38", "GD35"), ("AE38", "GD41"), ("GD38", "GD41"), ("GD35", "GD38"),
]

MIN_HISTORY_DAYS = 20
STATIC_LAW_MEAN = 1.055   # prima Ley NY promedio (calibración de mercado, sin historia propia)
STATIC_LAW_STD = 0.032


@dataclass
class PairRatio:
    a: str
    b: str
    kind: str                       # 'LEY' | 'CURVA'
    settlement: str
    mid_ratio: Optional[float]      # medio(B) / medio(A)
    rotate_a_to_b: Optional[float]  # nominales de B por nominal de A (costos incluidos)
    rotate_b_to_a: Optional[float]  # nominales de A por nominal de B (costos incluidos)
    z_score: Optional[float]
    hist_mean: Optional[float]
    hist_std: Optional[float]
    calibration: str                # 'HISTORICA_<n>d' | 'ESTATICA' | 'SIN_HISTORIA'
    price_a: Optional[Tuple[Optional[float], Optional[float]]] = None   # (compradora, vendedora)
    price_b: Optional[Tuple[Optional[float], Optional[float]]] = None
    notes: List[str] = field(default_factory=list)
    source: str = "BYMA"

    def to_dict(self) -> Dict:
        return asdict(self)


def daily_series(db: Session, ticker: str, column, settlement: str = "24HS",
                 max_days: int = 252) -> "OrderedDict[date, float]":
    """Último valor de cada rueda (fecha ART) para una columna de PriceSnapshot."""
    rows = db.execute(
        select(PriceSnapshot.timestamp, column)
        .where(PriceSnapshot.ticker == ticker, PriceSnapshot.settlement_type == settlement,
               column.is_not(None))
        .order_by(PriceSnapshot.id)
    ).all()
    out: "OrderedDict[date, float]" = OrderedDict()
    for ts, v in rows:
        if ts.tzinfo is None:
            from datetime import timezone
            ts = ts.replace(tzinfo=timezone.utc)
        out[ts.astimezone(ART).date()] = float(v)
    while len(out) > max_days:
        out.popitem(last=False)
    return out


def history_stats(values: List[float]) -> Tuple[Optional[float], Optional[float]]:
    if len(values) < MIN_HISTORY_DAYS:
        return None, None
    s = stdev(values)
    return mean(values), (s if s > 1e-12 else None)


def ratio_history(db: Session, a: str, b: str, settlement: str = "24HS") -> List[float]:
    sa = daily_series(db, a, PriceSnapshot.price_mep, settlement)
    sb = daily_series(db, b, PriceSnapshot.price_mep, settlement)
    return [sb[d] / sa[d] for d in sa if d in sb and sa[d] > 0]


def compute_pair_ratios(db: Session, view: MarketView, params: TradingParams,
                        settlements: Tuple[str, ...] = ("CI", "24HS")) -> List[PairRatio]:
    fee = params.commission_pct / 100.0
    out: List[PairRatio] = []
    for kind, pairs in (("LEY", LAW_PAIRS), ("CURVA", CURVE_PAIRS)):
        for a, b in pairs:
            hist = ratio_history(db, a, b)
            h_mean, h_std = history_stats(hist)
            for st in settlements:
                ba, bb = view.book(a + "D", st), view.book(b + "D", st)
                if not ba or not bb:
                    continue
                mid = bb.mid / ba.mid if ba.mid and bb.mid else None
                a_to_b = (ba.best_bid * (1 - fee)) / (bb.best_ask * (1 + fee)) if ba.best_bid and bb.best_ask else None
                b_to_a = (bb.best_bid * (1 - fee)) / (ba.best_ask * (1 + fee)) if bb.best_bid and ba.best_ask else None

                if h_mean is not None and h_std:
                    z_mean, z_std, calib = h_mean, h_std, f"HISTORICA_{len(hist)}d"
                elif kind == "LEY":
                    z_mean, z_std, calib = STATIC_LAW_MEAN, STATIC_LAW_STD, "ESTATICA"
                else:
                    z_mean = z_std = None
                    calib = "SIN_HISTORIA"
                z = round((mid - z_mean) / z_std, 2) if mid and z_mean and z_std else None

                notes = []
                if calib == "ESTATICA":
                    notes.append(f"Z-score con calibración estática ({len(hist)} de {MIN_HISTORY_DAYS} ruedas de historia).")
                elif calib == "SIN_HISTORIA":
                    notes.append(f"Sin z-score hasta acumular {MIN_HISTORY_DAYS} ruedas ({len(hist)} disponibles).")
                out.append(PairRatio(
                    a=a, b=b, kind=kind, settlement=st,
                    mid_ratio=round(mid, 4) if mid else None,
                    rotate_a_to_b=round(a_to_b, 4) if a_to_b else None,
                    rotate_b_to_a=round(b_to_a, 4) if b_to_a else None,
                    z_score=z, hist_mean=round(z_mean, 4) if z_mean else None,
                    hist_std=round(z_std, 4) if z_std else None, calibration=calib,
                    price_a=(ba.best_bid, ba.best_ask), price_b=(bb.best_bid, bb.best_ask), notes=notes,
                    source=combined_source(ba, bb),
                ))
    return out


def ytm_spread_stats(db: Session, a: str, b: str) -> Tuple[Optional[float], Optional[float], int]:
    """Media y desvío del spread de TIR (A - B, en bps) con la serie diaria real."""
    sa = daily_series(db, a, PriceSnapshot.ytm_percentage)
    sb = daily_series(db, b, PriceSnapshot.ytm_percentage)
    spreads = [(sa[d] - sb[d]) * 100.0 for d in sa if d in sb]
    m, s = history_stats(spreads)
    return m, s, len(spreads)
