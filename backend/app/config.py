from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Configuración general. Todos los valores se pueden sobreescribir con variables de
    entorno o con un archivo `.env` en la raíz del proyecto (no versionado).
    """
    PROJECT_NAME: str = "Sistema de Arbitraje de Bonos Argentinos"
    VERSION: str = "1.1.0-dev"
    API_V1_STR: str = "/api/v1"
    PORT: int = 8050
    # Por defecto solo escucha en esta PC. Usar HOST=0.0.0.0 para exponerlo en la red local.
    HOST: str = "127.0.0.1"
    RELOAD: bool = False

    # Base de Datos
    DATABASE_URL: str = "sqlite:///./bonistas.db"

    # URLs de Fuentes de Datos
    BONISTAS_BASE_URL: str = "https://bonistas.com"
    DOLAR_API_BASE_URL: str = "https://dolarapi.com/v1"

    # Parámetros de Ingesta
    POLLING_INTERVAL_SECONDS: int = 60
    # Consultar cotizaciones solo en días hábiles y en horario de rueda (según BYMA market-time),
    # con 25 min extra después del cierre por la demora de 20 min de BYMA Open Data.
    MARKET_HOURS_ONLY: bool = True
    TIMEZONE: str = "America/Argentina/Buenos_Aires"
    # Hora (ART) de la actualización diaria de datos de referencia (CompararBonos + BCRA)
    REFERENCE_REFRESH_HOUR: int = 10
    REFERENCE_REFRESH_MINUTE: int = 15
    # Útiles para tests / desarrollo offline
    DISABLE_SCHEDULER: bool = False
    SKIP_STARTUP_INGESTION: bool = False

    # Parámetros operativos del trader (valores por defecto, editables desde el dashboard)
    COMMISSION_PCT: float = 0.11         # % por operación, todo incluido (comisión + derechos + impuestos)
    MIN_NET_PROFIT_PCT: float = 0.40     # Ganancia neta mínima para disparar un arbitraje
    TRADE_SIZE_USD: float = 500.0        # Tamaño de operación para evaluar la profundidad del libro

    # Bull Market (tiempo real, etapa 4). La cookie de sesión NO va en el código: se pega en el
    # dashboard y se guarda en BULLMARKET_COOKIE_FILE (carpeta secrets/, fuera de git). También
    # puede definirse BULLMARKET_COOKIE en el .env (se usa si el archivo no existe).
    BULLMARKET_ENABLED: bool = True
    BULLMARKET_COOKIE: str = ""
    BULLMARKET_COOKIE_FILE: str = "secrets/bullmarket_cookie.txt"
    # Los libros de Bull Market solo se usan si la última consulta OK tiene menos de esta antigüedad
    BULLMARKET_MAX_AGE_SECONDS: int = 180

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=True, extra="ignore")


settings = Settings()
