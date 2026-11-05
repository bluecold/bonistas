"""
Feriados de mercado desde MAE Market Data (https://api.marketdata.mae.com.ar/api/mercado/feriados).

Devuelve los próximos feriados con su país ("ar" = Argentina, "us" = Estados Unidos), el
nombre y la fecha como texto SIN año ("9 de noviembre"). El año se infiere: la lista es de
feriados próximos, así que una fecha que ya pasó este año corresponde al año siguiente.

- Feriados en Argentina: no hay rueda ni liquidación (afectan 24hs, caución y corte de cupón).
- Feriados en EE.UU.: hay rueda local, pero con poco volumen en activos ligados al exterior
  (más relevante para CEDEARs que para bonos). Se informan, no cambian el calendario.
"""

import logging
import re
from dataclasses import dataclass
from datetime import date
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

URL = "https://api.marketdata.mae.com.ar/api/mercado/feriados"
HEADERS = {"User-Agent": "bonistas-monitor/1.1 (uso personal)", "Accept": "application/json"}

MONTHS = {"enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6, "julio": 7,
          "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12}
_TEXT = re.compile(r"^\s*(\d{1,2})\s+de\s+([a-záéíóú]+)\s*$", re.I)


@dataclass(frozen=True)
class Holiday:
    day: date
    country: str          # 'AR' | 'US'
    name: str


def infer_date(text: str, today: date) -> Optional[date]:
    m = _TEXT.match(text or "")
    if not m:
        return None
    month = MONTHS.get(m.group(2).lower())
    if month is None:
        return None
    day = int(m.group(1))
    for year in (today.year, today.year + 1):
        try:
            d = date(year, month, day)
        except ValueError:
            return None
        if d >= today:
            return d
    return None


def parse_holidays(raw: List[Dict[str, Any]], today: date) -> List[Holiday]:
    out: List[Holiday] = []
    for item in raw or []:
        if not isinstance(item, dict):
            continue
        country = str(item.get("country", "")).strip().upper()
        d = infer_date(str(item.get("date_text", "")), today)
        if country not in ("AR", "US") or d is None:
            continue
        out.append(Holiday(d, country, str(item.get("tooltip_title_holiday", "")).strip()[:120]))
    return out


class MaeClient:
    def __init__(self, url: str = URL, timeout: float = 15.0):
        self.url = url
        self.timeout = timeout

    async def fetch_raw(self) -> List[Dict[str, Any]]:
        async with httpx.AsyncClient(timeout=self.timeout, headers=HEADERS) as client:
            resp = await client.get(self.url)
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, list):
            raise ValueError("Respuesta de feriados MAE inesperada (no es una lista)")
        return data

    async def fetch_holidays(self, today: date) -> List[Holiday]:
        return parse_holidays(await self.fetch_raw(), today)
