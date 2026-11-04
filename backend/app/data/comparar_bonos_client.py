"""
Cliente de CompararBonos (https://compararbonos.com.ar/api/bonos), API JSON pública.

Se usa como fuente de REFERENCIA (una vez por día): flujos futuros por 100 VN (para CER ya
ajustados por el CER vigente), pago final de LECAP/BONCAP, valor técnico, capital residual,
próximo cupón y plazo de liquidación de la rueda.
"""

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

import httpx

logger = logging.getLogger(__name__)

URL = "https://compararbonos.com.ar/api/bonos"
HEADERS = {"User-Agent": "bonistas-monitor/1.1 (uso personal)", "Accept": "application/json"}

# Tipos de CompararBonos que corresponden al alcance de bonos de v1.1 (sin ONs)
BOND_TYPES = {"Soberano", "International", "CER", "Provincial", "Treasury", "DUAL", "DL",
              "TAMAR", "BONCAP", "LECAP", "FIJA"}


@dataclass
class ReferenceBondData:
    ticker_base: str
    tipo: str
    moneda: Optional[str]
    flows: List[Tuple[date, float]] = field(default_factory=list)
    technical_value: Optional[float] = None
    residual_capital: Optional[float] = None
    final_payment: Optional[float] = None
    yield_is_real: bool = False
    flows_cer_adjusted: bool = False
    ref_ytm_pct: Optional[float] = None
    ref_duration: Optional[float] = None
    payment_structure: Optional[str] = None
    species: List[str] = field(default_factory=list)


def _f(v: Any) -> Optional[float]:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def parse_reference(payload: Dict[str, Any]) -> Tuple[Dict[str, ReferenceBondData], Dict[str, Any]]:
    """
    Agrupa por ticker base (los flujos son los mismos para pesos/D/C) y devuelve
    (bonos por ticker base, metadatos de la rueda).
    """
    out: Dict[str, ReferenceBondData] = {}
    for b in payload.get("bonds") or []:
        tipo = b.get("tipo")
        if tipo not in BOND_TYPES:
            continue
        base = str(b.get("tickerBase") or b.get("ticker") or "").upper()
        if not base:
            continue
        ref = out.get(base)
        if ref is None:
            flows = []
            for f in b.get("flujos") or []:
                try:
                    flows.append((date.fromisoformat(f["fecha"]), float(f["monto"])))
                except (KeyError, TypeError, ValueError):
                    continue
            ref = ReferenceBondData(
                ticker_base=base,
                tipo=tipo,
                moneda=b.get("moneda"),
                flows=sorted(flows),
                technical_value=_f(b.get("valorTecnico")),
                residual_capital=_f(b.get("capitalResidual")),
                final_payment=_f(b.get("pagoFinal")),
                yield_is_real=bool(b.get("tirEsReal")),
                flows_cer_adjusted=bool(b.get("flujosAjustados")),
                ref_ytm_pct=_f(b.get("tir")),
                ref_duration=_f(b.get("duration")),
                payment_structure=b.get("estructuraPago"),
            )
            out[base] = ref
        ticker = str(b.get("ticker") or "").upper()
        if ticker and ticker not in ref.species:
            ref.species.append(ticker)
    meta = payload.get("rueda") or {}
    return out, meta


class CompararBonosClient:
    def __init__(self, url: str = URL, timeout: float = 25.0):
        self.url = url
        self.timeout = timeout

    async def fetch_raw(self) -> Dict[str, Any]:
        async with httpx.AsyncClient(timeout=self.timeout, headers=HEADERS) as client:
            res = await client.get(self.url)
            res.raise_for_status()
            data = res.json()
        if not isinstance(data, dict) or data.get("status") != "ok":
            raise ValueError("Respuesta inesperada de CompararBonos")
        return data

    async def fetch_reference(self) -> Tuple[Dict[str, ReferenceBondData], Dict[str, Any]]:
        refs, meta = parse_reference(await self.fetch_raw())
        logger.info(f"CompararBonos: {len(refs)} bonos de referencia (rueda {meta.get('fechaRueda')})")
        return refs, meta
