import pytest
from datetime import date
from backend.app.quant import (
    generate_cashflows,
    calculate_accrued_interest,
    calculate_residual_capital,
    calculate_technical_value,
    calculate_parity,
    calculate_ytm,
    calculate_duration_and_md,
    calculate_tem,
    calculate_tna,
    calculate_implied_fx,
    calculate_breakeven_inflation,
    calculate_law_spread,
    calculate_z_score
)

def test_al30_cashflow_generation():
    """Verifica que el generador de flujos de fondos de AL30/GD30 respete el cronograma 2020."""
    settlement = date(2026, 11, 4)
    maturity = date(2030, 7, 9)
    
    cfs = generate_cashflows("AL30", settlement, maturity)
    assert len(cfs) > 0
    
    # El primer flujo futuro debe ser Enero 2027 (o el siguiente cupón post Nov 2026)
    first_cf = cfs[0]
    assert first_cf.date == date(2027, 1, 9)
    assert first_cf.amortization_amount == 8.0
    assert first_cf.interest_rate == 0.0075
    
    # El último flujo debe ser en julio 2030
    last_cf = cfs[-1]
    assert last_cf.date == date(2030, 7, 9)
    assert last_cf.residual_capital == 0.0

def test_technical_value_and_parity():
    """Verifica el cálculo de Valor Técnico y Paridad %."""
    settlement = date(2026, 11, 4)
    # AL30 residual al 4 de noviembre de 2026: 64.0 (36% amortizado acumulado)
    res = calculate_residual_capital("AL30", settlement)
    assert res == 64.0
    
    accrued = calculate_accrued_interest("AL30", settlement)
    assert 0.15 < accrued < 0.16 # ~0.1546
    
    vt = calculate_technical_value(res, accrued)
    assert 64.15 < vt < 64.16 # Coincide exactamente con el fair_value de pantalla profesional (64.1546)
    
    # Paridad a precio de mercado USD 52.72
    parity = calculate_parity(52.72, vt)
    assert 82.10 < parity < 82.25 # Coincide exactamente con la paridad reportada (82.18%)

def test_ytm_solver_newton_and_brent():
    """Verifica la resolución numérica de la TIR (YTM) para AL30."""
    settlement = date(2026, 11, 4)
    maturity = date(2030, 7, 9)
    cfs = generate_cashflows("AL30", settlement, maturity)
    
    price = 54.50
    ytm = calculate_ytm(price, cfs)
    
    assert ytm is not None
    assert 0.10 < ytm < 0.35 # La TIR esperada de AL30 ronda 15%-25% anual en este rango de paridad
    
    # Con YTM conocido, calcular duración
    d_mac, md = calculate_duration_and_md(price, ytm, cfs)
    assert d_mac is not None and md is not None
    assert 1.0 < md < 3.0 # Modified duration de AL30 está en ~1.8-2.2 años

def test_tem_and_tna():
    """Verifica las conversiones de tasas TEM y TNA."""
    ytm = 0.2682 # ~26.82% anual
    tem = calculate_tem(ytm)
    assert 0.019 < tem < 0.021 # ~2.0% mensual
    
    tna = calculate_tna(tem)
    assert 0.23 < tna < 0.25

def test_implied_fx():
    """Verifica el cálculo de MEP, CCL y Canje."""
    # Ejemplo AL30: ARS 83370, USD MEP 52.71, CCL 49.63
    res = calculate_implied_fx(price_ars=83370.0, price_mep=52.71, price_ccl=49.63)
    assert 1580.0 < res["mep_implied"] < 1585.0
    assert 1675.0 < res["ccl_implied"] < 1685.0
    assert res["canje_pct"] > 5.0 # Canje positivo (~6.1%)

def test_breakeven_inflation():
    """Verifica la ecuación Fisher para Breakeven entre Tasa Fija y CER."""
    # LECAP al 26.8% anual vs BONCER al 7.5% real anual
    fixed_ytm = 0.268
    cer_ytm = 0.075
    
    be = calculate_breakeven_inflation(fixed_ytm, cer_ytm)
    # Breakeven = (1.268 / 1.075) - 1 = 17.95% anual
    assert 0.17 < be["breakeven_annual"] < 0.19
    # Mensual = (1.1795)^(1/12) - 1 = ~1.38% mensual
    assert 0.012 < be["breakeven_monthly"] < 0.015

def test_law_spread_metrics():
    """Verifica el cálculo del spread de legislación entre GD30 y AL30."""
    price_gd = 54.49
    price_al = 52.71
    ytm_gd = 0.185
    ytm_al = 0.201
    
    spread = calculate_law_spread(price_gd, price_al, ytm_gd, ytm_al)
    assert spread["price_ratio"] == 1.0338 # 3.38% prima NY
    assert spread["price_spread_pct"] == 3.377
    assert spread["yield_spread_bps"] == 160.0 # 160 bps de diferencia AL vs GD

def test_z_score():
    """Verifica el cálculo de Z-score estadístico."""
    history = [1.02, 1.03, 1.035, 1.04, 1.045, 1.05, 1.055, 1.06]
    z_res = calculate_z_score(1.09, history)
    assert z_res["z_score"] is not None
    assert z_res["z_score"] > 2.0 # Desvío por encima de 2 sigmas
