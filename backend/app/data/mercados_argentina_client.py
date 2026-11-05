"""
Cronogramas de pago desde Mercados Argentina (https://mercadosargentina.com.ar).

Cada título tiene su ficha `/activos/<ticker>` con la tabla "Cronograma de Pagos"
(Fecha | Renta | Amortización | Total | Estado), por cada 100 VN, que incluye también los pagos
ya realizados: aquí se conservan solo los posteriores a la fecha de corte.

Uso: segunda / tercera fuente de flujos de los provinciales en dólares, para verificar por
consenso los cronogramas de CompararBonos y Bruno618, y para completar bonos que ninguna de
las otras publica (ej. San Juan 2035).

Política de uso: robots.txt permite las fichas; el sitio limita pedidos por IP para programas
automáticos. Se consulta una vez por día, de a una ficha por vez, con pausa entre pedidos.

Validaciones (si alguna falla, el bono se descarta con el motivo):
- Total = Renta + Amortización en cada fila.
- La suma de las amortizaciones futuras no supera 100 y el último pago amortiza capital.
- Moneda de pago explícita en la ficha.
"""

import asyncio
import logging
import re
from datetime import date
from typing import Dict, List, Optional, Tuple

import httpx

from backend.app.data.bruno618_client import ProvincialSchedule, ScheduleRow

logger = logging.getLogger(__name__)

BASE_URL = "https://mercadosargentina.com.ar/activos"
HEADERS = {"User-Agent": "bonistas-monitor/1.1 (uso personal)", "Accept": "text/html"}

# Provinciales en dólares a consultar. Clave: ticker usado en esta app (CompararBonos / BYMA);
# valor: ticker de la ficha en Mercados Argentina cuando difiere.
PROVINCIAL_TICKERS: Dict[str, str] = {
    "BA37D": "ba37d", "BB37D": "bb37d", "BC37D": "bc37d", "BDC33": "bdc33", "BDC36": "bdc36",
    "CO32": "co32", "CO35": "co35", "ERF25": "erf25", "ERM33": "erm33", "NDG34": "ndg34",
    "NDT25": "ndt25", "PMM29": "pmm29", "PUA36": "pua36", "PUL26": "pul26", "SFD34": "sfd34",
    "SJO35": "sj035",
}

# Especies en BYMA de bonos que CompararBonos no lista (pesos, MEP, cable)
BYMA_SPECIES: Dict[str, List[str]] = {
    "SJO35": ["SJO35", "SJO5D", "SJO5C"],
    "NDG34": ["NDG34", "NDG4D", "NDG4C"],
}

_ROW = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
_TD = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
_TAG = re.compile(r"<[^>]+>")
_DATE = re.compile(r"^(\d{2})/(\d{2})/(\d{4})$")
TOL = 0.02


class MercadosArgentinaError(Exception):
    pass


def _clean(text: str) -> str:
    return " ".join(_TAG.sub(" ", text).split())


def _num(text: str) -> float:
    t = _clean(text).replace(".", "").replace(",", ".")
    return float(t) if t else 0.0


def parse_schedule(ticker: str, html: str, after: date) -> ProvincialSchedule:
    """Cronograma con los pagos posteriores a `after`. Lanza MercadosArgentinaError si no es válido."""
    i = html.find("Cronograma de Pagos")
    if i < 0:
        raise MercadosArgentinaError(f"{ticker}: la ficha no publica cronograma de pagos")
    seg = html[i:]
    table = seg[seg.find("<table"): seg.find("</table>")]
    rows: List[Tuple[date, float, float, float]] = []
    for tr in _ROW.findall(table):
        tds = _TD.findall(tr)
        if len(tds) < 4:
            continue
        m = _DATE.match(_clean(tds[0]))
        if not m:
            continue
        try:
            d = date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
            rows.append((d, _num(tds[1]), _num(tds[2]), _num(tds[3])))
        except ValueError as e:
            raise MercadosArgentinaError(f"{ticker}: fila ilegible ({e})") from e
    if not rows:
        raise MercadosArgentinaError(f"{ticker}: no se encontró la tabla de flujos (¿cambió el formato?)")

    future = sorted(r for r in rows if r[0] > after)
    if not future:
        raise MercadosArgentinaError(f"{ticker}: sin pagos futuros")
    for d, renta, amort, total in future:
        if abs(renta + amort - total) > TOL:
            raise MercadosArgentinaError(f"{ticker}: total ≠ renta + amortización el {d}")
    remaining = sum(r[2] for r in future)
    if remaining > 100 + TOL or future[-1][2] <= 0:
        raise MercadosArgentinaError(f"{ticker}: amortizaciones inconsistentes (suman {remaining:.2f})")

    text = _clean(html)
    mm = re.search(r"Moneda de pago\s+(USD|ARS|D[oó]lares|Pesos)", text, re.I)
    if mm is None:
        raise MercadosArgentinaError(f"{ticker}: no se encontró la moneda de pago")
    currency = "ARS" if mm.group(1).upper() in ("ARS", "PESOS") else "USD"

    out: List[ScheduleRow] = []
    residual = remaining
    for d, renta, amort, total in future:
        residual -= amort
        out.append(ScheduleRow(d, renta, amort, total, round(max(residual, 0.0), 4)))
    return ProvincialSchedule(ticker=ticker, currency=currency, data_date=None, rows=out)


class MercadosArgentinaClient:
    def __init__(self, base_url: str = BASE_URL, timeout: float = 20.0, pause_seconds: float = 1.0):
        self.base_url = base_url
        self.timeout = timeout
        self.pause_seconds = pause_seconds

    async def fetch_raw(self, site_ticker: str) -> str:
        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True, headers=HEADERS) as client:
            resp = await client.get(f"{self.base_url}/{site_ticker}")
        if resp.status_code == 404:
            raise MercadosArgentinaError(f"{site_ticker}: la ficha no existe (404)")
        if resp.status_code == 429:
            raise MercadosArgentinaError(f"{site_ticker}: límite de pedidos del sitio (429)")
        resp.raise_for_status()
        return resp.text

    async def fetch_schedules(self, after: date, tickers: Optional[Dict[str, str]] = None
                              ) -> Tuple[Dict[str, ProvincialSchedule], Dict[str, str]]:
        ok: Dict[str, ProvincialSchedule] = {}
        errors: Dict[str, str] = {}
        for i, (t, site) in enumerate((tickers or PROVINCIAL_TICKERS).items()):
            if i and self.pause_seconds:
                await asyncio.sleep(self.pause_seconds)
            try:
                ok[t] = parse_schedule(t, await self.fetch_raw(site), after)
            except (MercadosArgentinaError, httpx.HTTPError) as e:
                errors[t] = str(e)[:200]
                logger.info(f"Mercados Argentina: {e}")
                if "429" in str(e):
                    break          # respetar el límite: no seguir insistiendo hoy
        return ok, errors
