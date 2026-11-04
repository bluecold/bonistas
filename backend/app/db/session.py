from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker
from backend.app.config import settings

IS_SQLITE = settings.DATABASE_URL.startswith("sqlite")

# check_same_thread=False: el scheduler y los endpoints usan la base desde hilos distintos
connect_args = {"check_same_thread": False, "timeout": 30} if IS_SQLITE else {}

engine = create_engine(
    settings.DATABASE_URL,
    connect_args=connect_args,
    echo=False
)

if IS_SQLITE:
    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_connection, connection_record):
        """
        WAL: lecturas del dashboard en paralelo con la escritura del scheduler, sin bloqueos.
        synchronous=NORMAL: seguro con WAL y mucho más rápido que FULL (menos fsync en Windows).
        """
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
