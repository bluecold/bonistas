"""
Motor algorítmico central de arbitrajes.
Orquesta la evaluación periódica de las 4 estrategias, concilia señales activas/expiradas y genera el Command Center.
"""

import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from sqlalchemy import select, update

from backend.app.db.models import ArbitrageSignal, MacroIndicator
from backend.app.schemas.arbitrage import ArbitrageSignalCreate
from backend.app.schemas.snapshot import BondQuoteView
from backend.app.services.ingestion_service import IngestionService
from backend.app.arbitrage.strategies import (
    ArbitrageStrategies,
    HISTORICAL_AL30_GD29_SPREAD_MEAN_BPS,
    HISTORICAL_AL30_GD29_SPREAD_STD_BPS,
    RV_Z_THRESHOLD,
)

logger = logging.getLogger(__name__)

class ArbitrageEngine:
    def __init__(self, ingestion_service: Optional[IngestionService] = None):
        self.ingestion = ingestion_service or IngestionService()

    def evaluate_all_strategies(self, db: Session) -> List[ArbitrageSignal]:
        """
        Ejecuta todas las estrategias contra las últimas cotizaciones guardadas en la base de datos.
        Actualiza el estado de las señales en la tabla arbitrage_signals y retorna las señales activas.
        """
        # 1. Obtener cotizaciones consolidadas
        quotes = self.ingestion.get_latest_quotes(db)
        quotes_dict: Dict[str, BondQuoteView] = {q.ticker: q for q in quotes}

        # 2. Obtener variables macro más recientes
        macro_ipc = db.execute(
            select(MacroIndicator)
            .where(MacroIndicator.name == "IPC")
            .order_by(MacroIndicator.date.desc())
        ).scalars().first()
        expected_ipc = float(macro_ipc.value) if macro_ipc else 2.4

        macro_tamar = db.execute(
            select(MacroIndicator)
            .where(MacroIndicator.name == "TAMAR")
            .order_by(MacroIndicator.date.desc())
        ).scalars().first()
        tamar_rate = float(macro_tamar.value) if macro_tamar else 38.5

        # 3. Evaluar las 4 estrategias
        generated_signals: List[ArbitrageSignalCreate] = []

        # Estrategia 1: Spread de Legislación (AL vs GD)
        sig_law = ArbitrageStrategies.evaluate_law_premium(quotes_dict)
        generated_signals.extend(sig_law)

        # Estrategia 2: Relative Value Curva Corta (GD29 vs AL30)
        sig_rv = ArbitrageStrategies.evaluate_relative_value_curve(quotes_dict)
        generated_signals.extend(sig_rv)

        # Estrategia 3: Breakeven Inflación (LECAP vs BONCER)
        sig_be = ArbitrageStrategies.evaluate_breakeven_inflation(quotes_dict, expected_monthly_inflation_pct=expected_ipc)
        generated_signals.extend(sig_be)

        # Estrategia 4: Bonos Duales (TAMAR vs CER)
        sig_dual = ArbitrageStrategies.evaluate_dual_bonds(quotes_dict, tamar_tna_pct=tamar_rate, inflation_monthly_pct=expected_ipc)
        generated_signals.extend(sig_dual)

        # 4. Sincronizar con la base de datos:
        # Marcar señales previas como EXPIRED
        db.execute(
            update(ArbitrageSignal)
            .where(ArbitrageSignal.status == "ACTIVE")
            .values(status="EXPIRED")
        )

        now = datetime.now(timezone.utc)
        saved_signals: List[ArbitrageSignal] = []

        for s_data in generated_signals:
            db_signal = ArbitrageSignal(
                timestamp=now,
                strategy_name=s_data.strategy_name,
                leg_sell_ticker=s_data.leg_sell_ticker,
                leg_buy_ticker=s_data.leg_buy_ticker,
                metric_name=s_data.metric_name,
                metric_value=s_data.metric_value,
                historical_mean=s_data.historical_mean,
                std_deviations=s_data.std_deviations,
                action_recommended=s_data.action_recommended,
                status="ACTIVE",
                notes=s_data.notes
            )
            db.add(db_signal)
            saved_signals.append(db_signal)

        db.commit()
        logger.info(f"ArbitrageEngine: {len(saved_signals)} señales activas generadas y persistidas.")
        return saved_signals

    def get_arbitrage_command_center(self, db: Session) -> Dict[str, Any]:
        """
        Retorna la matriz completa del Command Center con semáforos (Verde, Amarillo, Rojo)
        para visualización en el dashboard.
        """
        quotes = self.ingestion.get_latest_quotes(db)
        quotes_dict = {q.ticker: q for q in quotes}

        # Señales activas actuales
        active_signals = db.execute(
            select(ArbitrageSignal)
            .where(ArbitrageSignal.status == "ACTIVE")
            .order_by(ArbitrageSignal.timestamp.desc())
        ).scalars().all()

        # Matriz Semáforo Ley Local vs NY
        law_pairs_matrix = []
        for al, gd in [("AL29", "GD29"), ("AL30", "GD30"), ("AL35", "GD35"), ("AE38", "GD38"), ("AL41", "GD41")]:
            q_al = quotes_dict.get(al)
            q_gd = quotes_dict.get(gd)
            # Solo especie D (MEP): last_price puede estar en pesos y distorsionar el ratio
            p_al = q_al.price_mep if q_al else None
            p_gd = q_gd.price_mep if q_gd else None
            ratio = round(p_gd / p_al, 4) if p_al and p_gd and p_al > 0 else None
            
            traffic_light = "RED"
            status_desc = "Sin desvío significativo"
            if ratio:
                if ratio <= 1.01:
                    traffic_light = "GREEN"
                    status_desc = f"Arbitraje Claro: Prima NY comprimida ({ratio:.3f}). Rotar a NY."
                elif ratio >= 1.12:
                    traffic_light = "GREEN"
                    status_desc = f"Arbitraje Claro: Prima NY inflada ({ratio:.3f}). Rotar a ARG."
                elif ratio <= 1.035 or ratio >= 1.09:
                    traffic_light = "YELLOW"
                    status_desc = f"En Observación: Ratio en zona límite ({ratio:.3f})."

            law_pairs_matrix.append({
                "al_ticker": al,
                "gd_ticker": gd,
                "price_al": p_al,
                "price_gd": p_gd,
                "ratio": ratio,
                "traffic_light": traffic_light,
                "status_description": status_desc
            })

        # Semáforo Relative Value AL30 vs GD29
        q_al30 = quotes_dict.get("AL30")
        q_gd29 = quotes_dict.get("GD29")
        rv_spread_bps = None
        rv_light = "RED"
        rv_desc = "Curva en rango normal"
        if q_al30 and q_gd29 and q_al30.ytm_percentage and q_gd29.ytm_percentage:
            rv_spread_bps = round((q_al30.ytm_percentage - q_gd29.ytm_percentage) * 100.0, 1)
            rv_z = (rv_spread_bps - HISTORICAL_AL30_GD29_SPREAD_MEAN_BPS) / HISTORICAL_AL30_GD29_SPREAD_STD_BPS
            if rv_z >= RV_Z_THRESHOLD:
                rv_light = "GREEN"
                rv_desc = f"Arbitraje Convexidad Activo: Spread AL30 vs GD29 en {rv_spread_bps} bps ({rv_z:+.2f}σ)."
            elif rv_z >= RV_Z_THRESHOLD / 2:
                rv_light = "YELLOW"
                rv_desc = f"En Observación: Spread ampliándose ({rv_spread_bps} bps, {rv_z:+.2f}σ)."

        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "active_signals_count": len(active_signals),
            "active_signals": [
                {
                    "id": s.id,
                    "strategy_name": s.strategy_name,
                    "leg_sell_ticker": s.leg_sell_ticker,
                    "leg_buy_ticker": s.leg_buy_ticker,
                    "metric_name": s.metric_name,
                    "metric_value": float(s.metric_value),
                    "action_recommended": s.action_recommended,
                    "std_deviations": float(s.std_deviations) if s.std_deviations else None,
                    "notes": s.notes
                }
                for s in active_signals
            ],
            "law_premium_matrix": law_pairs_matrix,
            "relative_value_tramo_corto": {
                "pair": "GD29 vs AL30",
                "spread_bps": rv_spread_bps,
                "traffic_light": rv_light,
                "status_description": rv_desc
            }
        }

