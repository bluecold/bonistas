"""
Cotizaciones históricas diarias desde Rava (https://www.rava.com/perfil/<especie>).

La ficha de cada especie ofrece la descarga "Cotizaciones históricas" en CSV, sin sesión
(robots.txt no la restringe): `GET /perfil/descarga-historicos/<especie>`, unos 5 años de ruedas
con columnas `especie,apertura,maximo,minimo,ultimo,fecha,volumen,cierre,timestamp,...`.

Se usa una vez por día para las bandas de los ratios entre bonos (especie D contra especie D).
"""

import asyncio
import csv
import io
import logging
from datetime import date
from typing import Dict, Iterable, List, Tuple

import httpx

logger = logging.getLogger(__name__)

URL = "https://www.rava.com/perfil/descarga-historicos/{symbol}"
HEADERS = {"User-Agent": "bonistas-monitor/1.1 (uso personal)", "Accept": "text/csv,*/*"}


def parse_history(text: str) -> List[Tuple[date, float]]:
    """[(fecha, cierre)] en orden cronológico. Ignora filas sin cierre o con fecha inválida."""
    out: Dict[date, float] = {}
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    for row in reader:
        try:
            day = date.fromisoformat((row.get("fecha") or "").strip())
            close = float(row.get("cierre") or 0)
        except ValueError:
            continue
        if close > 0:
            out[day] = close
    return sorted(out.items())


class RavaClient:
    def __init__(self, timeout: float = 20.0, pause_seconds: float = 1.5):
        self.timeout = timeout
        self.pause_seconds = pause_seconds

    async def fetch_text(self, symbol: str) -> str:
        async with httpx.AsyncClient(timeout=self.timeout, headers=HEADERS, follow_redirects=True) as client:
            resp = await client.get(URL.format(symbol=symbol))
        resp.raise_for_status()
        return resp.text

    async def fetch_histories(self, symbols: Iterable[str]) -> Tuple[Dict[str, List[Tuple[date, float]]], Dict[str, str]]:
        """Historia de cada especie, de a una y con pausa. Devuelve (historias, errores)."""
        histories: Dict[str, List[Tuple[date, float]]] = {}
        errors: Dict[str, str] = {}
        for i, symbol in enumerate(symbols):
            if i:
                await asyncio.sleep(self.pause_seconds)
            try:
                rows = parse_history(await self.fetch_text(symbol))
                if not rows:
                    raise ValueError("sin filas")
                histories[symbol] = rows
            except httpx.HTTPStatusError as e:
                errors[symbol] = f"HTTP {e.response.status_code}"
                if e.response.status_code == 429:       # el sitio pide frenar: no insistir
                    break
            except Exception as e:
                errors[symbol] = str(e)[:120]
        return histories, errors
