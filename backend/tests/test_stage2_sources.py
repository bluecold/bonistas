"""
Tests de la etapa 2: BYMA Open Data, CompararBonos, BCRA, calendario de mercado y
almacenamiento solo de cambios. Todo offline (fixtures reales recortados del 04-nov-2026).
"""

import asyncio
from datetime import date, datetime, time

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from backend.app.data.byma_client import (
    BymaClient, parse_bond_rows, pick_overnight_caucion, species_base,
)
from backend.app.data.bcra_client import latest_on_or_before
from backend.app.db.models import BookQuote, MacroIndicator
from backend.app.db.session import Base
from backend.app.services.market_book_service import MarketBookService
from backend.app.services.market_calendar import ART, MarketWindow, next_business_day

from backend.tests.conftest import _load


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine)()
    try:
        yield db
    finally:
        db.close()


# ---------------------------------------------------------------------------
# BYMA: especies, plazos y monedas
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("symbol,currency,expected", [
    ("AL30", "ARS", "AL30"),
    ("AL30D", "MEP", "AL30"),
    ("AL30C", "CCL", "AL30"),
    ("GD30D", "MEP", "GD30"),
    ("BPA7D", "MEP", "BPOA7"),   # BOPREAL: la especie en pesos tiene otro ticker
    ("BPA7C", "CCL", "BPOA7"),
    ("TZXD6", "ARS", "TZXD6"),   # en pesos nunca se recorta
])
def test_species_base(symbol, currency, expected):
    assert species_base(symbol, currency) == expected


def test_parse_bond_rows_maps_settlement_and_currency():
    rows = {(r.symbol, r.settlement): r for r in parse_bond_rows(_load("byma_public_bonds.json")["data"])}
    ci_ars, h24_mep, h24_ccl = rows[("AL30", "CI")], rows[("AL30D", "24HS")], rows[("AL30C", "24HS")]
    assert (ci_ars.currency, h24_mep.currency, h24_ccl.currency) == ("ARS", "MEP", "CCL")
    assert {ci_ars.base_ticker, h24_mep.base_ticker, h24_ccl.base_ticker} == {"AL30"}
    # Valores reales del cierre del 04-nov-2026
    assert (ci_ars.bid, ci_ars.ask, ci_ars.last) == (82920, 83390, 83380)
    assert (h24_mep.bid, h24_mep.bid_qty, h24_mep.ask, h24_mep.ask_qty) == (52.5, 1968, 52.75, 78)
    assert ci_ars.trade_time == "17:00:16"


def test_parse_bond_rows_turns_zeros_into_none():
    rows = {r.symbol: r for r in parse_bond_rows(_load("byma_public_bonds.json")["data"])}
    z = rows["ZZ99"]
    assert z.bid is None and z.ask is None and z.last is None


def test_pick_overnight_caucion():
    c = pick_overnight_caucion(_load("byma_cauciones.json"))
    assert c["days"] == 1
    assert c["tna_pct"] == pytest.approx(26.1)
    assert c["bid_pct"] == pytest.approx(22.6)


# ---------------------------------------------------------------------------
# Almacenamiento solo de cambios
# ---------------------------------------------------------------------------

def test_books_are_stored_only_when_they_change(db_session):
    svc = MarketBookService()
    rows = parse_bond_rows(_load("byma_public_bonds.json")["data"])

    first = svc.store_rows(db_session, rows, "BYMA")
    assert first["stored"] > 0 and first["empty"] == 1   # ZZ99 sin precio se descarta

    second = svc.store_rows(db_session, rows, "BYMA")
    assert second["stored"] == 0 and second["unchanged"] == first["stored"]

    rows[0].bid = (rows[0].bid or 1) + 1                 # cambia una sola punta
    third = svc.store_rows(db_session, rows, "BYMA")
    assert third["stored"] == 1


def test_book_cache_survives_restart(db_session):
    """Un servicio nuevo (reinicio) no vuelve a guardar lo que ya está en la base."""
    rows = parse_bond_rows(_load("byma_public_bonds.json")["data"])
    MarketBookService().store_rows(db_session, rows, "BYMA")
    again = MarketBookService().store_rows(db_session, rows, "BYMA")
    assert again["stored"] == 0


def test_ingest_byma_stores_caucion_as_macro(db_session):
    result = asyncio.run(MarketBookService(BymaClient()).ingest_byma(db_session))
    assert result["books"]["stored"] > 0
    macro = db_session.execute(
        select(MacroIndicator).where(MacroIndicator.name == "CAUCION_1D_TNA")
    ).scalar_one()
    assert float(macro.value) == pytest.approx(26.1)
    assert macro.source == "BYMA"


def test_bonistas_snapshots_only_on_change(client):
    again = client.post("/api/v1/ingest").json()["details"]
    assert again["snapshots_created"] == 0
    assert again["unchanged"] > 0
    assert again["byma"]["books"]["stored"] == 0


# ---------------------------------------------------------------------------
# Calendario de mercado
# ---------------------------------------------------------------------------

def _at(h, m, d=date(2026, 11, 4)):
    return datetime(d.year, d.month, d.day, h, m, tzinfo=ART)


@pytest.mark.parametrize("now,expected", [
    (_at(9, 0), False),
    (_at(10, 26), True),     # 5 min antes de la apertura
    (_at(13, 0), True),
    (_at(17, 20), True),     # BYMA publica con 20 min de demora
    (_at(17, 40), False),
])
def test_market_window(now, expected):
    w = MarketWindow(date(2026, 11, 4), True, time(10, 30), time(17, 0), "BYMA")
    assert w.is_open_for_polling(now) is expected


def test_market_window_holiday():
    w = MarketWindow(date(2026, 11, 4), False, time(10, 30), time(17, 0), "BYMA")
    assert w.is_open_for_polling(_at(13, 0)) is False


def test_next_business_day_skips_weekend():
    assert next_business_day(date(2026, 11, 6)) == date(2026, 11, 9)   # viernes -> lunes
    assert next_business_day(date(2026, 11, 4)) == date(2026, 11, 5)


def test_scheduled_job_does_nothing_outside_market_hours(monkeypatch):
    import backend.main as main

    async def closed(*a, **k):
        return False

    async def must_not_run(db):
        raise AssertionError("no debía consultar fuentes fuera de horario")

    monkeypatch.setattr(main.market_calendar, "should_poll", closed)
    monkeypatch.setattr(main, "run_market_cycle", must_not_run)
    asyncio.run(main.scheduled_ingestion_job())


# ---------------------------------------------------------------------------
# BCRA
# ---------------------------------------------------------------------------

def test_bcra_ignores_future_dates():
    detalle = [{"fecha": "2026-11-15", "valor": 870.7}, {"fecha": "2026-11-04", "valor": 867.5},
               {"fecha": "2026-11-03", "valor": 867.2}]
    item = latest_on_or_before(detalle, date(2026, 11, 4))
    assert item == {"fecha": date(2026, 11, 4), "valor": 867.5}


def test_reference_refresh_stores_bcra_macro(client):
    macro = client.get("/api/v1/macro").json()
    assert macro["CER"]["source"] == "BCRA"
    assert macro["TAMAR"]["value"] == 24.0
    assert macro["A3500"]["date"] == "2026-11-04"


# ---------------------------------------------------------------------------
# CompararBonos: valuación y flujos de instrumentos sin cronograma propio
# ---------------------------------------------------------------------------

def test_reference_endpoint_resolves_species(client):
    data = client.get("/api/v1/reference/AL30D").json()
    assert data["ticker_base"] == "AL30"
    assert {"AL30", "AL30D", "AL30C"} <= set(data["species"])


def test_lecap_valuation_from_reference_flows(client):
    res = client.post("/api/v1/calculator/valuation",
                      json={"ticker": "S30N6", "price": 127.85, "settlement_date": "2026-11-05"})
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["source"] == "COMPARARBONOS"
    assert data["ytm_percentage"] == pytest.approx(25.97, abs=0.3)   # TIR de referencia de mercado


def test_cer_valuation_is_real_yield(client):
    res = client.post("/api/v1/calculator/valuation",
                      json={"ticker": "TZX27", "price": 418.25, "settlement_date": "2026-11-05"})
    data = res.json()
    assert data["yield_is_real"] is True
    assert data["ytm_percentage"] == pytest.approx(3.69, abs=0.1)
    assert data["technical_value"] == pytest.approx(428.22)
    assert data["parity_percentage"] == pytest.approx(97.67, abs=0.05)


def test_reference_cashflows_only_total(client):
    cfs = client.get("/api/v1/bonds/S30N6/cashflows?settlement_date=2026-11-05").json()
    assert len(cfs) == 1
    assert cfs[0]["source"] == "COMPARARBONOS"
    assert cfs[0]["total_cashflow"] == pytest.approx(129.888)
    assert cfs[0]["coupon_amount"] is None


def test_verified_schedule_still_preferred(client):
    cfs = client.get("/api/v1/bonds/AL30/cashflows?settlement_date=2026-11-05").json()
    assert cfs[0]["source"] == "PROPIO"
    assert cfs[0]["coupon_amount"] == pytest.approx(0.24)


# ---------------------------------------------------------------------------
# Endpoints nuevos
# ---------------------------------------------------------------------------

def test_books_endpoint_groups_species(client):
    books = client.get("/api/v1/books?base_ticker=AL30").json()
    assert {(b["symbol"], b["settlement"]) for b in books} == {
        (s, st) for s in ("AL30", "AL30D", "AL30C") for st in ("CI", "24HS")
    }
    ci = client.get("/api/v1/books?base_ticker=AL30&settlement=CI").json()
    assert {b["settlement"] for b in ci} == {"CI"}


def test_status_endpoint(client):
    status = client.get("/api/v1/status").json()
    assert status["market"]["is_working_day"] is True
    for name in ("BYMA", "COMPARARBONOS", "BCRA", "BONISTAS"):
        assert status["sources"][name]["healthy"] is True, name


def test_put_and_tamar_scenarios_do_not_overwrite_base_bond(client):
    """BPOA8_PUT (TIR 27,4%) no debe pisar la TIR del escenario base de BPOA8 (9,26%)."""
    quotes = {q["ticker"]: q for q in client.get("/api/v1/quotes").json()}
    assert quotes["BPOA8"]["ytm_percentage"] == pytest.approx(9.2616, abs=0.01)
    assert "BPOA8_PUT" not in quotes
