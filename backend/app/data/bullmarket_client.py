"""
Cliente de cotizaciones en tiempo real de Bull Market Brokers (cuenta del propio trader).

Usa el mismo endpoint que la pantalla de cotizaciones de la plataforma web:
    GET https://inversiones.bullmarket.com.ar/Clients/MarketPrices/GetStockPrices
        ?term=1|2&index=bonos&hideWithoutPrices=true&sortColumn=ticker&isAscending=true...

Requiere la cookie de una sesión iniciada en el navegador (dura ~30 min). Este módulo NO
inicia sesión ni maneja usuario/contraseña: la cookie la pega el trader en el dashboard y se
guarda fuera del código (ver services/bullmarket_session.py).

Convenciones de la respuesta:
- term: "1" = Contado Inmediato (CI), "2" = 24hs.
- currency: "ARS" = pesos, "USD" = dólar MEP (especie D), "CCL" = dólar cable (especie C).
- stockOffer.bidTop / askTop: hasta 5 niveles {price, quantity, position}; precio por 100 VN.
- stockState: price (último), close (cierre anterior), totalNominalValue, totalAmount, operations.

`index` queda parametrizado para versiones futuras (merval, cedears, obligaciones...).
"""

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import httpx

from backend.app.data.byma_client import BookRow, species_base

logger = logging.getLogger(__name__)

BASE_URL = "https://inversiones.bullmarket.com.ar"
PRICES_PATH = "/Clients/MarketPrices/GetStockPrices"

TERM_TO_SETTLEMENT = {"1": "CI", "2": "24HS"}
SETTLEMENT_TO_TERM = {v: k for k, v in TERM_TO_SETTLEMENT.items()}
CURRENCY_MAP = {"ARS": "ARS", "USD": "MEP", "CCL": "CCL", "EXT": "CCL"}

# Los mismos encabezados que envía la página de cotizaciones (petición XHR del navegador)
HEADERS = {
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "es,es-419;q=0.9,en;q=0.8",
    "Referer": f"{BASE_URL}/Cotizaciones/bonos",
    "X-Requested-With": "XMLHttpRequest",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"),
}


class BullMarketError(Exception):
    """Error transitorio (red, 5xx, respuesta inesperada)."""


class SessionExpiredError(BullMarketError):
    """La cookie ya no es válida: hay que volver a iniciar sesión en el navegador."""


def _num(v: Any) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f > 0 else None


def _levels(raw: Any) -> List[Tuple[float, float]]:
    out: List[Tuple[float, float]] = []
    if not isinstance(raw, list):
        return out
    for lv in sorted((x for x in raw if isinstance(x, dict)), key=lambda x: x.get("position") or 0):
        p, q = _num(lv.get("price")), _num(lv.get("quantity"))
        if p is not None:
            out.append((p, q or 0.0))
    return out


def _trade_time(v: Any) -> Optional[str]:
    s = str(v or "").strip()
    if len(s) == 6 and s.isdigit() and s != "000000":
        return f"{s[0:2]}:{s[2:4]}:{s[4:6]}"
    return None


def parse_stock_prices(raw_rows: List[Dict[str, Any]], term: Optional[str] = None) -> List[BookRow]:
    """Normaliza `result` de GetStockPrices a filas de libro con hasta 5 niveles de profundidad."""
    tickers = {str(r.get("ticker", "")).strip().upper() for r in raw_rows if isinstance(r, dict)}
    out: List[BookRow] = []
    for r in raw_rows:
        if not isinstance(r, dict):
            continue
        symbol = str(r.get("ticker", "")).strip().upper()
        currency = CURRENCY_MAP.get(str(r.get("currency", "")).upper())
        settlement = TERM_TO_SETTLEMENT.get(str(r.get("term") or term or ""))
        if not symbol or not currency or not settlement:
            continue
        offer = r.get("stockOffer") or {}
        state = r.get("stockState") or {}
        bids, asks = _levels(offer.get("bidTop")), _levels(offer.get("askTop"))
        ops = state.get("operations")
        out.append(BookRow(
            symbol=symbol,
            base_ticker=species_base(symbol, currency, tickers),
            currency=currency,
            settlement=settlement,
            bid=bids[0][0] if bids else None,
            bid_qty=bids[0][1] if bids else None,
            ask=asks[0][0] if asks else None,
            ask_qty=asks[0][1] if asks else None,
            last=_num(state.get("price")),
            prev_close=_num(state.get("close")),
            volume_nominal=_num(state.get("totalNominalValue")),
            volume_amount=_num(state.get("totalAmount")),
            trades=int(ops) if isinstance(ops, (int, float)) and ops > 0 else None,
            trade_time=_trade_time(r.get("emisionTime")),
            maturity_date=None,
            bids=bids,
            asks=asks,
        ))
    return out


def classify_response(status_code: int, content_type: str, body: str) -> None:
    """Lanza SessionExpiredError / BullMarketError según la respuesta. No hace nada si es JSON OK."""
    if status_code in (401, 403) or 300 <= status_code < 400:
        raise SessionExpiredError(f"Sesión de Bull Market vencida o inválida (HTTP {status_code}).")
    if status_code >= 400:
        raise BullMarketError(f"Bull Market respondió HTTP {status_code}.")
    text = body.lstrip()[:200].lower()
    if "html" in (content_type or "").lower() or text.startswith("<"):
        # La plataforma devuelve la página de login (HTML) cuando la sesión ya no es válida
        raise SessionExpiredError("Bull Market devolvió una página HTML (login): sesión vencida.")


@dataclass
class BullMarketClient:
    base_url: str = BASE_URL
    timeout: float = 15.0

    def _url(self, term: str, index: str, bond_type: str = "") -> str:
        return (f"{self.base_url}{PRICES_PATH}?term={term}&hideWithoutPrices=true&index={index}"
                f"&sortColumn=ticker&isAscending=true&bondRate=&bondType={bond_type}&productSectorId=")

    async def fetch_raw(self, cookie: str, term: str, index: str = "bonos") -> List[Dict[str, Any]]:
        if not cookie:
            raise SessionExpiredError("No hay cookie de sesión de Bull Market configurada.")
        headers = dict(HEADERS, Cookie=cookie)
        try:
            async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=False) as client:
                resp = await client.get(self._url(term, index), headers=headers)
        except httpx.HTTPError as e:
            raise BullMarketError(f"Error de red con Bull Market: {e.__class__.__name__}") from e
        classify_response(resp.status_code, resp.headers.get("content-type", ""), resp.text)
        if not resp.text.strip():
            return []
        try:
            data = resp.json()
        except ValueError as e:
            raise SessionExpiredError("Respuesta de Bull Market no es JSON: probable sesión vencida.") from e
        if isinstance(data, dict) and isinstance(data.get("result"), list):
            return data["result"]
        if isinstance(data, list):
            return data
        raise BullMarketError("Respuesta de Bull Market sin el campo 'result'.")

    async def fetch_books(self, cookie: str, index: str = "bonos",
                          settlements: Tuple[str, ...] = ("CI", "24HS")) -> List[BookRow]:
        rows: List[BookRow] = []
        for st in settlements:
            term = SETTLEMENT_TO_TERM[st]
            rows += parse_stock_prices(await self.fetch_raw(cookie, term, index), term)
        return rows
