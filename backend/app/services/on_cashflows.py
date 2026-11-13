"""
Flujos de fondos de obligaciones negociables.

Fuente principal: Bull Market (mismo endpoint que los bonos:
POST /Clients/FixedIncome/GetProductsCashflowTablesAndSum), con la sesión del trader.
Respaldo sin sesión (o si Bull Market no tiene la ON): el calendario público de próximos pagos
de bonistas.com. Cada cronograma lleva su origen en `source` (BULLMARKET / BONISTAS).

Se piden a demanda, cuando se abre la ficha de una ON, y se guardan en memoria hasta el día
siguiente. Un cronograma de bonistas.com se reemplaza por el de Bull Market cuando hay sesión. No se guardan en la referencia de bonos a propósito: el motor de
arbitraje no opera ON y un cronograma ahí lo habilitaría a generar señales.
"""

import logging
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

from backend.app.data import bullmarket_client as bmc
from backend.app.data.bonistas_payments_client import BonistasPaymentsCache, lookup as bonistas_lookup
from backend.app.services.bullmarket_session import BullMarketSession

logger = logging.getLogger(__name__)


class OnCashflowUnavailable(Exception):
    """No se pudo obtener el cronograma (sin sesión, sesión vencida, error de red o sin datos)."""


class OnCashflowService:
    def __init__(self, session: BullMarketSession, bonistas: Optional[BonistasPaymentsCache] = None):
        self.session = session
        self.bonistas = bonistas                  # None = sin respaldo (solo Bull Market)
        self._cache: Dict[str, Tuple[date, Any]] = {}
        self.prefetched_day: Optional[date] = None

    def _cookie(self) -> Optional[str]:
        return (self.session.get_cookie() if self.session.status == "ACTIVA" else None) or None

    def _cached(self, t: str, today: date, any_source: bool) -> Any:
        """Cronograma del día en cache; con `any_source=False` solo vale el de Bull Market."""
        hit = self._cache.get(t)
        if hit and hit[0] == today and (any_source or source_of(hit[1]) == "BULLMARKET"):
            return hit[1]
        return None

    async def _from_bonistas(self, t: str, today: date) -> Any:
        if self.bonistas is None:
            return None
        return bonistas_lookup(await self.bonistas.get(today), t)

    async def get(self, ticker: str, today: Optional[date] = None) -> Any:
        """Cronograma (pagos posteriores a hoy, por 100 VN) o OnCashflowUnavailable."""
        today = today or date.today()
        t = ticker.strip().upper()
        cookie = self._cookie()
        hit = self._cached(t, today, any_source=not cookie)
        if hit is not None:
            return hit

        problem: Optional[OnCashflowUnavailable] = None
        if cookie:
            try:
                ok, errors = await bmc.fetch_cashflows(cookie, [t], after=today)
                sch = ok.get(t)
                if sch is not None:
                    self._cache[t] = (today, sch)
                    return sch
                detail = errors.get(t)
                problem = OnCashflowUnavailable(
                    f"Bull Market no tiene pagos futuros para {t}" + (f" ({detail})." if detail else "."))
            except bmc.SessionExpiredError as e:
                problem = OnCashflowUnavailable(
                    "La sesión de Bull Market venció: volvé a iniciarla para ver los flujos.")
                problem.__cause__ = e
            except bmc.BullMarketError as e:
                logger.warning(f"Flujos ON {t}: {e}")
                problem = OnCashflowUnavailable(f"Bull Market no respondió ({e}).")
                problem.__cause__ = e

        sch = self._cached(t, today, any_source=True) or await self._from_bonistas(t, today)
        if sch is not None:
            self._cache[t] = (today, sch)
            return sch
        raise problem or OnCashflowUnavailable(
            f"bonistas.com no publica los pagos de {t} y Bull Market requiere la sesión: "
            "iniciá la sesión en el dashboard para verlos.")

    async def prefetch(self, tickers: List[str], today: Optional[date] = None,
                       mark_day: bool = True) -> Dict[str, Any]:
        """
        Cronogramas de muchas ON de una vez, para el valor relativo. Con sesión: Bull Market (el
        cliente agrupa de a 40 por pedido), una vez por día. Las que Bull Market no devuelve, o
        todas si no hay sesión, se completan con bonistas.com. Las que ya están en el cache del
        día no se vuelven a pedir.

        `mark_day=False`: pedido parcial (las ON de un emisor, para la ficha); no cuenta como la
        descarga diaria de todas las ON.
        """
        today = today or date.today()
        wanted = [t.strip().upper() for t in tickers]
        cookie = self._cookie()
        missing = [t for t in wanted if self._cached(t, today, any_source=False) is None]
        if missing and cookie:
            ok, errors = await bmc.fetch_cashflows(cookie, missing, after=today)
            for t, sch in ok.items():
                self._cache[t] = (today, sch)
            if mark_day:
                self.prefetched_day = today
            logger.info(f"Cronogramas de ON: {len(ok)} de {len(missing)} ({len(errors)} con errores)")
        pending = [t for t in wanted if self._cached(t, today, any_source=True) is None]
        if pending and self.bonistas is not None:
            published = await self.bonistas.get(today)
            filled = 0
            for t in pending:
                sch = bonistas_lookup(published, t)
                if sch is not None:
                    self._cache[t] = (today, sch)
                    filled += 1
            if filled:
                logger.info(f"Cronogramas de ON desde bonistas.com: {filled} de {len(pending)}")
        return self.schedules(today)

    def schedules(self, today: Optional[date] = None) -> Dict[str, Any]:
        """Cronogramas vigentes del día (los de días anteriores pueden incluir pagos ya hechos)."""
        today = today or date.today()
        return {t: sch for t, (d, sch) in self._cache.items() if d == today}


def source_of(schedule: Any) -> str:
    """Origen de un cronograma de ON: BULLMARKET (por defecto) o BONISTAS."""
    return getattr(schedule, "source", None) or "BULLMARKET"


def on_base_tickers(db) -> List[str]:
    """
    Ticker de cada ON para pedir su cronograma: la especie en pesos (YM34O). Las especies D/C
    solo se piden si no está la de pesos (todas comparten el mismo cronograma).
    """
    from sqlalchemy import select
    from backend.app.db.models import Bond
    tickers = set(db.execute(select(Bond.ticker).where(Bond.bond_type == "ON")).scalars())
    return sorted(t for t in tickers if not (t[-1:] in ("D", "C") and t[:-1] + "O" in tickers))
