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
RV_Z_THRESHOLD = 1.1                          # Desvíos sobre la media para activar el swap

class ArbitrageStrategies:

    @staticmethod
    def evaluate_law_premium(
        quotes_by_ticker: Dict[str, BondQuoteView]
    ) -> List[ArbitrageSignalCreate]:
        """
        Estrategia 1: Spread de Legislación (Law Premium AL vs GD).
        - Regla A: Compresión hacia Ratio <= 1.01 o Spread TIR <= 20 bps -> ROTAR_A_NY (Vender AL, Comprar GD).
        - La rotación a Ley ARG por prima alta ya no se decide acá con un corte fijo común a todos
          los pares: usa la banda propia de cada par sobre puntas (ratios.py / engine.py).
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

            # Solo especie D (MEP) contra especie D. Nunca caer a last_price: puede estar en pesos.
            p_al = q_al.price_mep
            p_gd = q_gd.price_mep

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

        return signals

    @staticmethod
    def evaluate_relative_value_curve(
        quotes_by_ticker: Dict[str, BondQuoteView],
        spread_mean_bps: Optional[float] = None,
        spread_std_bps: Optional[float] = None,
    ) -> List[ArbitrageSignalCreate]:
        """
        Estrategia 2: Relative Value & Duration Swap (Tramo Corto GD29 vs AL30).
        - Métrica: Delta TIR = TIR(AL30) - TIR(GD29).
        - Regla: Z >= +1.1 sigma sobre la media histórica del spread -> SELL GD29 & BUY AL30.
          (Antes también disparaba con spread >= 130 bps, umbral por DEBAJO de la media de 180 bps:
          la señal quedaba activa en condiciones normales de mercado.)
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
            # Media/desvío de la historia real si se proveen; si no, calibración estática
            mean_bps = spread_mean_bps if spread_mean_bps is not None else HISTORICAL_AL30_GD29_SPREAD_MEAN_BPS
            std_bps = spread_std_bps if spread_std_bps else HISTORICAL_AL30_GD29_SPREAD_STD_BPS
            calibration = "historia real" if spread_mean_bps is not None else "calibración estática"
            z_score = round((spread_bps - mean_bps) / std_bps, 2)

            # Activación solo ante un ensanchamiento anormal respecto de la media histórica
            if z_score >= RV_Z_THRESHOLD:
                signals.append(
                    ArbitrageSignalCreate(
                        strategy_name="RELATIVE_VALUE_CURVE",
                        leg_sell_ticker="GD29",
                        leg_buy_ticker="AL30",
                        metric_name="SPREAD_YIELD_BPS",
                        metric_value=Decimal(str(spread_bps)),
                        historical_mean=Decimal(str(round(mean_bps, 2))),
                        std_deviations=Decimal(str(z_score)),
                        action_recommended="SWAP_DURACION",
                        notes=(
                            f"Diferencial AL30 vs GD29 en {spread_bps:.1f} bps (Z-Score: {z_score:+.2f} sigma "
                            f"sobre una media de {mean_bps:.0f} bps, {calibration}). "
                            f"MD AL30 {q_al30.modified_duration or '-'} vs GD29 {q_gd29.modified_duration or '-'}. "
                            f"Recomendación: Rotar GD29 hacia AL30 para maximizar captura en compresión de curvas."
                        )
                    )
                )

        return signals

    @staticmethod
    def _match_fixed_cer_pair(quotes_by_ticker: Dict[str, BondQuoteView]):
        """
        Elige el par tasa fija / CER con la Modified Duration más parecida (y > ~2 meses), para
        que el breakeven compare plazos equivalentes. Antes se tomaba el primero de una lista
        fija (ej. S30N6 a 26 días contra TZX27 a 8 meses).
        Sin datos de duration, cae al primero disponible de cada tipo.
        """
        MIN_MD = 0.15
        # Solo especies en pesos: las especies en dólares (TA7D, T2D8D...) repiten el bono
        def peso_species(q) -> bool:
            return q.price_ars is not None or (q.price_mep is None and q.price_ccl is None)
        fixed = [q for q in quotes_by_ticker.values()
                 if q.bond_type == "TASA_FIJA" and q.ytm_percentage and peso_species(q)]
        cer = [q for q in quotes_by_ticker.values()
               if q.bond_type == "CER" and q.ytm_percentage and peso_species(q)]
        with_md = [
            (abs(f.modified_duration - c.modified_duration), f, c)
            for f in fixed for c in cer
            if f.modified_duration and c.modified_duration
            and f.modified_duration >= MIN_MD and c.modified_duration >= MIN_MD
        ]
        if with_md:
            _, f, c = min(with_md, key=lambda t: t[0])
            return f, c
        return (fixed[0] if fixed else None), (cer[0] if cer else None)

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

        fixed_quote, cer_quote = ArbitrageStrategies._match_fixed_cer_pair(quotes_by_ticker)

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
                        f"de mercado ({be_monthly_pct:.2f}% m/m) entre {fixed_quote.ticker} (MD {fixed_quote.modified_duration or '-'}) "
                        f"y {cer_quote.ticker} (MD {cer_quote.modified_duration or '-'}). "
                        f"Nota: la inflación de referencia es el último IPC publicado (no una expectativa). "
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

