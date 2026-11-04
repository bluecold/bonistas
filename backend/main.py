import os
import logging
from contextlib import asynccontextmanager
from datetime import datetime
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import func, select

from backend.app.config import settings
from backend.app.db.session import engine, Base, SessionLocal
from backend.app.db.migrations import add_missing_columns
from backend.app.db.models import Bond, PriceSnapshot, ArbitrageSignal, MacroIndicator, ReferenceBond
from backend.app.services.market_calendar import ART
# Se reutilizan las mismas instancias que usan los endpoints (una sola fuente de verdad)
from backend.app.api.routes import (
    router as api_router,
    ingestion_service,
    arbitrage_engine,
    market_book_service,
    reference_service,
    market_calendar,
)

# Configuración de Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("bonistas_trading")

scheduler = AsyncIOScheduler(timezone=ART)


async def run_market_cycle(db) -> None:
    """Un ciclo completo: analítica (Bonistas), libro de BYMA y evaluación de estrategias."""
    try:
        await ingestion_service.ingest_market_data(db)
    except Exception as e:
        logger.error(f"Bonistas: {e}")
    await market_book_service.ingest_byma(db)
    arbitrage_engine.evaluate_all_strategies(db)


async def scheduled_ingestion_job():
    """Cada POLLING_INTERVAL_SECONDS; solo consulta las fuentes en horario de mercado."""
    if not await market_calendar.should_poll():
        logger.debug("Fuera del horario de mercado: no se consultan cotizaciones.")
        return
    db = SessionLocal()
    try:
        await run_market_cycle(db)
    except Exception as e:
        logger.error(f"Error en ciclo programado de ingesta/arbitraje: {e}")
    finally:
        db.close()


async def scheduled_reference_job():
    """Una vez por día: flujos de CompararBonos y CER/TAMAR/A3500 del BCRA."""
    db = SessionLocal()
    try:
        result = await reference_service.refresh(db)
        logger.info(f"Datos de referencia actualizados: {result.get('reference_bonds', 0)} bonos.")
    except Exception as e:
        logger.error(f"Error en la actualización de referencia: {e}")
    finally:
        db.close()


def reference_is_stale(db) -> bool:
    last = db.execute(select(func.max(ReferenceBond.fetched_at))).scalar()
    if last is None:
        return True
    if last.tzinfo is None:
        from datetime import timezone
        last = last.replace(tzinfo=timezone.utc)
    return last.astimezone(ART).date() < datetime.now(ART).date()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. Crear tablas en la base de datos (las nuevas se agregan sin tocar las existentes)
    logger.info("Verificando y creando esquemas de base de datos...")
    Base.metadata.create_all(bind=engine)
    add_missing_columns(engine)

    # 2. Sembrar catálogo inicial
    db = SessionLocal()
    try:
        count = ingestion_service.seed_initial_bonds(db)
        logger.info(f"Catálogo verificado. {count} bonos sembrados.")

        # Ingesta y evaluación iniciales (una vez, aunque el mercado esté cerrado: muestra el último cierre)
        if settings.SKIP_STARTUP_INGESTION:
            logger.info("Ingesta inicial omitida (SKIP_STARTUP_INGESTION).")
        else:
            try:
                if reference_is_stale(db):
                    logger.info("Actualizando datos de referencia (CompararBonos + BCRA)...")
                    await reference_service.refresh(db)
                logger.info("Ejecutando ingesta inicial de mercado...")
                await run_market_cycle(db)
            except Exception as e:
                logger.warning(f"No se pudo completar la ingesta/evaluación inicial: {e}")
    finally:
        db.close()

    # 3. Iniciar programador de tareas
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
        scheduler.add_job(
            scheduled_reference_job,
            CronTrigger(day_of_week="mon-fri", hour=settings.REFERENCE_REFRESH_HOUR,
                        minute=settings.REFERENCE_REFRESH_MINUTE, timezone=ART),
            id="reference_refresh",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        scheduler.start()
        logger.info(
            f"Programador iniciado: mercado cada {settings.POLLING_INTERVAL_SECONDS}s "
            f"({'solo en horario de rueda' if settings.MARKET_HOURS_ONLY else 'sin restricción horaria'}), "
            f"referencia L-V {settings.REFERENCE_REFRESH_HOUR:02d}:{settings.REFERENCE_REFRESH_MINUTE:02d} ART."
        )
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

