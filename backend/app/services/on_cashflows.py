"""
Flujos de fondos de obligaciones negociables desde Bull Market (mismo endpoint que los bonos:
POST /Clients/FixedIncome/GetProductsCashflowTablesAndSum).

Se piden a demanda, cuando se abre la ficha de una ON, con la sesión del trader, y se guardan en
memoria hasta el día siguiente. No se guardan en la referencia de bonos a propósito: el motor de
arbitraje no opera ON y un cronograma ahí lo habilitaría a generar señales.
"""

import logging
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

from backend.app.data import bullmarket_client as bmc
from backend.app.services.bullmarket_session import BullMarketSession

logger = logging.getLogger(__name__)


class OnCashflowUnavailable(Exception):
    """No se pudo obtener el cronograma (sin sesión, sesión vencida, error de red o sin datos)."""


class OnCashflowService:
    def __init__(self, session: BullMarketSession):
        self.session = session
        self._cache: Dict[str, Tuple[date, Any]] = {}
        self.prefetched_day: Optional[date] = None

    async def get(self, ticker: str, today: Optional[date] = None) -> Any:
        """Cronograma (pagos posteriores a hoy, por 100 VN) o OnCashflowUnavailable."""
        today = today or date.today()
        t = ticker.strip().upper()
        hit = self._cache.get(t)
        if hit and hit[0] == today:
            return hit[1]
        cookie = self.session.get_cookie() if self.session.status == "ACTIVA" else None
        if not cookie:
            raise OnCashflowUnavailable(
                "Los flujos de las ON salen de Bull Market: iniciá la sesión en el dashboard para verlos.")
        try:
            ok, errors = await bmc.fetch_cashflows(cookie, [t], after=today)
        except bmc.SessionExpiredError as e:
            raise OnCashflowUnavailable("La sesión de Bull Market venció: volvé a iniciarla para ver los flujos.") from e
        except bmc.BullMarketError as e:
            logger.warning(f"Flujos ON {t}: {e}")
            raise OnCashflowUnavailable(f"Bull Market no respondió ({e}).") from e
        sch = ok.get(t)
        if sch is None:
            detail = errors.get(t)
            raise OnCashflowUnavailable(
                f"Bull Market no tiene pagos futuros para {t}" + (f" ({detail})." if detail else "."))
        self._cache[t] = (today, sch)
        return sch

    async def prefetch(self, tickers: List[str], today: Optional[date] = None) -> Dict[str, Any]:
        """
        Cronogramas de muchas ON de una vez (el cliente agrupa de a 40 por pedido). Se usa una vez
        por día para el valor relativo; las que ya están en el cache del día no se vuelven a pedir.
        """
        today = today or date.today()
        missing = [t.strip().upper() for t in tickers
                   if not (self._cache.get(t.strip().upper()) or (None,))[0] == today]
        cookie = self.session.get_cookie() if self.session.status == "ACTIVA" else None
        if missing and cookie:
            ok, errors = await bmc.fetch_cashflows(cookie, missing, after=today)
            for t, sch in ok.items():
                self._cache[t] = (today, sch)
            self.prefetched_day = today
            logger.info(f"Cronogramas de ON: {len(ok)} de {len(missing)} ({len(errors)} con errores)")
        return self.schedules(today)

    def schedules(self, today: Optional[date] = None) -> Dict[str, Any]:
        """Cronogramas vigentes del día (los de días anteriores pueden incluir pagos ya hechos)."""
        today = today or date.today()
        return {t: sch for t, (d, sch) in self._cache.items() if d == today}


def on_base_tickers(db) -> List[str]:
    """
    Ticker de cada ON para pedir su cronograma: la especie en pesos (YM34O). Las especies D/C
    solo se piden si no está la de pesos (todas comparten el mismo cronograma).
    """
    from sqlalchemy import select
    from backend.app.db.models import Bond
    tickers = set(db.execute(select(Bond.ticker).where(Bond.bond_type == "ON")).scalars())
    return sorted(t for t in tickers if not (t[-1:] in ("D", "C") and t[:-1] + "O" in tickers))
