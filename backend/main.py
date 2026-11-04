import os
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from backend.app.config import settings
from backend.app.db.session import engine, Base, SessionLocal
from backend.app.db.models import Bond, PriceSnapshot, ArbitrageSignal, MacroIndicator
from backend.app.api.routes import router as api_router, ingestion_service, arbitrage_engine

# Configuración de Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("bonistas_trading")

scheduler = AsyncIOScheduler()
# Se reutilizan las mismas instancias que usan los endpoints (una sola fuente de verdad)

async def scheduled_ingestion_job():
    """Tarea periódica para ingesta de cotizaciones y evaluación algorítmica de arbitrajes."""
    logger.info("Iniciando ciclo automático de ingesta...")
    db = SessionLocal()
    try:
        await ingestion_service.ingest_market_data(db)
        logger.info("Ejecutando motor de evaluación de arbitrajes...")
        arbitrage_engine.evaluate_all_strategies(db)
    except Exception as e:
        logger.error(f"Error en ciclo programado de ingesta/arbitraje: {e}")
    finally:
        db.close()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. Crear tablas en la base de datos
    logger.info("Verificando y creando esquemas de base de datos...")
    Base.metadata.create_all(bind=engine)
    
    # 2. Sembrar catálogo inicial
    db = SessionLocal()
    try:
        count = ingestion_service.seed_initial_bonds(db)
        logger.info(f"Catálogo verificado. {count} bonos sembrados.")
        
        # Ejecutar una primera ingesta y evaluación al iniciar
        if settings.SKIP_STARTUP_INGESTION:
            logger.info("Ingesta inicial omitida (SKIP_STARTUP_INGESTION).")
        else:
            try:
                logger.info("Ejecutando ingesta inicial de mercado...")
                await ingestion_service.ingest_market_data(db)
                logger.info("Ejecutando evaluación inicial de arbitrajes...")
                arbitrage_engine.evaluate_all_strategies(db)
            except Exception as e:
                logger.warning(f"No se pudo completar la ingesta/evaluación inicial: {e}")
    finally:
        db.close()

    # 3. Iniciar programador de tareas periódico
    if not settings.DISABLE_SCHEDULER:
        scheduler.add_job(
            scheduled_ingestion_job,
            "interval",
            seconds=settings.POLLING_INTERVAL_SECONDS,
            id="market_ingestion",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        scheduler.start()
        logger.info(f"Programador de tareas iniciado. Intervalo: {settings.POLLING_INTERVAL_SECONDS}s.")
    else:
        logger.info("Programador de tareas deshabilitado (DISABLE_SCHEDULER).")

    yield

    # Shutdown
    if scheduler.running:
        logger.info("Deteniendo programador de tareas...")
        scheduler.shutdown()

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description="Motor cuantitativo en tiempo real para detección y catalogación de oportunidades de arbitraje en bonos soberanos argentinos.",
    lifespan=lifespan
)

# CORS: el dashboard se sirve desde el mismo origen, así que solo se habilitan orígenes locales
# de desarrollo (ej. Vite). Sin credenciales: no hay cookies que compartir entre orígenes.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        f"http://localhost:{settings.PORT}",
        f"http://127.0.0.1:{settings.PORT}",
        "http://localhost:5173",
    ],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix=settings.API_V1_STR)

# Montaje de Dashboard Web estático
static_dir = os.path.join(os.path.dirname(__file__), "app", "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

@app.get("/", include_in_schema=False)
def serve_dashboard():
    index_path = os.path.join(static_dir, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"message": "Bonistas Trading & Arbitrage API activa. Documentación en /docs"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host=settings.HOST, port=settings.PORT, reload=settings.RELOAD)

