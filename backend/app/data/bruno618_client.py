"""
Cronogramas de pago de bonos provinciales desde Bruno618 (https://bruno618.com).

Uso: respaldo de CompararBonos, que no publica los flujos de la mayoría de los provinciales.
Cada bono tiene su página `/herramientas/flujo-de-fondos-renta-fija/<ticker>` con una tabla
renderizada en el servidor: Fecha | Renta | Amortización | Total | Residual, por cada 100 VN
de valor nominal original y solo con los pagos futuros.

Política de uso: robots.txt permite /herramientas. Se consulta una vez por día (con la
actualización de referencia), de a una página por vez y con una pausa entre pedidos.

Las fichas aclaran que el cronograma es proyectado a partir de las condiciones de emisión;
para tasa variable o ajuste (CER, dollar linked) los montos son estimados, por eso aquí solo
se usan bonos provinciales en dólares.

Validaciones (si alguna falla, el bono se descarta y se informa el motivo):
- Total = Renta + Amortización en cada fila.
- Residual encadenado: residual anterior − amortización = residual de la fila.
- El último residual es 0 (el bono se amortiza por completo).
"""

import asyncio
import logging
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Dict, List, Optional, Tuple

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://bruno618.com/herramientas/flujo-de-fondos-renta-fija"
HEADERS = {"User-Agent": "bonistas-monitor/1.1 (uso personal)", "Accept": "text/html"}

# Provinciales que publica Bruno618 (sección "Argentina — Subsoberanos / Provinciales")
PROVINCIAL_TICKERS = [
    "BA37D", "BB37D", "BC37D", "BDC33", "BDC36", "BP28", "BPLD", "BPLE", "CO27D",
    "CO32", "CO35", "ERF25", "ERM33", "NDT25", "PMM29", "PUA36", "PUL26", "SFD34",
]

_ROW = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
_TIME = re.compile(r'<time[^>]*dateTime="(\d{4}-\d{2}-\d{2})"', re.I)
_TD = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
_TAG = re.compile(r"<[^>]+>")
_DATA_DATE = re.compile(r"Datos al\s*(?:<!--.*?-->)?\s*(?:<[^>]+>\s*)*(\d{2}/\d{2}/\d{4})", re.S)

TOL = 0.02


class Bruno618Error(Exception):
    pass


@dataclass
class ScheduleRow:
    date: date
    coupon: float
    amortization: float
    total: float
    residual: float


@dataclass
class ProvincialSchedule:
    ticker: str
    currency: str                    # 'USD' o 'ARS'
    data_date: Optional[str]         # "Datos al" de la ficha (dd/mm/aaaa)
    rows: List[ScheduleRow] = field(default_factory=list)

    @property
    def flows(self) -> List[Tuple[date, float]]:
        return [(r.date, r.total) for r in self.rows]


def _num(text: str) -> float:
    t = _TAG.sub("", text).strip().replace(".", "").replace(",", ".")
    return float(t)


def parse_schedule(ticker: str, html: str) -> ProvincialSchedule:
    """Lee la tabla de la ficha. Lanza Bruno618Error si no hay tabla o no pasa las validaciones."""
    rows: List[ScheduleRow] = []
    table = html[html.find("<tbody"): html.find("</tbody>")] if "<tbody" in html else ""
    for tr in _ROW.findall(table):
        m = _TIME.search(tr)
        tds = _TD.findall(tr)
        if not m or len(tds) < 5:
            continue
        try:
            rows.append(ScheduleRow(date.fromisoformat(m.group(1)), _num(tds[1]), _num(tds[2]),
                                    _num(tds[3]), _num(tds[4])))
        except ValueError as e:
            raise Bruno618Error(f"{ticker}: número ilegible en la tabla ({e})") from e
    if not rows:
        raise Bruno618Error(f"{ticker}: no se encontró la tabla de flujos (¿cambió el formato?)")

    rows.sort(key=lambda r: r.date)
    prev = rows[0].residual + rows[0].amortization
    for r in rows:
        if abs(r.coupon + r.amortization - r.total) > TOL:
            raise Bruno618Error(f"{ticker}: total ≠ renta + amortización el {r.date}")
        if abs(prev - r.amortization - r.residual) > TOL:
            raise Bruno618Error(f"{ticker}: residual inconsistente el {r.date}")
        prev = r.residual
    if rows[-1].residual > TOL:
        raise Bruno618Error(f"{ticker}: el cronograma no amortiza el 100% (residual final {rows[-1].residual})")

    text = " ".join(_TAG.sub(" ", html).split())
    m = re.search(r"Moneda de pago\s+(D[oó]lares|Pesos)", text, re.I)
    if m is None:
        raise Bruno618Error(f"{ticker}: no se encontró la moneda de pago (¿cambió el formato?)")
    currency = "USD" if m.group(1).lower().startswith("d") else "ARS"
    dm = _DATA_DATE.search(html)
    return ProvincialSchedule(ticker=ticker, currency=currency, data_date=dm.group(1) if dm else None, rows=rows)


class Bruno618Client:
    def __init__(self, base_url: str = BASE_URL, timeout: float = 20.0, pause_seconds: float = 0.7):
        self.base_url = base_url
        self.timeout = timeout
        self.pause_seconds = pause_seconds

    async def fetch_raw(self, ticker: str) -> str:
        url = f"{self.base_url}/{ticker.lower()}"
        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True, headers=HEADERS) as client:
            resp = await client.get(url)
        if resp.status_code == 404:
            raise Bruno618Error(f"{ticker}: la ficha ya no existe (404)")
        resp.raise_for_status()
        return resp.text

    async def fetch_schedules(self, tickers: Optional[List[str]] = None
                              ) -> Tuple[Dict[str, ProvincialSchedule], Dict[str, str]]:
        """Devuelve (cronogramas válidos, errores por ticker). Un bono con error no frena al resto."""
        ok: Dict[str, ProvincialSchedule] = {}
        errors: Dict[str, str] = {}
        for i, t in enumerate(tickers or PROVINCIAL_TICKERS):
            if i and self.pause_seconds:
                await asyncio.sleep(self.pause_seconds)
            try:
                ok[t] = parse_schedule(t, await self.fetch_raw(t))
            except (Bruno618Error, httpx.HTTPError) as e:
                errors[t] = str(e)[:200]
                logger.warning(f"Bruno618: {e}")
        return ok, errors
