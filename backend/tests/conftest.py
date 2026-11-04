"""
Configuración común de tests.

Objetivos:
1. NUNCA tocar la base real (`bonistas.db`): se usa una SQLite temporal por sesión de tests.
2. No depender de internet: las fuentes externas se reemplazan por los fixtures JSON de
   `backend/tests/fixtures/`. Los tests marcados con `@pytest.mark.network` usan las APIs
   reales y solo corren con la variable de entorno RUN_NETWORK_TESTS=1.
3. No arrancar el scheduler ni la ingesta automática al levantar la app.

Las variables de entorno se fijan ANTES de importar cualquier módulo de `backend`, porque
la configuración y el engine de SQLAlchemy se crean al importar.
"""

import json
import os
import tempfile
from decimal import Decimal
from pathlib import Path

_TMP_DIR = tempfile.mkdtemp(prefix="bonistas_tests_")
os.environ["DATABASE_URL"] = f"sqlite:///{Path(_TMP_DIR, 'test.db').as_posix()}"
os.environ["DISABLE_SCHEDULER"] = "true"
os.environ["SKIP_STARTUP_INGESTION"] = "true"

import pytest  # noqa: E402

from backend.app.data.bonistas_client import BonistasClient  # noqa: E402
from backend.app.data.dolar_api_client import DolarApiClient  # noqa: E402
from backend.app.data.macro_connectors import MacroDataConnector  # noqa: E402
from backend.app.schemas.macro import MacroIndicatorCreate  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"
RUN_NETWORK = os.environ.get("RUN_NETWORK_TESTS") == "1"

SAMPLE_DOLARES = {
    "oficial": 1570.0, "blue": 1560.0, "bolsa": 1588.6,
    "contadoconliqui": 1680.4, "mayorista": 1546.0,
}


def _load(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def pytest_configure(config):
    config.addinivalue_line("markers", "network: usa APIs externas reales (requiere RUN_NETWORK_TESTS=1)")


def pytest_collection_modifyitems(config, items):
    if RUN_NETWORK:
        return
    skip = pytest.mark.skip(reason="Test de red: ejecutar con RUN_NETWORK_TESTS=1")
    for item in items:
        if "network" in item.keywords:
            item.add_marker(skip)


def _install_offline_sources(monkeypatch):
    bonds = _load("sample_bonds.json")
    fx = _load("sample_fx.json")

    async def fake_fetch_bonds(self):
        return bonds

    async def fake_fetch_fx(self):
        return fx

    async def fake_rates(self):
        return dict(SAMPLE_DOLARES)

    async def fake_macro(self):
        from datetime import date
        return {
            "IPC": MacroIndicatorCreate(
                date=date(2026, 10, 1), name="IPC", value=Decimal("1.9"), source="TEST_FIXTURE"
            )
        }

    monkeypatch.setattr(BonistasClient, "fetch_bonds", fake_fetch_bonds)
    monkeypatch.setattr(BonistasClient, "fetch_fx", fake_fetch_fx)
    monkeypatch.setattr(DolarApiClient, "get_rates_dict", fake_rates)
    monkeypatch.setattr(MacroDataConnector, "fetch_macro_snapshot", fake_macro)


@pytest.fixture(autouse=True)
def offline_sources(request, monkeypatch):
    """Reemplaza las fuentes externas por datos de fixtures (salvo en tests de red)."""
    if request.node.get_closest_marker("network"):
        return
    _install_offline_sources(monkeypatch)


@pytest.fixture(scope="module")
def client():
    """Cliente HTTP de la app con datos de mercado cargados desde los fixtures (uno por módulo)."""
    from fastapi.testclient import TestClient
    from backend.main import app

    with pytest.MonkeyPatch.context() as mp:
        _install_offline_sources(mp)
        with TestClient(app) as test_client:
            res = test_client.post("/api/v1/ingest")
            assert res.status_code == 200, res.text
            yield test_client
