import os
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    PROJECT_NAME: str = "Sistema de Arbitraje de Bonos Argentinos"
    VERSION: str = "1.0.0"
    API_V1_STR: str = "/api/v1"
    PORT: int = int(os.getenv("PORT", 8050))
    HOST: str = os.getenv("HOST", "0.0.0.0")
    
    # Base de Datos
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./bonistas.db")
    
    # URLs de Fuentes de Datos
    BONISTAS_BASE_URL: str = "https://bonistas.com"
    DOLAR_API_BASE_URL: str = "https://dolarapi.com/v1"
    
    # Parámetros de Ingesta
    POLLING_INTERVAL_SECONDS: int = 30
    MARKET_OPEN_HOUR: int = 11  # 11:00 hs ART
    MARKET_CLOSE_HOUR: int = 17 # 17:00 hs ART
    TIMEZONE: str = "America/Argentina/Buenos_Aires"
    
    model_config = SettingsConfigDict(env_file=".env", case_sensitive=True, extra="ignore")

settings = Settings()
