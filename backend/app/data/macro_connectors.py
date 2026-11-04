"""
Conector macroeconómico: inflación mensual (IPC).

Solo devuelve datos REALES con su fecha y fuente. Si la consulta falla no se inventa un valor:
las estrategias usan sus propios valores por defecto y lo registran, pero nada ficticio se
persiste en la base como si fuera un dato de mercado.

Pendiente (etapa 2): CER, TAMAR y A3500 desde la API del BCRA.
"""

import httpx
import logging
from datetime import datetime
from decimal import Decimal
from typing import Dict, Optional
from backend.app.schemas.macro import MacroIndicatorCreate

logger = logging.getLogger(__name__)

INFLATION_URL = "https://api.argentinadatos.com/v1/finanzas/indices/inflacion"


class MacroDataConnector:
    def __init__(self, timeout: float = 8.0):
        self.timeout = timeout
        self.headers = {"User-Agent": "bonistas-monitor/1.1", "Accept": "application/json"}

    async def fetch_latest_inflation(self) -> Optional[MacroIndicatorCreate]:
        """Último dato de inflación mensual IPC (INDEC vía ArgentinaDatos), o None si no hay datos."""
        try:
            async with httpx.AsyncClient(timeout=self.timeout, headers=self.headers) as client:
                res = await client.get(INFLATION_URL)
                res.raise_for_status()
                data = res.json()
        except Exception as e:
            logger.warning(f"No se pudo consultar la API de inflación: {e}")
            return None

        if not data or not isinstance(data, list):
            return None
        last_item = data[-1]
        fecha_str = last_item.get("fecha")
        valor = last_item.get("valor")
        if not fecha_str or valor is None:
            return None
        return MacroIndicatorCreate(
            date=datetime.strptime(fecha_str, "%Y-%m-%d").date(),
            name="IPC",
            value=Decimal(str(valor)),
            source="INDEC / ArgentinaDatos",
        )

    async def fetch_macro_snapshot(self) -> Dict[str, MacroIndicatorCreate]:
        """Indicadores macro disponibles, por nombre. Solo incluye los que se obtuvieron de verdad."""
        result: Dict[str, MacroIndicatorCreate] = {}
        ipc = await self.fetch_latest_inflation()
        if ipc is not None:
            result["IPC"] = ipc
        return result
