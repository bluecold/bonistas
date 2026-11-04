"""
Cliente HTTP para DolarAPI (https://dolarapi.com).
Provee cotizaciones en tiempo real del Dólar Oficial, Mayorista A3500, Dólar Bolsa (MEP), CCL y Blue.
"""

import httpx
import logging
from typing import List, Dict, Any, Optional
from backend.app.config import settings

logger = logging.getLogger(__name__)

class DolarApiClient:
    def __init__(self, base_url: Optional[str] = None, timeout: float = 8.0):
        self.base_url = base_url or settings.DOLAR_API_BASE_URL
        self.timeout = timeout
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json",
        }

    async def fetch_all_dolares(self) -> List[Dict[str, Any]]:
        """Obtiene todas las cotizaciones de dólares disponibles."""
        url = f"{self.base_url}/dolares"
        try:
            async with httpx.AsyncClient(timeout=self.timeout, headers=self.headers) as client:
                response = await client.get(url)
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.error(f"Error al consultar DolarAPI ({url}): {e}")
            raise

    async def get_rates_dict(self) -> Dict[str, float]:
        """Devuelve un diccionario simple {'oficial': 1570.0, 'bolsa': 1577.3, 'ccl': 1676.2, 'mayorista': 1547.0, 'blue': 1565.0}."""
        data = await self.fetch_all_dolares()
        result = {}
        for item in data:
            casa = item.get("casa", "").lower()
            venta = item.get("venta") or item.get("compra") or 0.0
            if casa:
                result[casa] = float(venta)
        return result

