"""
Calendario de próximos pagos de bonistas.com (https://bonistas.com/proximos-pagos).

Una sola página pública, sin sesión, con todos los pagos futuros (renta, amortización, total y
saldo por 100 VN) de soberanos, letras, Bopreales y más de cien obligaciones negociables. Los
datos vienen embebidos en el JSON `__NEXT_DATA__` de la página.

Uso en la app:
- Respaldo de los cronogramas de ON cuando no hay sesión de Bull Market.
- Pagos con corte inminente que CompararBonos ya no lista (caso TX28), también sin sesión.

Notas del formato (verificado el 13/11/2026):
- `saldo` es el capital ANTES del pago: residual después del pago = saldo − principal.
- `moneda`: "ARS", "USD", "USD MEP" o "USD CABLE". Para CER, los montos están en pesos ajustados
  por el CER vigente (estimación: cambia todos los días).
- Las especies en dólares figuran con el ticker D (AL30D, YMCXD); las de pesos, con el ticker base.
- Los símbolos con "_" (TXMD8_CER) son la otra pata de un bono dual: otro escenario del mismo
  instrumento, se descartan.

Validaciones (si alguna falla, el bono se descarta y se informa el motivo):
- Total = renta + amortización en cada fila.
- Montos no negativos y residual no negativo.
"""

import json
import logging
import re
import time
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

import httpx

from backend.app.config import settings
from backend.app.data.bruno618_client import ProvincialSchedule, ScheduleRow

logger = logging.getLogger(__name__)

SOURCE = "BONISTAS"
PATH = "/proximos-pagos"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Accept": "text/html",
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
}
TOL = 0.02
RETRY_SECONDS = 600

_NEXT_DATA = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)
_PAYMENT_CURRENCY = {"ARS": "ARS", "USD MEP": "MEP", "USD CABLE": "CCL"}


class BonistasPaymentsError(Exception):
    pass


def parse_payments(html: str, after: date) -> Tuple[Dict[str, ProvincialSchedule], Dict[str, str]]:
    """
    Devuelve (cronogramas por símbolo con los pagos posteriores a `after`, errores por símbolo).
    Lanza BonistasPaymentsError si la página no trae el listado (¿cambió el formato?).
    """
    m = _NEXT_DATA.search(html)
    if m is None:
        raise BonistasPaymentsError("no se encontró __NEXT_DATA__ en la página (¿cambió el formato?)")
    try:
        payments = json.loads(m.group(1))["props"]["pageProps"]["initialPayments"]
    except (ValueError, KeyError, TypeError) as e:
        raise BonistasPaymentsError(f"no se encontró el listado de pagos ({e})") from e
    if not isinstance(payments, list) or not payments:
        raise BonistasPaymentsError("el listado de pagos está vacío")

    by_symbol: Dict[str, List[Dict[str, Any]]] = {}
    for p in payments:
        sym = str(p.get("symbol") or "").strip().upper()
        if sym and "_" not in sym:
            by_symbol.setdefault(sym, []).append(p)

    ok: Dict[str, ProvincialSchedule] = {}
    errors: Dict[str, str] = {}
    for sym, items in by_symbol.items():
        try:
            monedas = {str(p.get("moneda") or "").strip().upper() for p in items}
            if len(monedas) != 1:
                raise BonistasPaymentsError(f"monedas mezcladas {sorted(monedas)}")
            moneda = monedas.pop()
            if moneda != "ARS" and not moneda.startswith("USD"):
                raise BonistasPaymentsError(f"moneda desconocida '{moneda}'")
            rows: List[ScheduleRow] = []
            for p in items:
                day = date.fromisoformat(str(p["fecha"])[:10])
                coupon, amort, total = float(p["cupon"]), float(p["principal"]), float(p["total"])
                residual = float(p["saldo"]) - amort
                if min(coupon, amort, total) < 0 or residual < -TOL:
                    raise BonistasPaymentsError(f"monto negativo el {day}")
                if abs(coupon + amort - total) > TOL:
                    raise BonistasPaymentsError(f"total ≠ renta + amortización el {day}")
                rows.append(ScheduleRow(day, coupon, amort, total, max(residual, 0.0)))
        except (BonistasPaymentsError, KeyError, TypeError, ValueError) as e:
            errors[sym] = str(e)[:200]
            continue
        future = sorted((r for r in rows if r.date > after), key=lambda r: r.date)
        if not future:
            continue
        sch = ProvincialSchedule(ticker=sym, currency="ARS" if moneda == "ARS" else "USD",
                                 data_date=None, rows=future)
        # Datos extra, fuera del dataclass (igual que los cronogramas de Bull Market)
        sch.payment_currency = _PAYMENT_CURRENCY.get(moneda)
        sch.source = SOURCE
        ok[sym] = sch
    return ok, errors


class BonistasPaymentsClient:
    def __init__(self, base_url: Optional[str] = None, timeout: float = 20.0):
        self.base_url = base_url or settings.BONISTAS_BASE_URL
        self.timeout = timeout

    async def fetch_raw(self) -> str:
        async with httpx.AsyncClient(timeout=self.timeout, headers=HEADERS, follow_redirects=True) as client:
            resp = await client.get(f"{self.base_url}{PATH}")
            resp.raise_for_status()
            return resp.text

    async def fetch_schedules(self, after: date) -> Tuple[Dict[str, ProvincialSchedule], Dict[str, str]]:
        return parse_payments(await self.fetch_raw(), after)


class BonistasPaymentsCache:
    """
    Calendario del día en memoria: la página se pide una vez por día. Si falla, se reintenta
    recién a los RETRY_SECONDS (nunca en cada ciclo de 60 s) y mientras tanto no hay datos.
    """

    def __init__(self, client: Optional[BonistasPaymentsClient] = None):
        self.client = client or BonistasPaymentsClient()
        self._day: Optional[date] = None
        self._schedules: Dict[str, ProvincialSchedule] = {}
        self._failed_at: float = 0.0

    async def get(self, today: Optional[date] = None) -> Dict[str, ProvincialSchedule]:
        """Cronogramas del día ({} si la fuente no responde: nunca lanza)."""
        from backend.app.services.source_health import source_health
        today = today or date.today()
        if self._day == today:
            return self._schedules
        if self._failed_at and time.monotonic() - self._failed_at < RETRY_SECONDS:
            return {}
        try:
            schedules, errors = await self.client.fetch_schedules(after=today)
        except Exception as e:
            self._failed_at = time.monotonic()
            source_health.failure("BONISTAS_PAGOS", e)
            logger.warning(f"Próximos pagos de bonistas.com: {e}")
            return {}
        self._day, self._schedules, self._failed_at = today, schedules, 0.0
        source_health.success("BONISTAS_PAGOS", schedules=len(schedules), errors=len(errors))
        if errors:
            logger.warning(f"Próximos pagos de bonistas.com: {len(errors)} bonos descartados: {errors}")
        logger.info(f"Próximos pagos de bonistas.com: {len(schedules)} cronogramas")
        return schedules


def lookup(schedules: Dict[str, ProvincialSchedule], ticker: str) -> Optional[ProvincialSchedule]:
    """
    Cronograma de un ticker o de su especie D (bonistas publica las ON y los bonos en dólares
    con el ticker D: YMCXO / YMCXC -> YMCXD).
    """
    t = ticker.strip().upper()
    if t in schedules:
        return schedules[t]
    if t[-1:] in ("O", "C") and t[:-1] + "D" in schedules:
        return schedules[t[:-1] + "D"]
    return None


bonistas_payments = BonistasPaymentsCache()
