"""
Tabla de cotizaciones del dashboard: una fila por instrumento.

bonistas.com publica cada especie por separado (AL30, AL30D, AL30C; YM34O, YM34D, YM34C). Para la
tabla se unen en una fila con las tres columnas de precio (pesos / MEP / cable), y las especies
quedan listadas en `species`. Las especies sin especie en pesos conocida siguen como fila propia.

Si hay sesión de Bull Market vigente, el precio de cada columna se reemplaza por el último operado
en Bull Market (tiempo real). Las métricas (TIR, paridad, duration, VT) siguen siendo las de
bonistas.com, calculadas con su propio precio.

El motor de arbitraje NO usa esta vista: sigue trabajando con las especies por separado.
"""

from typing import Any, Dict, Iterable, List, Optional, Tuple

from backend.app.data.byma_client import _BOPREAL_PESOS

PRICE_FIELD = {"ARS": "price_ars", "MEP": "price_mep", "CCL": "price_ccl"}


def _species_base(ticker: str, by_ticker: Dict[str, Any]) -> Optional[str]:
    """Ticker de la especie en pesos de una especie D/C, si está en el listado."""
    t = ticker.upper()
    if len(t) < 4 or t[-1] not in ("D", "C"):
        return None
    stem = t[:-1]
    for cand in (_BOPREAL_PESOS.get(stem), stem, stem + "O"):
        if cand and cand != t and cand in by_ticker:
            return cand
    return None


def _species_currency(q: Dict[str, Any]) -> Optional[str]:
    """Moneda de una fila de especie D/C: la única columna de precio con dato."""
    if q.get("price_ars") is not None:
        return None
    has_mep, has_ccl = q.get("price_mep") is not None, q.get("price_ccl") is not None
    if has_mep and not has_ccl:
        return "MEP"
    if has_ccl and not has_mep:
        return "CCL"
    return None


def consolidate(quotes: Iterable[Dict[str, Any]],
                live_books: Optional[Dict[str, Any]] = None,
                full_names: Optional[Dict[str, str]] = None) -> List[Dict[str, Any]]:
    """
    quotes: filas de get_latest_quotes (como dict). live_books: {símbolo: libro de Bull Market}
    solo con los símbolos vigentes del mismo plazo (objetos con .last/.bid/.ask/.trade_time).
    """
    by_ticker = {q["ticker"].upper(): dict(q) for q in quotes if not _is_placeholder(q)}
    live_books = live_books or {}

    # Especies en pesos por (tipo, vencimiento): las especies en dólares de bonos en pesos no
    # comparten el ticker (TA7D ↔ T30A7, SN6D ↔ S30N6, TXD8D ↔ TXMD8) pero sí el vencimiento.
    peso_by_maturity: Dict[Tuple[Any, Any], List[str]] = {}
    for t, q in by_ticker.items():
        if q.get("maturity_date") and _species_currency(q) is None:
            peso_by_maturity.setdefault((q.get("bond_type"), q["maturity_date"]), []).append(t)

    # 1. Asignar cada especie D/C a su especie en pesos
    species_of: Dict[str, Dict[str, str]] = {}      # base -> {"MEP": "AL30D", "CCL": "AL30C"}
    merged: set = set()
    for t, q in by_ticker.items():
        ccy = _species_currency(q)
        if not ccy:
            continue
        base = _species_base(t, by_ticker)
        if base and _species_currency(by_ticker[base]) is not None:
            base = None
        if not base and q.get("maturity_date"):
            cands = peso_by_maturity.get((q.get("bond_type"), q["maturity_date"]), [])
            base = cands[0] if len(cands) == 1 else None     # ambiguo: no adivinar
        if not base:
            continue
        slot = species_of.setdefault(base, {})
        if ccy in slot:          # dos candidatos para la misma moneda: no adivinar
            continue
        slot[ccy] = t
        merged.add(t)

    rows: List[Dict[str, Any]] = []
    for t, q in by_ticker.items():
        if t in merged:
            continue
        row = dict(q)
        species = species_of.get(t, {})
        own_ccy = _species_currency(q)
        # Símbolo de cada moneda: una especie D/C huérfana solo cotiza en su moneda
        if own_ccy:
            symbols: Dict[str, Optional[str]] = {own_ccy: t}
        else:
            symbols = {"ARS": t,
                       "MEP": species.get("MEP") or _guess_species(t, "MEP", live_books),
                       "CCL": species.get("CCL") or _guess_species(t, "CCL", live_books)}
            # La especie propia es la cotización directa de esa moneda
            for ccy, sp in species.items():
                field = PRICE_FIELD[ccy]
                if by_ticker[sp].get(field) is not None:
                    row[field] = by_ticker[sp][field]
            # Especie en pesos sin precio por moneda (bonos nuevos, ON): el último operado
            if row.get("price_ars") is None and q.get("last_price") is not None:
                row["price_ars"] = q["last_price"]
        sources: Dict[str, str] = {ccy: "BONISTAS" for ccy, f in PRICE_FIELD.items()
                                   if row.get(f) is not None}
        live_detail: Dict[str, Dict[str, Any]] = {}

        # 2. Bull Market en tiempo real
        for ccy, field in PRICE_FIELD.items():
            sym = symbols.get(ccy)
            book = live_books.get(sym) if sym else None
            if book is None:
                continue
            price, kind = live_price(book)
            if price is None:
                continue
            row[field] = price
            sources[ccy] = "BULLMARKET"
            live_detail[ccy] = {"symbol": sym, "kind": kind, "bid": getattr(book, "bid", None),
                                "ask": getattr(book, "ask", None), "last": getattr(book, "last", None),
                                "time": getattr(book, "trade_time", None)}

        row["species"] = sorted(species.values())
        # Descripción completa (ON: "Mirgor. Clase IV. Tasa fija 8.25%. USD. Vto. 07-2027.")
        row["full_name"] = (full_names or {}).get(t)
        row["price_sources"] = sources
        row["live_detail"] = live_detail
        row["live"] = any(v == "BULLMARKET" for v in sources.values())
        rows.append(row)
    rows.sort(key=lambda r: r["ticker"])
    return rows


def _is_placeholder(q: Dict[str, Any]) -> bool:
    """Cotización de relleno de bonistas (0.01 y TIR 0) en especies sin operaciones."""
    prices = [q.get(f) for f in ("price_ars", "price_mep", "price_ccl", "last_price")]
    return not q.get("ytm_percentage") and all(p is None or p <= 0.01 for p in prices)


def live_price(book: Any) -> Tuple[Optional[float], Optional[str]]:
    """
    Precio a mostrar de un libro en tiempo real:
    - "ULTIMO": último operado, si está dentro de las puntas (o si no hay las dos puntas).
    - "PUNTA_MEDIA": promedio compra/venta, si el último quedó fuera de las puntas (operación
      aislada, lote chico) o si todavía no hubo operaciones en el día.
    """
    last, bid, ask = getattr(book, "last", None), getattr(book, "bid", None), getattr(book, "ask", None)
    both = bool(bid) and bool(ask) and bid <= ask
    if last and (not both or bid <= last <= ask):
        return float(last), "ULTIMO"
    if both:
        return round((bid + ask) / 2, 4), "PUNTA_MEDIA"
    return None, None


def _guess_species(base: str, ccy: str, live_books: Dict[str, Any]) -> Optional[str]:
    """Especie D/C en Bull Market para un bono cuya especie no vino de bonistas."""
    suffix = "D" if ccy == "MEP" else "C"
    stems = [base]
    if base.endswith("O"):
        stems.append(base[:-1])
    inv = {v: k for k, v in _BOPREAL_PESOS.items()}
    if base in inv:
        stems.insert(0, inv[base])
    for stem in stems:
        if stem + suffix in live_books:
            return stem + suffix
    return None
