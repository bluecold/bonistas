"""
Estrategias algorítmicas de arbitraje y valor relativo para bonos argentinos.
Implementa las 4 estrategias definidas en la especificación formal v1.0.
"""

from decimal import Decimal
from typing import List, Dict, Optional, Any
from datetime import datetime

from backend.app.schemas.arbitrage import ArbitrageSignalCreate
from backend.app.schemas.snapshot import BondQuoteView
from backend.app.quant import (
    calculate_law_spread,
    calculate_breakeven_inflation,
    calculate_z_score
)

# Constantes históricas de calibración (ruedas anuales)
HISTORICAL_LAW_RATIO_MEAN = 1.055   # 5.5% prima promedio histórica Ley NY vs Ley ARG
HISTORICAL_LAW_RATIO_STD = 0.032    # Desvío estándar de la prima de legislación

HISTORICAL_AL30_GD29_SPREAD_MEAN_BPS = 180.0  # Spread medio AL30 vs GD29
HISTORICAL_AL30_GD29_SPREAD_STD_BPS = 45.0   # Desvío estándar

class ArbitrageStrategies:

    @staticmethod
    def evaluate_law_premium(
        quotes_by_ticker: Dict[str, BondQuoteView]
    ) -> List[ArbitrageSignalCreate]:
        """
        Estrategia 1: Spread de Legislación (Law Premium AL vs GD).
        - Regla A: Compresión hacia Ratio <= 1.01 o Spread TIR <= 20 bps -> ROTAR_A_NY (Vender AL, Comprar GD).
        - Regla B: Ensanchamiento hacia Ratio >= 1.12 o Z >= +1.5 sigma -> ROTAR_A_ARG (Vender GD, Comprar AL).
        """
        signals: List[ArbitrageSignalCreate] = []
        pairs = [
            ("AL29", "GD29"),
            ("AL30", "GD30"),
            ("AL35", "GD35"),
            ("AE38", "GD38"),
            ("AL41", "GD41")
        ]

        for al, gd in pairs:
            q_al = quotes_by_ticker.get(al)
            q_gd = quotes_by_ticker.get(gd)

            if not q_al or not q_gd:
                continue

            p_al = q_al.price_mep or q_al.last_price
            p_gd = q_gd.price_mep or q_gd.last_price

            if not p_al or not p_gd or p_al <= 0 or p_gd <= 0:
                continue

            ytm_al = (q_al.ytm_percentage / 100.0) if q_al.ytm_percentage else None
            ytm_gd = (q_gd.ytm_percentage / 100.0) if q_gd.ytm_percentage else None

            metrics = calculate_law_spread(p_gd, p_al, ytm_gd, ytm_al)
            ratio = metrics["price_ratio"]
            yield_spread_bps = metrics["yield_spread_bps"]

            if not ratio:
                continue

            z_score = round((ratio - HISTORICAL_LAW_RATIO_MEAN) / HISTORICAL_LAW_RATIO_STD, 2)

            # Regla A: Compresión extrema de ratio de precio o yield spread
            # El mercado no cobra prima de jurisdicción por ley NY: resguardo legal "gratis"
            if ratio <= 1.01 or (yield_spread_bps is not None and yield_spread_bps <= 20.0):
                signals.append(
                    ArbitrageSignalCreate(
                        strategy_name="LAW_PREMIUM",
                        leg_sell_ticker=al,
                        leg_buy_ticker=gd,
                        metric_name="SPREAD_PRICE_RATIO",
                        metric_value=Decimal(str(ratio)),
                        historical_mean=Decimal(str(HISTORICAL_LAW_RATIO_MEAN)),
                        std_deviations=Decimal(str(z_score)),
                        action_recommended="ROTAR_A_NY",
                        notes=(
                            f"Compresión de brecha legal {al}/{gd}: Ratio {ratio:.4f} (prima {(ratio-1)*100:.2f}%). "
                            f"Oportunidad de rotar a Ley Nueva York con resguardo jurídico internacional sin penalidad de rendimiento."
                        )
                    )
                )

            # Regla B: Ensanchamiento anormal del spread de legislación
            elif ratio >= 1.12 or z_score >= 1.5:
                signals.append(
                    ArbitrageSignalCreate(
                        strategy_name="LAW_PREMIUM",
                        leg_sell_ticker=gd,
                        leg_buy_ticker=al,
                        metric_name="SPREAD_PRICE_RATIO",
                        metric_value=Decimal(str(ratio)),
                        historical_mean=Decimal(str(HISTORICAL_LAW_RATIO_MEAN)),
                        std_deviations=Decimal(str(z_score)),
                        action_recommended="ROTAR_A_ARG",
                        notes=(
                            f"Ensanchamiento anormal de brecha legal {gd}/{al}: Ratio {ratio:.4f} (+{z_score} sigma). "
                            f"Venta de GD y compra de AL anticipando compresión de spread hacia el promedio histórico."
                        )
                    )
                )

        return signals

    @staticmethod
    def evaluate_relative_value_curve(
        quotes_by_ticker: Dict[str, BondQuoteView]
    ) -> List[ArbitrageSignalCreate]:
        """
        Estrategia 2: Relative Value & Duration Swap (Tramo Corto GD29 vs AL30).
        - Métrica: Delta TIR = TIR(AL30) - TIR(GD29).
        - Regla: Spread > 130 bps o Z > +1.1 sigma -> SELL GD29 & BUY AL30.
        Aprovecha la superior convexidad y TIR de AL30 con Modified Duration casi idéntica.
        """
        signals: List[ArbitrageSignalCreate] = []
        q_al30 = quotes_by_ticker.get("AL30")
        q_gd29 = quotes_by_ticker.get("GD29")

        if not q_al30 or not q_gd29:
            return signals

        ytm_al30 = q_al30.ytm_percentage
        ytm_gd29 = q_gd29.ytm_percentage

        if ytm_al30 is not None and ytm_gd29 is not None:
            spread_bps = round((ytm_al30 - ytm_gd29) * 100.0, 1) # diferencia en puntos básicos
            z_score = round(
                (spread_bps - HISTORICAL_AL30_GD29_SPREAD_MEAN_BPS) / HISTORICAL_AL30_GD29_SPREAD_STD_BPS,
                2
            )

            # Activación ante spread superior a 130 bps o z > 1.1 sigma
            if spread_bps >= 130.0 or z_score >= 1.1:
                signals.append(
                    ArbitrageSignalCreate(
                        strategy_name="RELATIVE_VALUE_CURVE",
                        leg_sell_ticker="GD29",
                        leg_buy_ticker="AL30",
                        metric_name="SPREAD_YIELD_BPS",
                        metric_value=Decimal(str(spread_bps)),
                        historical_mean=Decimal(str(HISTORICAL_AL30_GD29_SPREAD_MEAN_BPS)),
                        std_deviations=Decimal(str(z_score)),
                        action_recommended="SWAP_DURACION",
                        notes=(
                            f"Diferencial AL30 vs GD29 en {spread_bps:.1f} bps (Z-Score: +{z_score} sigma). "
                            f"AL30 ofrece mayor convexidad y TIR con Modified Duration equivalente (~1.66 vs 1.29). "
                            f"Recomendación: Rotar GD29 hacia AL30 para maximizar captura en compresión de curvas."
                        )
                    )
                )

        return signals

    @staticmethod
    def evaluate_breakeven_inflation(
        quotes_by_ticker: Dict[str, BondQuoteView],
        expected_monthly_inflation_pct: float = 2.4
    ) -> List[ArbitrageSignalCreate]:
        """
        Estrategia 3: Breakeven de Inflación y Rotación de Deuda en Pesos (LECAP/BONCAP vs BONCER).
        Compara Breakeven mensual (TEM) con la proyección de inflación (IPC / REM).
        """
        signals: List[ArbitrageSignalCreate] = []

        # Buscar mejor referencia de tasa fija (S30N6, T30A7, T15E7)
        fixed_candidates = ["S30N6", "T30A7", "T15E7", "TY30P"]
        fixed_quote: Optional[BondQuoteView] = None
        for t in fixed_candidates:
            if t in quotes_by_ticker and quotes_by_ticker[t].ytm_percentage:
                fixed_quote = quotes_by_ticker[t]
                break

        # Buscar mejor referencia de BONCER (TZX27, TZX28, TX26)
        cer_candidates = ["TZX27", "TZX28", "TX26", "TX31"]
        cer_quote: Optional[BondQuoteView] = None
        for t in cer_candidates:
            if t in quotes_by_ticker and quotes_by_ticker[t].ytm_percentage:
                cer_quote = quotes_by_ticker[t]
                break

        if not fixed_quote or not cer_quote:
            return signals

        fixed_ytm = fixed_quote.ytm_percentage / 100.0
        cer_ytm = cer_quote.ytm_percentage / 100.0

        be_res = calculate_breakeven_inflation(fixed_ytm, cer_ytm)
        be_monthly_pct = be_res["breakeven_monthly_pct"]

        # Comparar con inflación mensual esperada
        diff = expected_monthly_inflation_pct - be_monthly_pct

        # Si inflación esperada supera breakeven -> Conviene comprar CER
        if diff >= 0.15:
            signals.append(
                ArbitrageSignalCreate(
                    strategy_name="BREAKEVEN_CER_FIXED",
                    leg_sell_ticker=fixed_quote.ticker,
                    leg_buy_ticker=cer_quote.ticker,
                    metric_name="BREAKEVEN_TEM",
                    metric_value=Decimal(str(be_monthly_pct)),
                    historical_mean=Decimal(str(expected_monthly_inflation_pct)),
                    std_deviations=Decimal(str(round(diff, 2))),
                    action_recommended="COMPRAR_CER",
                    notes=(
                        f"Inflación proyectada ({expected_monthly_inflation_pct:.2f}% m/m) superior al breakeven "
                        f"de mercado ({be_monthly_pct:.2f}% m/m) entre {fixed_quote.ticker} y {cer_quote.ticker}. "
                        f"Recomendación: Posicionarse en BONCER para capturar ajuste CER + cupón real."
                    )
                )
            )
        # Si inflación esperada es menor al breakeven -> Conviene tasa fija
        elif diff <= -0.15:
            signals.append(
                ArbitrageSignalCreate(
                    strategy_name="BREAKEVEN_CER_FIXED",
                    leg_sell_ticker=cer_quote.ticker,
                    leg_buy_ticker=fixed_quote.ticker,
                    metric_name="BREAKEVEN_TEM",
                    metric_value=Decimal(str(be_monthly_pct)),
                    historical_mean=Decimal(str(expected_monthly_inflation_pct)),
                    std_deviations=Decimal(str(round(abs(diff), 2))),
                    action_recommended="COMPRAR_TASA_FIJA",
                    notes=(
                        f"Inflación proyectada ({expected_monthly_inflation_pct:.2f}% m/m) inferior al breakeven "
                        f"implícito ({be_monthly_pct:.2f}% m/m). "
                        f"Recomendación: Posicionarse en Tasa Fija ({fixed_quote.ticker}) para asegurar tasa real positiva."
                    )
                )
            )

        return signals

    @staticmethod
    def evaluate_dual_bonds(
        quotes_by_ticker: Dict[str, BondQuoteView],
        tamar_tna_pct: float = 38.5,
        inflation_monthly_pct: float = 2.4
    ) -> List[ArbitrageSignalCreate]:
        """
        Estrategia 4: Cobertura Sintética con Bonos Duales (TAMAR vs CER).
        Monitorea bonos duales como TXMD8, TXMJ0 ante incertidumbre de tasas/inflación.
        """
        signals: List[ArbitrageSignalCreate] = []
        dual_tickers = ["TXMD8", "TXMD9", "TXMJ0"]

        for dt in dual_tickers:
            q_dual = quotes_by_ticker.get(dt)
            if not q_dual:
                continue

            parity = q_dual.parity_percentage or 100.0

            # Los bonos duales otorgan el max(TAMAR, CER). Si cotizan a paridad menor al 95%,
            # la opción implícita de cobertura está subvaluada por el mercado
            if parity <= 96.0:
                signals.append(
                    ArbitrageSignalCreate(
                        strategy_name="DUAL_TAMAR_CER",
                        leg_sell_ticker="CASH_ARS",
                        leg_buy_ticker=dt,
                        metric_name="DUAL_OPTION_DISCOUNT",
                        metric_value=Decimal(str(parity)),
                        historical_mean=Decimal("100.0"),
                        std_deviations=Decimal(str(round((100.0 - parity) / 2.0, 2))),
                        action_recommended="COMPRAR_DUAL",
                        notes=(
                            f"Bono Dual {dt} cotizando a paridad atractiva ({parity:.1f}%). "
                            f"Otorga piso de rendimiento con opción implícita alcista tanto ante suba de TAMAR "
                            f"como ante aceleración de inflación CER."
                        )
                    )
                )

        return signals

