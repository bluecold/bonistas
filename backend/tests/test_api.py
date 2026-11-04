import pytest
from fastapi.testclient import TestClient
from backend.main import app
from backend.app.db.session import engine, Base

@pytest.fixture(scope="module", autouse=True)
def setup_test_db():
    Base.metadata.create_all(bind=engine)
    yield

@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client

def test_api_health(client):
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "service" in data

def test_api_bonds(client):
    response = client.get("/api/v1/bonds")
    assert response.status_code == 200
    bonds = response.json()
    assert len(bonds) > 0
    tickers = [b["ticker"] for b in bonds]
    assert "AL30" in tickers
    assert "GD30" in tickers

def test_api_bonds_filter_by_type(client):
    response = client.get("/api/v1/bonds?bond_type=HARD_DOLLAR")
    assert response.status_code == 200
    bonds = response.json()
    assert len(bonds) > 0
    assert all(b["bond_type"] == "HARD_DOLLAR" for b in bonds)

def test_api_quotes(client):
    response = client.get("/api/v1/quotes")
    assert response.status_code == 200
    quotes = response.json()
    assert isinstance(quotes, list)

def test_api_macro(client):
    response = client.get("/api/v1/macro")
    assert response.status_code == 200
    macro = response.json()
    assert isinstance(macro, dict)

def test_api_bond_cashflows(client):
    response = client.get("/api/v1/bonds/AL30/cashflows")
    assert response.status_code == 200
    cfs = response.json()
    assert len(cfs) > 0
    assert "total_cashflow" in cfs[0]
    assert "residual_capital" in cfs[0]

def test_api_calculator_valuation(client):
    payload = {
        "ticker": "AL30",
        "price": 52.72,
        "settlement_date": "2026-11-04"
    }
    response = client.post("/api/v1/calculator/valuation", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["residual_capital"] == 64.0
    assert 64.10 < data["technical_value"] < 64.20
    assert 82.0 < data["parity_percentage"] < 82.3
    assert data["ytm_percentage"] is not None
    assert 10.0 < data["ytm_percentage"] < 30.0
    assert data["modified_duration"] is not None

def test_api_breakeven_arbitrage(client):
    response = client.get("/api/v1/arbitrage/breakeven?fixed_ytm=26.8&cer_ytm=7.5")
    assert response.status_code == 200
    data = response.json()
    assert 17.0 < data["breakeven_annual_percentage"] < 19.0
    assert 1.2 < data["breakeven_monthly_percentage"] < 1.6
    assert "inflación mensual" in data["description"]

def test_api_law_spreads(client):
    response = client.get("/api/v1/arbitrage/law-spreads")
    assert response.status_code == 200
    pairs = response.json()
    assert len(pairs) == 5
    tickers = [p["al_ticker"] for p in pairs]
    assert "AL30" in tickers
    assert "AL29" in tickers

def test_api_swap_calculator(client):
    payload = {
        "sell_ticker": "GD30",
        "buy_ticker": "AL30",
        "sell_nominal": 10000.0,
        "broker_commission_pct": 0.5,
        "byma_fee_pct": 0.04
    }
    response = client.post("/api/v1/calculator/swap", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["sell_ticker"] == "GD30"
    assert data["buy_ticker"] == "AL30"
    assert data["sell_nominal"] == 10000.0
    assert data["buy_nominal_acquired"] > 0
    assert data["nominal_expansion_ratio"] > 0
    assert "summary_message" in data

def test_api_serve_dashboard(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "Bonistas Trading" in response.text
    assert "Plotly" in response.text
