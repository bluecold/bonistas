"""
Tests de regresión de la etapa 1 (correcciones de la revisión de nov-2026).

Los valores de referencia de mercado salen de CompararBonos / Bonistas al 04-nov-2026
(liquidación 24hs = 05-nov-2026).
"""

from datetime import date
from decimal import Decimal

import pytest

from backend.app.quant import (
    generate_cashflows,
    get_hard_dollar_schedule,
    calculate_accrued_interest,
    calculate_residual_capital,
    calculate_technical_value,
    calculate_ytm,
    calculate_duration_and_md,
)
from backend.app.quant.cashflows import base_ticker, has_verified_schedule
from backend.app.quant.fixed_income import days_30_360
from backend.app.schemas.snapshot import BondQuoteView
from backend.app.arbitrage.strategies import ArbitrageStrategies

SETTLE_24HS = date(2026, 11, 5)


# ---------------------------------------------------------------------------
# Tickers y especies
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("ticker,expected", [
    ("GD30", "GD30"),     # antes: "G30" (se borraban todas las D)
    ("GD30D", "GD30"),
    ("GD30C", "GD30"),
    ("AL30D", "AL30"),
    ("AE38C", "AE38"),
    ("DICP", "DICP"),     # antes: "IP"
    ("BPA7D", "BPA7D"),   # no es hard dollar 2020: no se toca
    ("S30N6", "S30N6"),
])
def test_base_ticker(ticker, expected):
    assert base_ticker(ticker) == expected


@pytest.mark.parametrize("al,gd", [("AL29", "GD29"), ("AL30", "GD30"), ("AL35", "GD35"),
                                   ("AE38", "GD38"), ("AL41", "GD41")])
def test_gd_and_al_share_schedule(al, gd):
    """AL y GD (y sus especies D/C) tienen exactamente los mismos flujos."""
    assert get_hard_dollar_schedule(gd), f"{gd} no encontró cronograma"
    assert get_hard_dollar_schedule(gd) == get_hard_dollar_schedule(al)
    assert get_hard_dollar_schedule(gd + "D") == get_hard_dollar_schedule(al)
    assert get_hard_dollar_schedule(gd + "C") == get_hard_dollar_schedule(al)


@pytest.mark.parametrize("ticker", ["AL29", "AL30", "AL35", "AE38", "AL41", "GD46"])
def test_amortizations_sum_100(ticker):
    total = sum(e["amort_pct"] for e in get_hard_dollar_schedule(ticker))
    assert total == pytest.approx(100.0, abs=1e-9)


# ---------------------------------------------------------------------------
# Cronogramas verificados contra el mercado
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("ticker,residual", [
    ("AL30", 64.0), ("GD30", 64.0), ("AL29", 60.0), ("AL35", 100.0),
    ("AE38", 100.0), ("AL41", 100.0), ("GD46", 90.9091),
])
def test_residual_capital_matches_market(ticker, residual):
    assert calculate_residual_capital(ticker, SETTLE_24HS) == pytest.approx(residual, abs=1e-4)


@pytest.mark.parametrize("ticker,first_flows", [
    # (fecha, flujo total) según CompararBonos
    ("AL30", [(date(2027, 1, 9), 8.24), (date(2027, 7, 9), 8.21), (date(2028, 1, 9), 8.42)]),
    ("AL29", [(date(2027, 1, 9), 10.30), (date(2027, 7, 9), 10.25)]),
    ("AL35", [(date(2027, 1, 9), 2.0625), (date(2028, 1, 9), 2.375), (date(2029, 1, 9), 2.50)]),
    ("AE38", [(date(2027, 1, 9), 2.50), (date(2027, 7, 9), 7.0455)]),
    ("AL41", [(date(2027, 1, 9), 1.75), (date(2028, 1, 9), 5.3214)]),
    ("GD46", [(date(2027, 1, 9), 4.1477), (date(2028, 1, 9), 4.1619), (date(2029, 1, 9), 4.3182)]),
])
def test_cashflows_match_market(ticker, first_flows):
    cfs = {cf.date: cf.total_cashflow for cf in generate_cashflows(ticker, SETTLE_24HS, date(2046, 7, 9))}
    for d, amount in first_flows:
        assert cfs[d] == pytest.approx(amount, abs=1e-3), f"{ticker} {d}"


def test_al30_step_up_applies_from_jan_2028():
    """El pago de jul-27 todavía devenga 0,75%; el 1,75% se paga recién desde ene-28."""
    rates = {e["date"]: e["coupon_tna"] for e in get_hard_dollar_schedule("AL30")}
    assert rates[date(2027, 7, 9)] == 0.0075
    assert rates[date(2028, 1, 9)] == 0.0175


def test_flow_on_settlement_date_is_excluded():
    """Si liquido el mismo día del pago, ese flujo ya no me corresponde (precio ex-cupón)."""
    cfs = generate_cashflows("AL30", date(2027, 1, 9), date(2030, 7, 9))
    assert cfs[0].date == date(2027, 7, 9)
    assert calculate_residual_capital("AL30", date(2027, 1, 9)) == 56.0


# ---------------------------------------------------------------------------
# Intereses corridos, TIR y duration
# ---------------------------------------------------------------------------

def test_days_30_360():
    assert days_30_360(date(2026, 7, 9), date(2026, 11, 5)) == 116
    assert days_30_360(date(2026, 1, 31), date(2026, 3, 31)) == 60


def test_technical_value_30_360_matches_market():
    """VT del AL30 al 05-nov-2026 = 64,1547 (igual que Bonistas y CompararBonos)."""
    accrued = calculate_accrued_interest("AL30D", SETTLE_24HS)
    vt = calculate_technical_value(calculate_residual_capital("AL30D", SETTLE_24HS), accrued)
    assert vt == pytest.approx(64.1547, abs=1e-4)


@pytest.mark.parametrize("ticker,price,expected_tir", [
    ("AL30D", 52.50, 13.18),
    ("GD30D", 54.39, 10.94),
])
def test_ytm_matches_market(ticker, price, expected_tir):
    cfs = generate_cashflows(ticker, SETTLE_24HS, date(2030, 7, 9))
    ytm = calculate_ytm(price, cfs)
    assert ytm * 100 == pytest.approx(expected_tir, abs=0.02)


def test_modified_duration_consistent_with_effective_ytm():
    cfs = generate_cashflows("AL30", SETTLE_24HS, date(2030, 7, 9))
    ytm = calculate_ytm(52.5, cfs)
    mac, md = calculate_duration_and_md(52.5, ytm, cfs)
    assert mac == pytest.approx(1.76, abs=0.01)          # Macaulay de CompararBonos
    assert md == pytest.approx(mac / (1 + ytm), abs=1e-3)


def test_generic_accrued_uses_last_real_coupon():
    """Antes se usaban siempre 30 días fijos, sin importar la fecha."""
    maturity = date(2027, 5, 30)
    a1 = calculate_accrued_interest("XX27", date(2026, 12, 1), coupon_rate=0.10, maturity_date=maturity)
    a2 = calculate_accrued_interest("XX27", date(2027, 3, 1), coupon_rate=0.10, maturity_date=maturity)
    assert a1 == pytest.approx(100 * 0.10 * 1 / 365, abs=1e-3)     # 1 día desde el cupón del 30-nov
    assert a2 > a1


def test_only_hard_dollar_2020_have_verified_schedule():
    assert has_verified_schedule("GD30D")
    assert not has_verified_schedule("S30N6")
    assert not has_verified_schedule("TZX27")


# ---------------------------------------------------------------------------
# Estrategias
# ---------------------------------------------------------------------------

def _hd(ticker, law, **kw):
    return BondQuoteView(ticker=ticker, name=ticker, bond_type="HARD_DOLLAR", law=law,
                         settlement_type="24HS", **kw)


def test_law_premium_never_mixes_pesos_with_dollars():
    """Sin precio MEP en una pata no hay ratio (antes caía a last_price en pesos -> ratio ~1500)."""
    quotes = {
        "AL30": _hd("AL30", "ARG", price_mep=None, last_price=83380.0, ytm_percentage=13.0),
        "GD30": _hd("GD30", "NY", price_mep=54.39, last_price=54.39, ytm_percentage=10.9),
    }
    assert ArbitrageStrategies.evaluate_law_premium(quotes) == []


def test_relative_value_does_not_fire_in_normal_conditions():
    """Spread de 150 bps está por DEBAJO de la media (180): no es una oportunidad."""
    quotes = {
        "AL30": _hd("AL30", "ARG", price_mep=52.5, ytm_percentage=12.0),
        "GD29": _hd("GD29", "NY", price_mep=53.5, ytm_percentage=10.5),
    }
    assert ArbitrageStrategies.evaluate_relative_value_curve(quotes) == []


def test_relative_value_fires_on_abnormal_spread():
    quotes = {
        "AL30": _hd("AL30", "ARG", price_mep=52.5, ytm_percentage=13.0),
        "GD29": _hd("GD29", "NY", price_mep=53.5, ytm_percentage=10.0),   # 300 bps: z = +2,67
    }
    signals = ArbitrageStrategies.evaluate_relative_value_curve(quotes)
    assert len(signals) == 1
    assert signals[0].std_deviations > Decimal("1.1")
    assert "+2.67" in signals[0].notes


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

def test_cashflows_endpoint_gd30_is_not_bullet(client):
    res = client.get("/api/v1/bonds/GD30/cashflows?settlement_date=2026-11-05")
    assert res.status_code == 200
    cfs = res.json()
    assert len(cfs) == 8
    assert cfs[0]["amortization_amount"] == pytest.approx(8.0)


def test_cashflows_endpoint_accepts_species_suffix(client):
    res = client.get("/api/v1/bonds/GD30D/cashflows?settlement_date=2026-11-05")
    assert res.status_code == 200
    assert len(res.json()) == 8


def test_valuation_rejects_instruments_without_flows(client):
    """Los duales no publican flujos proyectables: 422 en lugar de inventarlos."""
    res = client.post("/api/v1/calculator/valuation", json={"ticker": "TXMJ0", "price": 86.4})
    assert res.status_code == 422
    assert "Sin flujos" in res.json()["detail"]


def test_swap_unknown_ticker_returns_404_instead_of_fake_prices(client):
    res = client.post("/api/v1/calculator/swap", json={"sell_ticker": "NOEXISTE", "buy_ticker": "AL30"})
    assert res.status_code == 404


def test_swap_rejects_legs_without_common_currency(client):
    # BPA7D solo cotiza en dólares y S30N6 solo en pesos
    res = client.post("/api/v1/calculator/swap", json={"sell_ticker": "BPA7D", "buy_ticker": "S30N6"})
    assert res.status_code == 422


def test_swap_uses_mep_prices_and_respects_zero_fees(client):
    res = client.post("/api/v1/calculator/swap", json={
        "sell_ticker": "GD30", "buy_ticker": "AL30", "sell_nominal": 1000,
        "broker_commission_pct": 0, "byma_fee_pct": 0,
    })
    assert res.status_code == 200
    data = res.json()
    assert data["currency"] == "USD"
    assert data["sell_price"] < 100           # precio MEP, no en pesos
    assert data["sell_fees"] == 0.0


def test_swap_default_cost_is_011_pct(client):
    res = client.post("/api/v1/calculator/swap", json={"sell_ticker": "GD30", "buy_ticker": "AL30",
                                                         "sell_nominal": 1000})
    data = res.json()
    assert data["sell_fees"] == pytest.approx(data["sell_gross_amount"] * 0.0011, abs=0.01)


def test_quotes_do_not_mix_settlements(client):
    ci = client.get("/api/v1/quotes?settlement=CI").json()
    h24 = client.get("/api/v1/quotes?settlement=24HS").json()
    assert ci and h24
    assert {q["settlement_type"] for q in ci} == {"CI"}
    assert {q["settlement_type"] for q in h24} == {"24HS"}


def test_ingestion_skips_rows_without_price(client):
    """Las filas con precio 0 (sin operaciones) no se guardan como cotización."""
    res = client.post("/api/v1/ingest").json()
    assert res["details"]["skipped_without_price"] > 0
    for q in client.get("/api/v1/quotes?settlement=CI").json() + client.get("/api/v1/quotes").json():
        assert any((q["last_price"], q["price_ars"], q["price_mep"], q["price_ccl"]))


def test_breakeven_without_data_is_rejected(client):
    res = client.get("/api/v1/arbitrage/breakeven?fixed_ticker=NOEXISTE")
    assert res.status_code == 422


def test_macro_failure_persists_nothing(monkeypatch):
    """Si la API de inflación falla, no se inventa un IPC de 2,4%."""
    import asyncio
    from backend.app.data import macro_connectors

    class Boom:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): raise RuntimeError("sin red")
        async def __aexit__(self, *a): return False

    monkeypatch.setattr(macro_connectors.httpx, "AsyncClient", Boom)
    connector = macro_connectors.MacroDataConnector()
    assert asyncio.run(connector.fetch_latest_inflation()) is None
