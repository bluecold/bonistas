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
# Bull Market: nunca usar la cookie real del trader en los tests
os.environ["BULLMARKET_COOKIE_FILE"] = str(Path(_TMP_DIR, "secrets", "bullmarket_cookie.txt"))
os.environ["BULLMARKET_COOKIE"] = ""
# Nunca mostrar notificaciones reales de Windows al correr los tests
os.environ["WINDOWS_NOTIFICATIONS"] = "false"

import pytest  # noqa: E402

from backend.app.data.bonistas_client import BonistasClient  # noqa: E402
from backend.app.data.dolar_api_client import DolarApiClient  # noqa: E402
from backend.app.data.macro_connectors import MacroDataConnector  # noqa: E402
from backend.app.schemas.macro import MacroIndicatorCreate  # noqa: E402
from backend.app.data.byma_client import BymaClient, MarketTime  # noqa: E402
from backend.app.data.comparar_bonos_client import CompararBonosClient  # noqa: E402
from backend.app.data.bcra_client import BcraClient  # noqa: E402
from backend.app.data.bullmarket_client import BullMarketClient, SessionExpiredError  # noqa: E402

# Cookie de prueba aceptada por el Bull Market simulado (cualquier otra se trata como vencida)
TEST_BM_COOKIE = "ASP.NET_SessionId=test; .AspNetCore.Session=fixture"

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

    # --- Fuentes de la etapa 2 (respuestas reales recortadas, 04-nov-2026)
    byma_rows = _load("byma_public_bonds.json")["data"]
    cauciones = _load("byma_cauciones.json")
    comparar = _load("comparar_bonos.json")

    async def fake_books_raw(self):
        return [dict(r) for r in byma_rows]

    async def fake_cauciones(self):
        return cauciones

    async def fake_market_time(self):
        from datetime import time
        return MarketTime(is_working_day=True, opening=time(10, 30), closing=time(17, 0))

    async def fake_comparar(self):
        return comparar

    async def fake_bcra(self, today=None):
        from datetime import date
        return {
            "CER": MacroIndicatorCreate(date=date(2026, 11, 4), name="CER", value=Decimal("867.52"), source="BCRA"),
            "TAMAR": MacroIndicatorCreate(date=date(2026, 11, 3), name="TAMAR", value=Decimal("24.0"), source="BCRA"),
            "A3500": MacroIndicatorCreate(date=date(2026, 11, 4), name="A3500", value=Decimal("1548.49"), source="BCRA"),
        }

    monkeypatch.setattr(BymaClient, "fetch_bond_books_raw", fake_books_raw)
    monkeypatch.setattr(BymaClient, "fetch_cauciones_raw", fake_cauciones)
    monkeypatch.setattr(BymaClient, "fetch_market_time", fake_market_time)
    monkeypatch.setattr(CompararBonosClient, "fetch_raw", fake_comparar)
    monkeypatch.setattr(BcraClient, "fetch_latest", fake_bcra)

    # --- Bull Market (etapa 4): respuesta real recortada de 24hs; CI se simula con las mismas puntas
    bm_rows = _load("bullmarket_bonos_24hs.json")["result"]
    bm_on_rows = _load("bullmarket_on_24hs.json")["result"]     # índice obligacionesNegociables

    async def fake_bm_raw(self, cookie, term, index="bonos"):
        if cookie != TEST_BM_COOKIE:
            raise SessionExpiredError("Sesión de Bull Market vencida o inválida (HTTP 302).")
        rows = bm_on_rows if index == "obligacionesNegociables" else bm_rows
        return [dict(r, term=str(term)) for r in rows]

    monkeypatch.setattr(BullMarketClient, "fetch_raw", fake_bm_raw)

    # Cronogramas de Bull Market (respuesta real recortada: NDG34, TX28, BC37D, CO32, AL30)
    from backend.app.data import bullmarket_client as bmc
    bm_cf = _load("bullmarket_cashflows.json")

    async def fake_bm_cashflows(cookie, symbols, after, **kw):
        if cookie != TEST_BM_COOKIE:
            raise SessionExpiredError("Sesión de Bull Market vencida o inválida (HTTP 302).")
        wanted = {s.upper() for s in symbols}
        rows = [r for r in bm_cf["resultCashflowTable"] if r["symbol"] in wanted]
        return bmc.parse_cashflows({"resultCashflowTable": rows}, after)

    monkeypatch.setattr(bmc, "fetch_cashflows", fake_bm_cashflows)

    # --- Bruno618 (cronogramas de provinciales): ficha real recortada de CO32
    from backend.app.data.bruno618_client import Bruno618Client, parse_schedule
    co32_html = (FIXTURES / "bruno618_co32.html").read_text(encoding="utf-8")

    async def fake_bruno_schedules(self, tickers=None):
        return {"CO32": parse_schedule("CO32", co32_html)}, {}

    monkeypatch.setattr(Bruno618Client, "fetch_schedules", fake_bruno_schedules)

    # --- Mercados Argentina: ficha real recortada de SJ035 (San Juan 2035)
    from backend.app.data.mercados_argentina_client import MercadosArgentinaClient
    from backend.app.data.mercados_argentina_client import parse_schedule as ma_parse
    sj_html = (FIXTURES / "mercadosargentina_sj035.html").read_text(encoding="utf-8")

    async def fake_ma_schedules(self, after, tickers=None):
        return {"SJO35": ma_parse("SJO35", sj_html, after)}, {}

    monkeypatch.setattr(MercadosArgentinaClient, "fetch_schedules", fake_ma_schedules)

    # --- MAE: feriados (respuesta real del 05/11/2026)
    from backend.app.data.mae_client import MaeClient
    mae = _load("mae_feriados.json")

    async def fake_mae(self):
        return [dict(x) for x in mae]

    monkeypatch.setattr(MaeClient, "fetch_raw", fake_mae)

    # --- Ficha del bono: sin historia de Rava ni serie del CER salvo que el test las cargue
    from backend.app.data.rava_client import RavaClient

    async def fake_rava_text(self, symbol):
        return ""

    async def fake_bcra_series(self, name, since, until):
        return []

    monkeypatch.setattr(RavaClient, "fetch_text", fake_rava_text)
    monkeypatch.setattr(BcraClient, "fetch_series", fake_bcra_series)

    # Red de seguridad: aunque algún test construya un WindowsToastNotifier, no lanza PowerShell
    from backend.app.services.notifier import WindowsToastNotifier
    monkeypatch.setattr(WindowsToastNotifier, "send", lambda self, title, message, url=None: False)


@pytest.fixture(autouse=True)
def offline_sources(request, monkeypatch):
    """Reemplaza las fuentes externas por datos de fixtures (salvo en tests de red)."""
    # Cada test arranca sin feriados en el calendario (los tests de feriados los cargan explícitamente)
    from backend.app.services.market_calendar import set_ar_holidays
    set_ar_holidays([])
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
            res = test_client.post("/api/v1/reference/refresh")
            assert res.status_code == 200, res.text
            res = test_client.post("/api/v1/ingest")
            assert res.status_code == 200, res.text
            yield test_client
