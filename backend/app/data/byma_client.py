"""
Cliente de BYMA Open Data (https://open.bymadata.com.ar).

Datos públicos con 20 minutos de demora ("abierto e ilimitado" según BYMA). Provee, por
especie y plazo, la mejor punta compradora/vendedora con cantidades, último precio, volumen
y hora de la última operación. También cauciones y el horario de mercado.

Convenciones de BYMA:
- settlementType: "1" = Contado Inmediato (CI), "2" = 24hs.
- denominationCcy: "ARS" = pesos, "USD" = dólar MEP (especie D), "EXT" = dólar cable (especie C).
"""

import logging
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Any, Dict, List, Optional, Tuple

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://open.bymadata.com.ar/vanoms-be-core/rest/api/bymadata/free"
HEADERS = {
    "User-Agent": "bonistas-monitor/1.1 (uso personal)",
    "Accept": "application/json",
    "Content-Type": "application/json",
}

SETTLEMENT_MAP = {"1": "CI", "2": "24HS"}
CURRENCY_MAP = {"ARS": "ARS", "USD": "MEP", "EXT": "CCL"}

# BOPREAL: la especie en pesos tiene un ticker distinto a la D/C (BPOA7 <-> BPA7D / BPA7C)
_BOPREAL_PESOS = {"BPA7": "BPOA7", "BPB7": "BPOB7", "BPC7": "BPOC7", "BPD7": "BPOD7",
                  "BPA8": "BPOA8", "BPB8": "BPOB8"}


def species_base(symbol: str, currency: str, known_symbols: Optional[set] = None) -> str:
    """
    Ticker base común a las tres especies de un mismo bono (pesos, D y C).
    AL30 / AL30D / AL30C -> AL30.  BPOA7 / BPA7D / BPA7C -> BPOA7.
    Solo se quita el sufijo final si la especie NO es en pesos (las de pesos ya son la base).
    """
    s = symbol.strip().upper()
    if currency == "ARS" or len(s) < 4 or s[-1] not in ("D", "C"):
        return s
    stem = s[:-1]
    if stem in _BOPREAL_PESOS:
        return _BOPREAL_PESOS[stem]
    if known_symbols is None or stem in known_symbols:
        return stem
    return s


def _num(v: Any) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f > 0 else None


@dataclass
class BookRow:
    symbol: str
    base_ticker: str
    currency: str          # ARS / MEP / CCL
    settlement: str        # CI / 24HS
    bid: Optional[float]
    bid_qty: Optional[float]
    ask: Optional[float]
    ask_qty: Optional[float]
    last: Optional[float]
    prev_close: Optional[float]
    volume_nominal: Optional[float]
    volume_amount: Optional[float]
    trades: Optional[int]
    trade_time: Optional[str]
    maturity_date: Optional[date]
    # Profundidad completa [(precio, cantidad), ...] cuando la fuente la publica (Bull Market: 5 niveles)
    bids: Optional[List[Tuple[float, float]]] = None
    asks: Optional[List[Tuple[float, float]]] = None
    name: Optional[str] = None     # descripción de la fuente (Bull Market: "Mirgor. Clase IV. ...")


def parse_bond_rows(raw_rows: List[Dict[str, Any]]) -> List[BookRow]:
    """Normaliza la respuesta de public-bonds a filas de libro."""
    symbols = {str(r.get("symbol", "")).strip().upper() for r in raw_rows}
    out: List[BookRow] = []
    for r in raw_rows:
        symbol = str(r.get("symbol", "")).strip().upper()
        settlement = SETTLEMENT_MAP.get(str(r.get("settlementType")))
        currency = CURRENCY_MAP.get(str(r.get("denominationCcy", "")).upper())
        if not symbol or not settlement or not currency:
            continue
        maturity = None
        if r.get("maturityDate"):
            try:
                maturity = date.fromisoformat(str(r["maturityDate"])[:10])
            except ValueError:
                maturity = None
        out.append(BookRow(
            symbol=symbol,
            base_ticker=species_base(symbol, currency, symbols),
            currency=currency,
            settlement=settlement,
            bid=_num(r.get("bidPrice")),
            bid_qty=_num(r.get("quantityBid")),
            ask=_num(r.get("offerPrice")),
            ask_qty=_num(r.get("quantityOffer")),
            last=_num(r.get("trade")),
            prev_close=_num(r.get("previousClosingPrice")),
            volume_nominal=_num(r.get("tradeVolume")),
            volume_amount=_num(r.get("volumeAmount")),
            trades=int(r["numberOfOrders"]) if r.get("numberOfOrders") else None,
            trade_time=str(r["tradeHour"]) if r.get("tradeHour") else None,
            maturity_date=maturity,
        ))
    return out


def pick_overnight_caucion(raw_rows: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """
    Caución en pesos al plazo más corto con operaciones (normalmente 1 día).
    Devuelve {"tna_pct", "days", "bid_pct", "ask_pct", "maturity"} con tasas en % TNA.
    """
    candidates = []
    for r in raw_rows:
        sym = str(r.get("symbol", ""))
        if not sym.startswith("PESOS-") or str(r.get("settlementType")) != "1":
            continue
        days = r.get("daysToMaturity")
        last = _num(r.get("trade")) or _num(r.get("vwap"))
        if not days or not last or not _num(r.get("tradeVolume")):
            continue
        candidates.append((int(days), r, last))
    if not candidates:
        return None
    days, r, last = min(candidates, key=lambda c: c[0])
    bid, ask = _num(r.get("bidPrice")), _num(r.get("offerPrice"))
    return {
        "tna_pct": round(last * 100.0, 4),
        "days": days,
        "bid_pct": round(bid * 100.0, 4) if bid else None,
        "ask_pct": round(ask * 100.0, 4) if ask else None,
        "maturity": str(r.get("maturityDate", ""))[:10] or None,
    }


@dataclass
class MarketTime:
    is_working_day: bool
    opening: time
    closing: time


class BymaClient:
    def __init__(self, base_url: str = BASE_URL, timeout: float = 20.0, max_pages: int = 20):
        self.base_url = base_url
        self.timeout = timeout
        self.max_pages = max_pages  # tope de seguridad (hoy son ~7 páginas)

    async def _post(self, client: httpx.AsyncClient, path: str, body: Dict[str, Any]) -> Any:
        res = await client.post(f"{self.base_url}/{path}", json=body)
        res.raise_for_status()
        return res.json()

    async def fetch_bond_books_raw(self) -> List[Dict[str, Any]]:
        """Todas las especies de bonos públicos, CI y 24hs (paginado)."""
        rows: List[Dict[str, Any]] = []
        async with httpx.AsyncClient(timeout=self.timeout, headers=HEADERS) as client:
            page, page_count = 1, 1
            while page <= min(page_count, self.max_pages):
                data = await self._post(client, "public-bonds",
                                        {"T2": False, "T1": True, "T0": True, "page_number": page})
                rows.extend(data.get("data") or [])
                page_count = int((data.get("content") or {}).get("page_count") or 1)
                page += 1
        logger.info(f"BYMA: {len(rows)} filas de bonos ({page - 1} páginas)")
        return rows

    async def fetch_bond_books(self) -> List[BookRow]:
        return parse_bond_rows(await self.fetch_bond_books_raw())

    async def fetch_cauciones_raw(self) -> List[Dict[str, Any]]:
        async with httpx.AsyncClient(timeout=self.timeout, headers=HEADERS) as client:
            data = await self._post(client, "cauciones", {})
        return data if isinstance(data, list) else (data.get("data") or [])

    async def fetch_market_time(self) -> MarketTime:
        async with httpx.AsyncClient(timeout=self.timeout, headers=HEADERS) as client:
            data = await self._post(client, "market-time", {})
        return MarketTime(
            is_working_day=bool(data.get("isWorkingDay")),
            opening=time.fromisoformat(data.get("marketOpeningTime", "10:30:00")),
            closing=time.fromisoformat(data.get("marketClosingTime", "17:00:00")),
        )
