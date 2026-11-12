"""
Cliente de la API de Estadísticas del BCRA (v4.0, pública, sin token).

Variables usadas:
- 30: CER (coeficiente diario; el BCRA lo publica con fechas futuras, se toma el de hoy).
- 44: TAMAR bancos privados (% nominal anual).
- 5:  Tipo de cambio mayorista de referencia Com. A 3500.
"""

import logging
from datetime import date
from decimal import Decimal
from typing import Dict, List, Optional, Tuple

import httpx

from backend.app.schemas.macro import MacroIndicatorCreate

logger = logging.getLogger(__name__)

URL = "https://api.bcra.gob.ar/estadisticas/v4.0/monetarias/{id}"
HEADERS = {"User-Agent": "bonistas-monitor/1.1 (uso personal)", "Accept": "application/json"}

VARIABLES = {"CER": 30, "TAMAR": 44, "A3500": 5}


def latest_on_or_before(detalle: list, today: date) -> Optional[Dict]:
    """El dato más reciente con fecha <= hoy (el CER viene publicado por adelantado)."""
    best = None
    for item in detalle or []:
        try:
            d = date.fromisoformat(item["fecha"])
        except (KeyError, TypeError, ValueError):
            continue
        if d <= today and (best is None or d > best[0]):
            best = (d, item["valor"])
    return {"fecha": best[0], "valor": best[1]} if best else None


class BcraClient:
    def __init__(self, timeout: float = 20.0):
        self.timeout = timeout

    async def fetch_latest(self, today: Optional[date] = None) -> Dict[str, MacroIndicatorCreate]:
        """Último valor disponible de cada variable. Las que fallan se omiten (no se inventan)."""
        today = today or date.today()
        out: Dict[str, MacroIndicatorCreate] = {}
        async with httpx.AsyncClient(timeout=self.timeout, headers=HEADERS) as client:
            for name, var_id in VARIABLES.items():
                try:
                    res = await client.get(URL.format(id=var_id), params={"limit": 40})
                    res.raise_for_status()
                    results = res.json().get("results") or []
                    detalle = results[0].get("detalle") if results else []
                    item = latest_on_or_before(detalle, today)
                    if item:
                        out[name] = MacroIndicatorCreate(
                            date=item["fecha"], name=name,
                            value=Decimal(str(item["valor"])), source="BCRA",
                        )
                except Exception as e:
                    logger.warning(f"BCRA: no se pudo obtener {name} (id {var_id}): {e}")
        return out

    async def fetch_series(self, name: str, since: date, until: date) -> List[Tuple[date, float]]:
        """Serie diaria de una variable entre dos fechas, en orden cronológico (hasta 3000 datos)."""
        async with httpx.AsyncClient(timeout=self.timeout, headers=HEADERS) as client:
            res = await client.get(URL.format(id=VARIABLES[name]), params={
                "desde": since.isoformat(), "hasta": until.isoformat(), "limit": 3000})
        res.raise_for_status()
        results = res.json().get("results") or []
        out: Dict[date, float] = {}
        for item in (results[0].get("detalle") if results else []) or []:
            try:
                out[date.fromisoformat(item["fecha"])] = float(item["valor"])
            except (KeyError, TypeError, ValueError):
                continue
        return sorted(out.items())
