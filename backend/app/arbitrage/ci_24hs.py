"""
Detector de arbitraje entre plazos: Contado Inmediato (CI) vs 24hs, misma especie.

Direcciones (siempre con puntas, nunca con último precio):

A) VENDER CI / COMPRAR 24HS  (requiere tener el bono)
   Vendo hoy a la compradora CI y recompro a la vendedora de 24hs. Cobro hoy y pago mañana.
     bruto = (compradora_CI - F) / vendedora_24 - 1
   F = flujo que paga el bono entre hoy y la liquidación de 24hs: el precio CI lo incluye y el
   de 24hs no; si vendo en CI lo pierdo. Bonus opcional: colocar el efectivo en caución esos días.

B) COMPRAR CI / VENDER 24HS  (requiere efectivo)
   Compro hoy a la vendedora CI y vendo a la compradora de 24hs. Pago hoy, cobro mañana.
     bruto = (compradora_24 + F) / vendedora_CI - 1
   Costo de oportunidad: la caución que dejo de ganar esos días (se resta).

En ambos casos: neto = bruto - 2 x costo por operación (- caución en B).
Solo se emite señal si neto >= ganancia mínima Y ambas puntas tienen cantidad suficiente para
el tamaño de operación configurado.
"""

from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional

from backend.app.arbitrage.market_view import MarketView, walk_book, combined_source
from backend.app.services.trading_settings import TradingParams


@dataclass
class Leg:
    symbol: str
    settlement: str
    side: str                  # 'VENTA' (contra la compradora) o 'COMPRA' (contra la vendedora)
    price: Optional[float]     # precio promedio ejecutable para el tamaño pedido
    best_price: Optional[float]
    available_qty: float


@dataclass
class CiOpportunity:
    symbol: str
    base: str
    currency: str
    direction: str             # 'VENDER_CI_COMPRAR_24HS' | 'COMPRAR_CI_VENDER_24HS'
    sell_leg: Leg
    buy_leg: Leg
    nominal: Optional[float]
    size_usd: float
    gross_pct: Optional[float]
    fees_pct: float
    carry_pct: float           # caución por los días entre liquidaciones
    flow_adjustment: float     # F por 100 VN, en la moneda de la especie
    coupon_status: str         # SIN_PAGOS / AJUSTADO / DESCONOCIDO / CORTE_PROBABLE / AJUSTE_DUDOSO
    net_pct: Optional[float]
    depth_ok: bool
    signal: bool
    days: int
    source: str
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return asdict(self)


# Resguardos contra eventos del bono que no figuran en los flujos (cortes de cupón o
# amortizaciones que la fuente ya no lista, canjes, etc.)
STRUCTURAL_GAP_PCT = 3.0    # brecha bruta a partir de la cual se mira el cierre anterior
ANOMALY_GAP_PCT = 10.0      # brecha bruta que nunca es un desarbitraje CI/24hs real


def _r(v: Optional[float], n: int = 4) -> Optional[float]:
    return round(v, n) if v is not None else None


def detect_ci_vs_24hs(view: MarketView, params: TradingParams) -> List[CiOpportunity]:
    fee = params.commission_pct / 100.0
    min_net = params.min_net_profit_pct
    days = view.settlement_days
    caucion = (view.caucion_tna_pct or 0.0) / 100.0
    carry_pct = caucion * days / 365.0 * 100.0

    out: List[CiOpportunity] = []
    symbols = {sym for (sym, _st) in view.books}
    for sym in sorted(symbols):
        ci, h24 = view.book(sym, "CI"), view.book(sym, "24HS")
        if not ci or not h24:
            continue
        ref_price = h24.mid or ci.mid
        nominal = view.nominal_for_usd(params.trade_size_usd, ref_price, ci.currency) if ref_price else None
        fx = view.implied_mep(ci.base, "CI") if ci.currency == "ARS" else None
        flow, base_status = view.flow_between(ci.base, ci.currency, view.today, view.next_bd, fx)

        for direction in ("VENDER_CI_COMPRAR_24HS", "COMPRAR_CI_VENDER_24HS"):
            coupon_status = base_status      # cada dirección parte del estado del cronograma
            if direction == "VENDER_CI_COMPRAR_24HS":
                sell_book, sell_levels = ci, ci.bids
                buy_book, buy_levels = h24, h24.asks
            else:
                sell_book, sell_levels = h24, h24.bids
                buy_book, buy_levels = ci, ci.asks
            if not sell_levels or not buy_levels:
                continue

            qty = nominal if nominal else 0.0
            sell_fill = walk_book(sell_levels, qty) if qty else None
            buy_fill = walk_book(buy_levels, qty) if qty else None
            depth_ok = bool(sell_fill and buy_fill and sell_fill.complete and buy_fill.complete)
            sell_px = sell_fill.avg_price if depth_ok else sell_levels[0].price
            buy_px = buy_fill.avg_price if depth_ok else buy_levels[0].price

            if direction == "VENDER_CI_COMPRAR_24HS":
                gross = ((sell_px - flow) / buy_px - 1.0) * 100.0
                net = gross - 2 * fee * 100.0
            else:
                gross = ((sell_px + flow) / buy_px - 1.0) * 100.0
                net = gross - 2 * fee * 100.0 - carry_pct

            notes: List[str] = []
            if coupon_status == "AJUSTADO":
                notes.append(f"Ajustado por pago de {flow:.4f} entre {view.today} y {view.next_bd} (corte de cupón).")
            elif coupon_status == "DESCONOCIDO":
                notes.append("Sin cronograma de pagos: verificar que no haya corte de cupón antes de operar.")
            if not depth_ok:
                avail = min(l[0].qty for l in (sell_levels, buy_levels))
                notes.append(f"Profundidad insuficiente para USD {params.trade_size_usd:,.0f} (mejor punta: {avail:,.0f} VN).")
            if direction == "VENDER_CI_COMPRAR_24HS":
                notes.append("Requiere tener el bono en cartera.")
                if carry_pct:
                    notes.append(f"Extra opcional: colocar el efectivo en caución {days} día(s) ≈ +{carry_pct:.3f}%.")
            else:
                notes.append(f"Incluye costo de oportunidad de caución {days} día(s): -{carry_pct:.3f}%.")

            # ¿La brecha ya existía al cierre anterior? Entonces es estructural (corte de cupón /
            # amortización en el medio), no un desarbitraje.
            if abs(gross) >= STRUCTURAL_GAP_PCT and ci.prev_close and h24.prev_close:
                prev_gap = (ci.prev_close / h24.prev_close - 1.0) * 100.0
                same_side = prev_gap if direction == "VENDER_CI_COMPRAR_24HS" else -prev_gap
                if same_side >= abs(gross) * 0.5:
                    coupon_status = "CORTE_PROBABLE" if coupon_status == "SIN_PAGOS" else coupon_status
                    notes.insert(0, f"La brecha CI/24hs ya estaba al cierre anterior ({prev_gap:+.2f}%): "
                                    "probable corte de cupón o amortización no informado. Sin señal.")
            if abs(gross) >= ANOMALY_GAP_PCT and coupon_status == "AJUSTADO":
                # El cronograma dice que hay un corte entre las dos liquidaciones, pero los precios
                # no lo reflejan (ej. pago final al vencimiento: CI y 24hs cotizan los dos con el
                # pago adentro). El ajuste fabrica una ganancia que no existe.
                notes.insert(0, f"Aun descontando el pago de {flow:.4f} queda una brecha de {gross:+.1f}%: "
                                "los precios de CI y 24hs no reflejan ese corte. Sin señal.")
                coupon_status = "AJUSTE_DUDOSO"
            elif abs(gross) >= ANOMALY_GAP_PCT:
                notes.insert(0, f"Brecha de {gross:+.1f}% entre CI y 24hs: demasiado grande para un "
                                "desarbitraje real. Verificar pagos del bono. Sin señal.")
                if coupon_status == "SIN_PAGOS":
                    coupon_status = "CORTE_PROBABLE"

            signal =depth_ok and net >= min_net and coupon_status in ("SIN_PAGOS", "AJUSTADO")
            out.append(CiOpportunity(
                symbol=sym, base=ci.base, currency=ci.currency, direction=direction,
                sell_leg=Leg(sell_book.symbol, sell_book.settlement, "VENTA", _r(sell_px),
                             sell_levels[0].price, sell_levels[0].qty),
                buy_leg=Leg(buy_book.symbol, buy_book.settlement, "COMPRA", _r(buy_px),
                            buy_levels[0].price, buy_levels[0].qty),
                nominal=_r(nominal, 0), size_usd=params.trade_size_usd,
                gross_pct=_r(gross), fees_pct=round(2 * fee * 100.0, 4), carry_pct=round(carry_pct, 4),
                flow_adjustment=round(flow, 6), coupon_status=coupon_status, net_pct=_r(net),
                depth_ok=depth_ok, signal=signal, days=days, source=combined_source(ci, h24), notes=notes,
            ))
    out.sort(key=lambda o: (o.net_pct if o.net_pct is not None else -1e9), reverse=True)
    return out
