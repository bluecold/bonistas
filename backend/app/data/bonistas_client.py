"""
Cliente HTTP para el consumo de datos de Bonistas.com.
Permite obtener cotizaciones en tiempo real (CI y 24hs), tipos de cambio financieros implícitos y curvas de rendimiento.
"""

import httpx
import logging
from typing import List, Dict, Any, Optional
from backend.app.config import settings

logger = logging.getLogger(__name__)

class BonistasClient:
    def __init__(self, base_url: Optional[str] = None, timeout: float = 12.0):
        self.base_url = base_url or settings.BONISTAS_BASE_URL
        self.timeout = timeout
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
        }

    async def fetch_bonds(self) -> List[Dict[str, Any]]:
        """Obtiene la lista completa de cotizaciones de bonos."""
        url = f"{self.base_url}/api/bonds"
        try:
            async with httpx.AsyncClient(timeout=self.timeout, headers=self.headers, follow_redirects=True) as client:
                response = await client.get(url)
                response.raise_for_status()
                data = response.json()
                if isinstance(data, list):
                    logger.info(f"Obtenidos {len(data)} registros de bonos desde {url}")
                    return data
                return []
        except Exception as e:
            logger.error(f"Error al consultar {url}: {e}")
            raise

    async def fetch_fx(self) -> List[Dict[str, Any]]:
        """Obtiene la tabla de tipos de cambio implícitos (Pesos, MEP, Cable) para bonos soberanos."""
        url = f"{self.base_url}/api/fx/fx"
        try:
            async with httpx.AsyncClient(timeout=self.timeout, headers=self.headers, follow_redirects=True) as client:
                response = await client.get(url)
                response.raise_for_status()
                data = response.json()
                if isinstance(data, list):
                    logger.info(f"Obtenidos {len(data)} registros de FX desde {url}")
                    return data
                return []
        except Exception as e:
            logger.error(f"Error al consultar {url}: {e}")
            raise

    async def fetch_curves(self) -> Dict[str, Any]:
        """Obtiene las curvas de rendimiento parametrizadas por familia de bonos."""
        url = f"{self.base_url}/api/curves"
        try:
            async with httpx.AsyncClient(timeout=self.timeout, headers=self.headers, follow_redirects=True) as client:
                response = await client.get(url)
                response.raise_for_status()
                data = response.json()
                if isinstance(data, dict):
                    logger.info(f"Obtenidas curvas de rendimiento desde {url}")
                    return data
                return {}
        except Exception as e:
            logger.error(f"Error al consultar {url}: {e}")
            raise

