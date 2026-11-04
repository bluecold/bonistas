"""
Generador de flujos de fondos (Cash Flows) para títulos públicos de la República Argentina.
Maneja amortizaciones escalonadas, cupones step-up, bonos bullet y letras capitalizables.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import List, Dict, Optional
import numpy as np

@dataclass
class CashFlowItem:
    date: date
    days_from_settlement: int
    interest_rate: float
    coupon_amount: float
    amortization_amount: float
    total_cashflow: float
    residual_capital: float

# Cronogramas específicos de amortización y cupones de la reestructuración 2020
# (Fechas de pago: 9 de enero y 9 de julio de cada año)

def get_hard_dollar_schedule(ticker: str) -> List[Dict]:
    """
    Retorna el cronograma formal de cupones y amortizaciones para Bonares y Globales.
    Base 100 de valor nominal original.
    """
    ticker_base = ticker.replace("D", "").replace("C", "").upper()
    
    # AL30 / GD30:
    # Vencimiento: 09/07/2030. Cupones: 9 ene y 9 jul.
    # Amortizaciones: 12 cuotas semestrales:
    # Jul-24: 4%, Ene-25: 4%, Jul-25 a Jul-30: 8% semestral (10 cuotas)
    if ticker_base in ("AL30", "GD30"):
        dates = [
            (date(2024, 7, 9), 0.0075, 4.0),
            (date(2025, 1, 9), 0.0075, 4.0),
            (date(2025, 7, 9), 0.0075, 8.0),
            (date(2026, 1, 9), 0.0075, 8.0),
            (date(2026, 7, 9), 0.0075, 12.0),
            (date(2027, 1, 9), 0.0075, 8.0),
            (date(2027, 7, 9), 0.0175, 8.0),
            (date(2028, 1, 9), 0.0175, 8.0),
            (date(2028, 7, 9), 0.0175, 8.0),
            (date(2029, 1, 9), 0.0175, 8.0),
            (date(2029, 7, 9), 0.0175, 8.0),
            (date(2030, 1, 9), 0.0175, 8.0),
            (date(2030, 7, 9), 0.0175, 8.0),
        ]
        return [{"date": d, "coupon_tna": c, "amort_pct": a} for d, c, a in dates]

    # AL29 / GD29:
    # Vencimiento: 09/07/2029. Amortización: 10 cuotas semestrales del 10% a partir de Ene-25.
    if ticker_base in ("AL29", "GD29"):
        dates = [
            (date(2025, 1, 9), 0.0100, 10.0),
            (date(2025, 7, 9), 0.0100, 10.0),
            (date(2026, 1, 9), 0.0100, 10.0),
            (date(2026, 7, 9), 0.0100, 10.0),
            (date(2027, 1, 9), 0.0100, 10.0),
            (date(2027, 7, 9), 0.0100, 10.0),
            (date(2028, 1, 9), 0.0100, 10.0),
            (date(2028, 7, 9), 0.0100, 10.0),
            (date(2029, 1, 9), 0.0100, 10.0),
            (date(2029, 7, 9), 0.0100, 10.0),
        ]
        return [{"date": d, "coupon_tna": c, "amort_pct": a} for d, c, a in dates]

    # AL35 / GD35:
    # Vencimiento: 09/07/2035. Amortización: 10 cuotas del 10% desde Ene-31.
    if ticker_base in ("AL35", "GD35"):
        schedule = []
        for year in range(2025, 2036):
            c_rate = 0.04125 if year >= 2028 else 0.03625
            for month in (1, 7):
                d = date(year, month, 9)
                amort = 10.0 if year > 2030 or (year == 2031 and month >= 1) else 0.0
                if d <= date(2035, 7, 9):
                    schedule.append({"date": d, "coupon_tna": c_rate, "amort_pct": amort})
        return schedule

    # AE38 / GD38:
    # Vencimiento: 09/01/2038. Amortización semestral desde Jul-27.
    if ticker_base in ("AE38", "GD38"):
        schedule = []
        for year in range(2025, 2039):
            c_rate = 0.050 if year >= 2028 else 0.0425
            for month in (1, 7):
                d = date(year, month, 9)
                amort = 4.545 if (year > 2027 or (year == 2027 and month == 7)) and d <= date(2038, 1, 9) else 0.0
                if d <= date(2038, 1, 9):
                    schedule.append({"date": d, "coupon_tna": c_rate, "amort_pct": amort})
        return schedule

    # AL41 / GD41:
    # Vencimiento: 09/07/2041. Amortización semestral desde Ene-28 (28 cuotas).
    if ticker_base in ("AL41", "GD41"):
        schedule = []
        for year in range(2025, 2042):
            c_rate = 0.04875 if year >= 2028 else 0.035
            for month in (1, 7):
                d = date(year, month, 9)
                amort = 3.571 if year >= 2028 and d <= date(2041, 7, 9) else 0.0
                if d <= date(2041, 7, 9):
                    schedule.append({"date": d, "coupon_tna": c_rate, "amort_pct": amort})
        return schedule

    # GD46:
    # Vencimiento: 09/07/2046. Amortización semestral desde Ene-27.
    if ticker_base == "GD46":
        schedule = []
        for year in range(2025, 2047):
            c_rate = 0.04875 if year >= 2028 else 0.035
            for month in (1, 7):
                d = date(year, month, 9)
                amort = 2.5 if year >= 2027 and d <= date(2046, 7, 9) else 0.0
                if d <= date(2046, 7, 9):
                    schedule.append({"date": d, "coupon_tna": c_rate, "amort_pct": amort})
        return schedule

    return []


def generate_cashflows(
    ticker: str,
    settlement_date: date,
    maturity_date: date,
    coupon_rate: Optional[float] = None,
    frequency: int = 2,
    base_nominal: float = 100.0,
    is_bullet: bool = True
) -> List[CashFlowItem]:
    """
    Genera el vector futuro de flujos de fondos desde la fecha de liquidación hasta el vencimiento.
    Calcula residuales de capital, intereses corridos devengados y cupones futuros.
    """
    # 1. Verificar si existe cronograma específico de reestructuración Hard Dollar
    specific_schedule = get_hard_dollar_schedule(ticker)
    
    cashflows: List[CashFlowItem] = []
    
    if specific_schedule:
        # Calcular el capital residual histórico hasta la fecha de liquidación
        current_residual = base_nominal
        for event in specific_schedule:
            event_date = event["date"]
            amort_pct = event["amort_pct"]
            if event_date <= settlement_date:
                current_residual -= (amort_pct / 100.0) * base_nominal
                current_residual = max(0.0, current_residual)
        
        # Generar flujos futuros posteriores a la fecha de liquidación
        for event in specific_schedule:
            event_date = event["date"]
            if event_date <= settlement_date:
                continue
            
            c_rate = event["coupon_tna"]
            amort_pct = event["amort_pct"]
            
            # El cupón se paga sobre el residual vigente antes de la amortización de este período
            coupon_amount = current_residual * (c_rate / frequency)
            amort_amount = (amort_pct / 100.0) * base_nominal
            total_cf = coupon_amount + amort_amount
            
            current_residual = max(0.0, current_residual - amort_amount)
            days = (event_date - settlement_date).days
            
            cashflows.append(
                CashFlowItem(
                    date=event_date,
                    days_from_settlement=days,
                    interest_rate=c_rate,
                    coupon_amount=coupon_amount,
                    amortization_amount=amort_amount,
                    total_cashflow=total_cf,
                    residual_capital=current_residual
                )
            )
        return cashflows

    # 2. Flujos para bonos genéricos Bullet (ej. BONCER, Letras, BONCAPs, BOPREAL Bullet)
    coupon_tna = float(coupon_rate) if coupon_rate is not None else 0.0
    
    if frequency <= 0:
        frequency = 1

    # Fechas de cupones regulares hacia atrás desde vencimiento
    coupon_dates: List[date] = []
    curr_d = maturity_date
    months_step = 12 // frequency

    while curr_d > settlement_date:
        coupon_dates.append(curr_d)
        # Retroceder según frecuencia
        year_prev = curr_d.year
        month_prev = curr_d.month - months_step
        if month_prev <= 0:
            month_prev += 12
            year_prev -= 1
        try:
            curr_d = date(year_prev, month_prev, min(curr_d.day, 28))
        except Exception:
            curr_d = date(year_prev, month_prev, 28)

    coupon_dates.sort()

    for idx, c_date in enumerate(coupon_dates):
        is_last = (c_date == maturity_date) or (idx == len(coupon_dates) - 1)
        coupon_amt = base_nominal * (coupon_tna / frequency)
        amort_amt = base_nominal if is_last else 0.0
        total_cf = coupon_amt + amort_amt
        days = (c_date - settlement_date).days
        res_cap = 0.0 if is_last else base_nominal

        cashflows.append(
            CashFlowItem(
                date=c_date,
                days_from_settlement=days,
                interest_rate=coupon_tna,
                coupon_amount=coupon_amt,
                amortization_amount=amort_amt,
                total_cashflow=total_cf,
                residual_capital=res_cap
            )
        )

    return cashflows
