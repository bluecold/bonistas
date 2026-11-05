"""
Dólar implícito ejecutable por bono (pesos <-> dólares) y arbitraje de ida y vuelta.

Para cada bono con especie en pesos y en dólares (D = MEP, C = cable):
- COMPRAR dólares con el bono: compro la especie en pesos (vendedora) y vendo la D/C (compradora)
      tc_compra = vendedora_ARS * (1 + costo) / (compradora_USD * (1 - costo))     -> cuanto más bajo, mejor
- VENDER dólares con el bono: compro la D/C (vendedora) y vendo en pesos (compradora)
      tc_venta  = compradora_ARS * (1 - costo) / (vendedora_USD * (1 + costo))     -> cuanto más alto, mejor

Se calculan todas las combinaciones de plazo (pesos CI/24hs x dólares CI/24hs). En las que
cruzan plazos, si el bono paga un flujo entre CI y 24hs se descartan (el precio de un plazo
incluiría el cupón y el del otro no).

Ida y vuelta (señal): comprar dólares con el bono más barato y venderlos con el más caro,
las 4 patas en el mismo plazo:  ganancia = tc_venta(Y) / tc_compra(X) - 1  (costos incluidos).
"""

from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional

from backend.app.arbitrage.market_view import MIXED_SOURCE, MarketView, combined_source, walk_book
from backend.app.services.trading_settings import TradingParams

SETTLEMENTS = ("CI", "24HS")


@dataclass
class FxQuote:
    base: str
    kind: str                 # 'MEP' | 'CCL'
    ars_symbol: str
    usd_symbol: str
    ars_settlement: str
    usd_settlement: str
    buy_usd_rate: Optional[float]    # ARS por USD al comprar dólares (costos incluidos)
    sell_usd_rate: Optional[float]   # ARS por USD al vender dólares (costos incluidos)
    buy_depth_ok: bool
    sell_depth_ok: bool
    nominal: Optional[float]
    notes: List[str] = field(default_factory=list)
    source: str = "BYMA"

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class FxRoundTrip:
    kind: str
    settlement: str
    buy_with: str             # bono con el que se compran los dólares
    sell_with: str            # bono con el que se venden
    buy_usd_rate: float
    sell_usd_rate: float
    net_pct: float
    signal: bool
    notes: List[str] = field(default_factory=list)
    source: str = "BYMA"

    def to_dict(self) -> Dict:
        return asdict(self)


def _fill_price(levels, qty) -> (Optional[float], bool):
    if not levels:
        return None, False
    if not qty:
        return levels[0].price, False
    f = walk_book(levels, qty)
    return (f.avg_price, True) if f.complete else (levels[0].price, False)


def implied_fx_quotes(view: MarketView, params: TradingParams) -> List[FxQuote]:
    fee = params.commission_pct / 100.0
    out: List[FxQuote] = []
    for base, books in view.by_base().items():
        for kind in ("MEP", "CCL"):
            for s_ars in SETTLEMENTS:
                ars = books.get(("ARS", s_ars))
                if not ars:
                    continue
                for s_usd in SETTLEMENTS:
                    usd = books.get((kind, s_usd))
                    if not usd:
                        continue
                    notes: List[str] = []
                    if s_ars != s_usd:
                        flow, status = view.flow_between(base, kind, view.today, view.next_bd)
                        if status != "SIN_PAGOS":
                            continue   # cruce de plazos con pago en el medio o sin datos: no comparable
                        notes.append("Cruza plazos: una pata liquida hoy y la otra en 24hs.")
                    ref = usd.mid
                    nominal = view.nominal_for_usd(params.trade_size_usd, ref, kind) if ref else None

                    ars_ask, ok1 = _fill_price(ars.asks, nominal)
                    usd_bid, ok2 = _fill_price(usd.bids, nominal)
                    ars_bid, ok3 = _fill_price(ars.bids, nominal)
                    usd_ask, ok4 = _fill_price(usd.asks, nominal)

                    buy = (ars_ask * (1 + fee)) / (usd_bid * (1 - fee)) if ars_ask and usd_bid else None
                    sell = (ars_bid * (1 - fee)) / (usd_ask * (1 + fee)) if ars_bid and usd_ask else None
                    if buy is None and sell is None:
                        continue
                    out.append(FxQuote(
                        base=base, kind=kind, ars_symbol=ars.symbol, usd_symbol=usd.symbol,
                        ars_settlement=s_ars, usd_settlement=s_usd,
                        buy_usd_rate=round(buy, 2) if buy else None,
                        sell_usd_rate=round(sell, 2) if sell else None,
                        buy_depth_ok=ok1 and ok2, sell_depth_ok=ok3 and ok4,
                        nominal=round(nominal) if nominal else None, notes=notes,
                        source=combined_source(ars, usd),
                    ))
    return out


def best_round_trips(quotes: List[FxQuote], params: TradingParams) -> List[FxRoundTrip]:
    """Mejor ida y vuelta por tipo de dólar y plazo (las 4 patas en el mismo plazo)."""
    out: List[FxRoundTrip] = []
    for kind in ("MEP", "CCL"):
        for s in SETTLEMENTS:
            same = [q for q in quotes if q.kind == kind and q.ars_settlement == s and q.usd_settlement == s]
            buys = [q for q in same if q.buy_usd_rate and q.buy_depth_ok]
            sells = [q for q in same if q.sell_usd_rate and q.sell_depth_ok]
            if not buys or not sells:
                continue
            b = min(buys, key=lambda q: q.buy_usd_rate)
            v = max(sells, key=lambda q: q.sell_usd_rate)
            if b.base == v.base:
                # con el mismo bono no hay arbitraje real (sería cruzar su propio spread)
                others = [q for q in sells if q.base != b.base]
                if not others:
                    continue
                v = max(others, key=lambda q: q.sell_usd_rate)
            net = (v.sell_usd_rate / b.buy_usd_rate - 1.0) * 100.0
            out.append(FxRoundTrip(
                kind=kind, settlement=s, buy_with=b.base, sell_with=v.base,
                buy_usd_rate=b.buy_usd_rate, sell_usd_rate=v.sell_usd_rate, net_pct=round(net, 4),
                signal=net >= params.min_net_profit_pct,
                notes=[f"4 operaciones con costo {params.commission_pct}% c/u ya incluido.",
                       "Verificar restricciones vigentes de CNV para operaciones con dólar MEP/CCL."],
                source=b.source if b.source == v.source else MIXED_SOURCE,
            ))
    return out
