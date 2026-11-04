import pytest
import os
from decimal import Decimal
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.db.session import Base
from backend.app.db.models import Bond, PriceSnapshot, MacroIndicator
from backend.app.services.ingestion_service import IngestionService
from backend.app.data.bond_catalog import INITIAL_BONDS
from backend.app.data.dolar_api_client import DolarApiClient
from backend.app.data.bonistas_client import BonistasClient

# Configurar base de datos en memoria para pruebas
TEST_DB_URL = "sqlite:///:memory:"

@pytest.fixture
def db_session():
    engine = create_engine(TEST_DB_URL, connect_args={"check_same_thread": False})
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)

def test_seed_initial_bonds(db_session):
    """Verifica que el catálogo maestro se siembre con todos los bonos requeridos en la especificación."""
    service = IngestionService()
    count = service.seed_initial_bonds(db_session)
    assert count == len(INITIAL_BONDS)
    assert count >= 20

    # Comprobar bonos clave
    al30 = db_session.query(Bond).filter(Bond.ticker == "AL30").first()
    gd30 = db_session.query(Bond).filter(Bond.ticker == "GD30").first()
    s30n6 = db_session.query(Bond).filter(Bond.ticker == "S30N6").first()
    tx26 = db_session.query(Bond).filter(Bond.ticker == "TX26").first()

    assert al30 is not None
    assert al30.law == "ARG"
    assert al30.currency == "USD"
    assert al30.bond_type == "HARD_DOLLAR"

    assert gd30 is not None
    assert gd30.law == "NY"
    assert gd30.currency == "USD"
    assert gd30.bond_type == "HARD_DOLLAR"

    assert s30n6 is not None
    assert s30n6.bond_type == "TASA_FIJA"

    assert tx26 is not None
    assert tx26.bond_type == "CER"

@pytest.mark.network
@pytest.mark.asyncio
async def test_dolar_api_client():
    """Verifica la conectividad y respuesta del cliente DolarAPI."""
    client = DolarApiClient()
    rates = await client.get_rates_dict()
    assert isinstance(rates, dict)
    assert "oficial" in rates or "bolsa" in rates or "contadoconliqui" in rates
    if "bolsa" in rates:
        assert rates["bolsa"] > 0

@pytest.mark.asyncio
async def test_full_ingestion_cycle(db_session):
    """Verifica la ejecución completa de una ingesta de mercado en la base de datos."""
    service = IngestionService()
    result = await service.ingest_market_data(db_session)

    assert result["snapshots_created"] > 0
    assert "dolares" in result

    # Verificar que haya snapshots guardados
    snapshots = db_session.query(PriceSnapshot).all()
    assert len(snapshots) > 0

    # Probar consulta consolidada
    quotes = service.get_latest_quotes(db_session)
    assert len(quotes) > 0
    assert any(q.ticker in ("AL30", "GD30", "AL29", "GD29") for q in quotes)

