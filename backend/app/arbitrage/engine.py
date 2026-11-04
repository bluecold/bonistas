"""
Motor central de arbitrajes.

En cada evaluación:
1. Arma la vista de mercado (puntas por especie/plazo, caución, flujos).
2. Corre los detectores sobre puntas: CI vs 24hs, dólar implícito (ida y vuelta) y ratios
   AL/GD. Y las estrategias sobre analítica (Bonistas): valor relativo AL30/GD29 y breakeven.
3. Concilia con la base: una señal con la misma clave (estrategia|venta|compra|acción) es la
   MISMA señal mientras siga vigente (se actualiza `last_seen` y sus métricas); las que dejan de
   cumplirse pasan a EXPIRED. Así se sabe desde cuándo está activa una oportunidad y en la etapa 5
   se notifica solo cuando aparece una nueva.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.arbitrage.ci_24hs import CiOpportunity, detect_ci_vs_24hs
from backend.app.arbitrage.fx_implied import FxRoundTrip, best_round_trips, implied_fx_quotes
from backend.app.arbitrage.market_view import MarketView, build_market_view
from backend.app.arbitrage.ratios import PairRatio, compute_pair_ratios, ytm_spread_stats
from backend.app.arbitrage.strategies import (
    ArbitrageStrategies,
    HISTORICAL_AL30_GD29_SPREAD_MEAN_BPS,
    HISTORICAL_AL30_GD29_SPREAD_STD_BPS,
    RV_Z_THRESHOLD,
)
from backend.app.db.models import ArbitrageSignal, MacroIndicator
from backend.app.schemas.arbitrage import ArbitrageSignalCreate
from backend.app.schemas.snapshot import BondQuoteView
from backend.app.services.ingestion_service import IngestionService
from backend.app.services.trading_settings import TradingParams, get_params

logger = logging.getLogger(__name__)

LAW_ROTATE_TO_NY_MAX_RATIO = 1.01   # prima NY <= 1%: cobertura legal "gratis"
LAW_ROTATE_TO_ARG_MIN_RATIO = 1.12
LAW_ROTATE_TO_ARG_MIN_Z = 1.5

CONFIRMATION_BY_SOURCE = {"BYMA": "DEMORA_20MIN", "BULLMARKET": "TIEMPO_REAL"}


@dataclass
class ScanResult:
    view: MarketView
    params: TradingParams
    ci_24hs: List[CiOpportunity] = field(default_factory=list)
    fx_quotes: list = field(default_factory=list)
    fx_round_trips: List[FxRoundTrip] = field(default_factory=list)
    ratios: List[PairRatio] = field(default_factory=list)


def signal_key(s: ArbitrageSignalCreate) -> str:
    return f"{s.strategy_name}|{s.leg_sell_ticker}|{s.leg_buy_ticker}|{s.action_recommended}"


class ArbitrageEngine:
    def __init__(self, ingestion_service: Optional[IngestionService] = None,
                 sources: tuple = ("BYMA",)):
        self.ingestion = ingestion_service or IngestionService()
        self.sources = sources          # prioridad de fuentes de puntas (etapa 4: BULLMARKET primero)
        self.last_new_signals: List[ArbitrageSignal] = []
        self.last_expired_count = 0

    # ------------------------------------------------------------------ escaneo
    def scan(self, db: Session, params: Optional[TradingParams] = None,
             now: Optional[datetime] = None) -> ScanResult:
        params = params or get_params(db)
        view = build_market_view(db, sources=self.sources, now=now)
        result = ScanResult(view=view, params=params)
        result.ci_24hs = detect_ci_vs_24hs(view, params)
        result.fx_quotes = implied_fx_quotes(view, params)
        result.fx_round_trips = best_round_trips(result.fx_quotes, params)
        result.ratios = compute_pair_ratios(db, view, params)
        return result

    # ------------------------------------------------------------------ señales sobre puntas
    @staticmethod
    def _signals_from_ci(opps: List[CiOpportunity]) -> List[ArbitrageSignalCreate]:
        out = []
        for o in opps:
            if not o.signal:
                continue
            out.append(ArbitrageSignalCreate(
                strategy_name="CI_24HS",
                leg_sell_ticker=f"{o.sell_leg.symbol} {o.sell_leg.settlement}",
                leg_buy_ticker=f"{o.buy_leg.symbol} {o.buy_leg.settlement}",
                metric_name="GANANCIA_NETA_PCT",
                metric_value=Decimal(str(o.net_pct)),
                action_recommended=o.direction,
                net_profit_pct=o.net_pct,
                confirmation=CONFIRMATION_BY_SOURCE.get(o.source, o.source),
                details=o.to_dict(),
                notes=(
                    f"{o.symbol}: vender {o.sell_leg.settlement} a {o.sell_leg.price} y comprar "
                    f"{o.buy_leg.settlement} a {o.buy_leg.price} ({o.nominal:,.0f} VN ≈ USD {o.size_usd:,.0f}). "
                    f"Bruto {o.gross_pct:.3f}%, costos {o.fees_pct:.2f}%, neto {o.net_pct:.3f}%. "
                    + " ".join(o.notes)
                ),
            ))
        return out

    @staticmethod
    def _signals_from_fx(trips: List[FxRoundTrip], source: str) -> List[ArbitrageSignalCreate]:
        out = []
        for t in trips:
            if not t.signal:
                continue
            out.append(ArbitrageSignalCreate(
                strategy_name=f"{t.kind}_IDA_VUELTA",
                leg_sell_ticker=f"{t.sell_with} {t.settlement}",
                leg_buy_ticker=f"{t.buy_with} {t.settlement}",
                metric_name="GANANCIA_NETA_PCT",
                metric_value=Decimal(str(t.net_pct)),
                action_recommended=f"COMPRAR_{t.kind}_CON_{t.buy_with}_VENDER_CON_{t.sell_with}",
                net_profit_pct=t.net_pct,
                confirmation=CONFIRMATION_BY_SOURCE.get(source, source),
                details=t.to_dict(),
                notes=(
                    f"Comprar dólar {t.kind} con {t.buy_with} a ${t.buy_usd_rate:,.2f} y venderlo con "
                    f"{t.sell_with} a ${t.sell_usd_rate:,.2f} ({t.settlement}). Neto {t.net_pct:.3f}%. "
                    + " ".join(t.notes)
                ),
            ))
        return out

    @staticmethod
    def _signals_from_law_ratios(ratios: List[PairRatio], source: str) -> List[ArbitrageSignalCreate]:
        out = []
        for r in ratios:
            if r.kind != "LEY" or r.settlement != "24HS" or not r.mid_ratio:
                continue
            al, gd = r.a, r.b
            # Costo efectivo de pasar de AL a GD (GD por cada AL, invertido): <= 1.01 => prima comprimida
            cost_to_ny = (1.0 / r.rotate_a_to_b) if r.rotate_a_to_b else None
            common = dict(
                strategy_name="LAW_PREMIUM", metric_name="RATIO_GD_AL",
                metric_value=Decimal(str(r.mid_ratio)),
                historical_mean=Decimal(str(r.hist_mean)) if r.hist_mean else None,
                std_deviations=Decimal(str(r.z_score)) if r.z_score is not None else None,
                confirmation=CONFIRMATION_BY_SOURCE.get(source, source), details=r.to_dict(),
            )
            if cost_to_ny is not None and cost_to_ny <= LAW_ROTATE_TO_NY_MAX_RATIO:
                out.append(ArbitrageSignalCreate(
                    leg_sell_ticker=f"{al}D", leg_buy_ticker=f"{gd}D", action_recommended="ROTAR_A_NY",
                    notes=(f"Prima Ley NY comprimida: pasar de {al}D a {gd}D cuesta {cost_to_ny:.4f} "
                           f"(costos incluidos). Cobertura legal casi sin costo. " + " ".join(r.notes)),
                    **common,
                ))
            elif r.mid_ratio >= LAW_ROTATE_TO_ARG_MIN_RATIO or (
                    r.calibration.startswith("HISTORICA") and r.z_score is not None
                    and r.z_score >= LAW_ROTATE_TO_ARG_MIN_Z):
                out.append(ArbitrageSignalCreate(
                    leg_sell_ticker=f"{gd}D", leg_buy_ticker=f"{al}D", action_recommended="ROTAR_A_ARG",
                    notes=(f"Prima Ley NY anormalmente alta: ratio {r.mid_ratio:.4f} (z {r.z_score:+.2f}, "
                           f"{r.calibration}). Rotar {gd}D -> {al}D da {r.rotate_b_to_a:.4f} nominales por "
                           f"nominal. " + " ".join(r.notes)),
                    **common,
                ))
        return out

    # ------------------------------------------------------------------ evaluación completa
    def evaluate_all_strategies(self, db: Session, now: Optional[datetime] = None) -> List[ArbitrageSignal]:
        """Corre todos los detectores y concilia las señales con la base. Devuelve las activas."""
        scan = self.scan(db, now=now)
        main_source = self.sources[0]

        quotes = self.ingestion.get_latest_quotes(db)
        quotes_dict: Dict[str, BondQuoteView] = {q.ticker: q for q in quotes}

        generated: List[ArbitrageSignalCreate] = []
        generated += self._signals_from_ci(scan.ci_24hs)
        generated += self._signals_from_fx(scan.fx_round_trips, main_source)
        generated += self._signals_from_law_ratios(scan.ratios, main_source)

        # Pares AL/GD sin puntas de BYMA: se evalúan con la analítica de Bonistas (precio MEP)
        pairs_with_books = {(r.a, r.b) for r in scan.ratios if r.kind == "LEY"}
        quotes_without_books = {
            t: q for t, q in quotes_dict.items()
            if not any(t in pair for pair in pairs_with_books)
        }
        generated += ArbitrageStrategies.evaluate_law_premium(quotes_without_books)

        # Valor relativo AL30/GD29: regla puramente estadística -> solo con historia real
        rv_mean, rv_std, _n = ytm_spread_stats(db, "AL30", "GD29")
        if rv_mean is not None:
            generated += ArbitrageStrategies.evaluate_relative_value_curve(quotes_dict, rv_mean, rv_std)

        ipc = self._latest_macro(db, "IPC")
        if ipc is not None:
            generated += ArbitrageStrategies.evaluate_breakeven_inflation(
                quotes_dict, expected_monthly_inflation_pct=ipc)
        # Duales: sin señal. Una paridad < 96% no es evidencia de subvaluación (refleja plazo y
        # tasas); valuarlos requiere modelar la opción CER vs TAMAR, que queda fuera de v1.1.

        return self._reconcile(db, generated)

    def _reconcile(self, db: Session, generated: List[ArbitrageSignalCreate]) -> List[ArbitrageSignal]:
        now = datetime.now(timezone.utc)
        active_rows = list(db.execute(
            select(ArbitrageSignal).where(ArbitrageSignal.status == "ACTIVE").order_by(ArbitrageSignal.id)
        ).scalars())
        # Una fila por clave; las legacy sin clave (v1.0) y los duplicados se expiran
        active: Dict[str, ArbitrageSignal] = {}
        for row in active_rows:
            if row.signal_key and row.signal_key not in active:
                active[row.signal_key] = row
        seen_keys = set()
        new: List[ArbitrageSignal] = []
        current: List[ArbitrageSignal] = []

        for g in generated:
            key = signal_key(g)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            row = active.get(key)
            if row is None:
                row = ArbitrageSignal(signal_key=key, first_seen=now, status="ACTIVE",
                                      strategy_name=g.strategy_name, leg_sell_ticker=g.leg_sell_ticker,
                                      leg_buy_ticker=g.leg_buy_ticker, action_recommended=g.action_recommended)
                db.add(row)
                new.append(row)
            row.timestamp = now
            row.last_seen = now
            row.metric_name = g.metric_name
            row.metric_value = g.metric_value
            row.historical_mean = g.historical_mean
            row.std_deviations = g.std_deviations
            row.notes = g.notes
            row.net_profit_pct = g.net_profit_pct
            row.confirmation = g.confirmation
            row.details = g.details
            current.append(row)

        expired = 0
        kept = {id(r) for r in current}
        for row in active_rows:
            if id(row) not in kept:
                row.status = "EXPIRED"
                expired += 1

        db.commit()
        self.last_new_signals = new
        self.last_expired_count = expired
        logger.info(f"ArbitrageEngine: {len(current)} activas ({len(new)} nuevas, {expired} expiradas).")
        return current

    @staticmethod
    def _latest_macro(db: Session, name: str) -> Optional[float]:
        row = db.execute(
            select(MacroIndicator).where(MacroIndicator.name == name).order_by(MacroIndicator.date.desc())
        ).scalars().first()
        return float(row.value) if row else None

    # ------------------------------------------------------------------ Command Center
    def get_arbitrage_command_center(self, db: Session) -> Dict[str, Any]:
        """Matriz del Command Center con semáforos (GREEN = oportunidad, YELLOW = observación)."""
        scan = self.scan(db)
        quotes_dict = {q.ticker: q for q in self.ingestion.get_latest_quotes(db)}

        active_signals = db.execute(
            select(ArbitrageSignal)
            .where(ArbitrageSignal.status == "ACTIVE")
            .order_by(ArbitrageSignal.net_profit_pct.desc().nulls_last(), ArbitrageSignal.first_seen)
        ).scalars().all()

        # Matriz AL/GD (24hs) desde puntas
        law_pairs_matrix = []
        for r in (x for x in scan.ratios if x.kind == "LEY" and x.settlement == "24HS"):
            cost_to_ny = (1.0 / r.rotate_a_to_b) if r.rotate_a_to_b else None
            light, desc = "NEUTRAL", "Sin desvío significativo"
            if cost_to_ny is not None and cost_to_ny <= LAW_ROTATE_TO_NY_MAX_RATIO:
                light, desc = "GREEN", f"Prima NY comprimida ({r.mid_ratio:.3f}): rotar a NY."
            elif r.mid_ratio and (r.mid_ratio >= LAW_ROTATE_TO_ARG_MIN_RATIO or (
                    r.calibration.startswith("HISTORICA") and (r.z_score or 0) >= LAW_ROTATE_TO_ARG_MIN_Z)):
                light, desc = "GREEN", f"Prima NY inflada ({r.mid_ratio:.3f}, z {r.z_score:+.2f}): rotar a ARG."
            elif r.calibration.startswith("HISTORICA") and r.z_score is not None and abs(r.z_score) >= 1.0:
                light, desc = "YELLOW", f"En observación: z {r.z_score:+.2f} ({r.calibration})."
            law_pairs_matrix.append({
                "al_ticker": r.a, "gd_ticker": r.b,
                "price_al": r.price_a[1] if r.price_a else None,   # vendedora (para comprar)
                "price_gd": r.price_b[1] if r.price_b else None,
                "ratio": r.mid_ratio, "z_score": r.z_score, "calibration": r.calibration,
                "rotate_al_to_gd": r.rotate_a_to_b, "rotate_gd_to_al": r.rotate_b_to_a,
                "traffic_light": light, "status_description": desc,
            })

        # Pares sin puntas en la fuente: se muestran con el precio MEP de Bonistas (último operado)
        from backend.app.arbitrage.ratios import LAW_PAIRS
        shown = {(row["al_ticker"], row["gd_ticker"]) for row in law_pairs_matrix}
        for al, gd in LAW_PAIRS:
            if (al, gd) in shown:
                continue
            q_al, q_gd = quotes_dict.get(al), quotes_dict.get(gd)
            p_al = q_al.price_mep if q_al else None
            p_gd = q_gd.price_mep if q_gd else None
            law_pairs_matrix.append({
                "al_ticker": al, "gd_ticker": gd, "price_al": p_al, "price_gd": p_gd,
                "ratio": round(p_gd / p_al, 4) if p_al and p_gd else None, "z_score": None,
                "calibration": "SIN_PUNTAS", "rotate_al_to_gd": None, "rotate_gd_to_al": None,
                "traffic_light": "NEUTRAL",
                "status_description": "Sin puntas en la fuente: ratio con último precio MEP (Bonistas).",
            })
        order = {p: i for i, p in enumerate(LAW_PAIRS)}
        law_pairs_matrix.sort(key=lambda row: order.get((row["al_ticker"], row["gd_ticker"]), 99))

        # Valor relativo AL30 vs GD29 (TIR de Bonistas), con historia real si alcanza
        rv_mean, rv_std, rv_n = ytm_spread_stats(db, "AL30", "GD29")
        mean_bps = rv_mean if rv_mean is not None else HISTORICAL_AL30_GD29_SPREAD_MEAN_BPS
        std_bps = rv_std or HISTORICAL_AL30_GD29_SPREAD_STD_BPS
        q_al30, q_gd29 = quotes_dict.get("AL30"), quotes_dict.get("GD29")
        rv_spread_bps, rv_light, rv_desc = None, "NEUTRAL", "Curva en rango normal"
        if q_al30 and q_gd29 and q_al30.ytm_percentage and q_gd29.ytm_percentage:
            rv_spread_bps = round((q_al30.ytm_percentage - q_gd29.ytm_percentage) * 100.0, 1)
            rv_z = (rv_spread_bps - mean_bps) / std_bps
            if rv_z >= RV_Z_THRESHOLD and rv_mean is None:
                rv_light, rv_desc = "YELLOW", (
                    f"Spread {rv_spread_bps} bps ({rv_z:+.2f}σ con calibración estática): sin señal hasta "
                    f"tener 20 ruedas de historia ({rv_n} disponibles).")
            elif rv_z >= RV_Z_THRESHOLD:
                rv_light, rv_desc = "GREEN", f"Spread AL30 vs GD29 en {rv_spread_bps} bps ({rv_z:+.2f}σ)."
            elif rv_z >= RV_Z_THRESHOLD / 2:
                rv_light, rv_desc = "YELLOW", f"Spread ampliándose ({rv_spread_bps} bps, {rv_z:+.2f}σ)."
        rv_calibration = f"HISTORICA_{rv_n}d" if rv_mean is not None else f"ESTATICA ({rv_n} ruedas)"

        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "params": scan.params.to_dict(),
            "data_source": self.sources[0],
            "confirmation": CONFIRMATION_BY_SOURCE.get(self.sources[0]),
            "active_signals_count": len(active_signals),
            "active_signals": [
                {
                    "id": s.id,
                    "strategy_name": s.strategy_name,
                    "leg_sell_ticker": s.leg_sell_ticker,
                    "leg_buy_ticker": s.leg_buy_ticker,
                    "metric_name": s.metric_name,
                    "metric_value": float(s.metric_value) if s.metric_value is not None else None,
                    "action_recommended": s.action_recommended,
                    "std_deviations": float(s.std_deviations) if s.std_deviations is not None else None,
                    "net_profit_pct": s.net_profit_pct,
                    "confirmation": s.confirmation,
                    "first_seen": s.first_seen.isoformat() if s.first_seen else None,
                    "last_seen": s.last_seen.isoformat() if s.last_seen else None,
                    "notes": s.notes,
                }
                for s in active_signals
            ],
            "law_premium_matrix": law_pairs_matrix,
            "curve_ratios": [r.to_dict() for r in scan.ratios if r.kind == "CURVA"],
            "relative_value_tramo_corto": {
                "pair": "GD29 vs AL30",
                "spread_bps": rv_spread_bps,
                "mean_bps": round(mean_bps, 1),
                "calibration": rv_calibration,
                "traffic_light": rv_light,
                "status_description": rv_desc,
            },
        }
