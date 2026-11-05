"""
Sesión de Bull Market: guarda la cookie que pega el trader y sigue su estado.

Seguridad:
- La cookie se guarda en un archivo de `secrets/` (ignorado por git) o se toma de la variable
  BULLMARKET_COOKIE del `.env`. Nunca se escribe en logs ni se devuelve por la API: el
  dashboard solo ve el estado (activa / vencida / sin configurar) y cuándo se cargó.
- No hay login automático con usuario y contraseña. Cuando la sesión vence se deja de
  consultar Bull Market (para no insistir con una cookie inválida) hasta que se pegue una nueva.

Estados:
- NO_CONFIGURADA: no hay cookie.
- PENDIENTE: hay cookie pero todavía no se probó.
- ACTIVA: la última consulta fue correcta.
- VENCIDA: Bull Market rechazó la cookie (401/403, redirección o página de login).
- ERROR: falló la última consulta por otro motivo (red, 5xx); se reintenta en el próximo ciclo.
"""

import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Dict, Optional

from backend.app.config import settings

logger = logging.getLogger(__name__)

MAX_COOKIE_LENGTH = 16000

_CURL_COOKIE = re.compile(r"""(?:-H|--header)\s+['"]cookie:\s*([^'"]+)['"]""", re.IGNORECASE)
_CURL_B = re.compile(r"""(?:-b|--cookie)\s+['"]([^'"]+)['"]""", re.IGNORECASE)
_HEADER_LINE = re.compile(r"^\s*cookie\s*:\s*(.+)$", re.IGNORECASE | re.MULTILINE)


class InvalidCookieError(ValueError):
    pass


def normalize_cookie(raw: str) -> str:
    """
    Acepta el valor del encabezado `Cookie` tal como lo muestran las herramientas de
    desarrollador del navegador (con o sin el prefijo "cookie:"), o un comando "Copiar como
    cURL". Devuelve "nombre=valor; nombre2=valor2".
    """
    text = (raw or "").strip()
    if not text:
        raise InvalidCookieError("La cookie está vacía.")
    if len(text) > MAX_COOKIE_LENGTH * 4:
        raise InvalidCookieError("El texto pegado es demasiado largo.")
    for rx in (_CURL_COOKIE, _CURL_B, _HEADER_LINE):
        m = rx.search(text)
        if m:
            text = m.group(1)
            break
    parts = [p.strip() for p in re.split(r"[;\r\n]+", text) if p.strip()]
    pairs = [p for p in parts if "=" in p and not p.startswith("=")]
    if not pairs:
        raise InvalidCookieError("No se encontraron pares nombre=valor en la cookie.")
    cookie = "; ".join(pairs)
    if len(cookie) > MAX_COOKIE_LENGTH:
        raise InvalidCookieError("La cookie es demasiado larga.")
    if any(ord(c) < 32 or ord(c) == 127 for c in cookie):
        raise InvalidCookieError("La cookie contiene caracteres no válidos.")
    return cookie


class BullMarketSession:
    def __init__(self, cookie_file: Optional[str] = None, env_cookie: Optional[str] = None):
        self.cookie_file = Path(cookie_file or settings.BULLMARKET_COOKIE_FILE)
        self.env_cookie = settings.BULLMARKET_COOKIE if env_cookie is None else env_cookie
        self._lock = Lock()
        self.status = "PENDIENTE" if self.get_cookie() else "NO_CONFIGURADA"
        self.saved_at: Optional[datetime] = self._file_mtime()
        self.last_ok: Optional[datetime] = None
        self.expired_at: Optional[datetime] = None
        self.last_error: Optional[str] = None
        self.last_rows: int = 0

    # ------------------------------------------------------------------ almacenamiento
    def _file_mtime(self) -> Optional[datetime]:
        try:
            return datetime.fromtimestamp(self.cookie_file.stat().st_mtime, tz=timezone.utc)
        except OSError:
            return None

    def get_cookie(self) -> Optional[str]:
        try:
            value = self.cookie_file.read_text(encoding="utf-8").strip()
            if value:
                return value
        except OSError:
            pass
        return (self.env_cookie or "").strip() or None

    def set_cookie(self, raw: str) -> None:
        cookie = normalize_cookie(raw)
        with self._lock:
            self.cookie_file.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.cookie_file.with_suffix(".tmp")
            tmp.write_text(cookie, encoding="utf-8")
            try:
                os.chmod(tmp, 0o600)
            except OSError:
                pass
            os.replace(tmp, self.cookie_file)
            self.status = "PENDIENTE"
            self.saved_at = datetime.now(timezone.utc)
            self.expired_at = None
            self.last_error = None
        logger.info("Cookie de Bull Market actualizada (valor no registrado).")

    def clear(self) -> None:
        with self._lock:
            try:
                self.cookie_file.unlink()
            except FileNotFoundError:
                pass
            self.env_cookie = ""
            self.status = "NO_CONFIGURADA"
            self.saved_at = None
            self.last_error = None

    # ------------------------------------------------------------------ estado
    @property
    def should_poll(self) -> bool:
        """Se consulta si hay cookie y no está marcada como vencida."""
        return settings.BULLMARKET_ENABLED and self.status in ("PENDIENTE", "ACTIVA", "ERROR") \
            and self.get_cookie() is not None

    def mark_ok(self, rows: int) -> None:
        with self._lock:
            self.status = "ACTIVA"
            self.last_ok = datetime.now(timezone.utc)
            self.last_error = None
            self.last_rows = rows

    def mark_expired(self, reason: str) -> bool:
        """Marca la sesión como vencida. Devuelve True si recién venció (para notificar una sola vez)."""
        with self._lock:
            newly = self.status != "VENCIDA"
            self.status = "VENCIDA"
            self.expired_at = datetime.now(timezone.utc) if newly else self.expired_at
            self.last_error = reason[:300]
        if newly:
            logger.warning(f"Bull Market: {reason}")
        return newly

    def mark_error(self, reason: str) -> None:
        with self._lock:
            self.status = "ERROR"
            self.last_error = reason[:300]

    def to_dict(self) -> Dict[str, Any]:
        def iso(d):
            return d.isoformat() if d else None
        return {
            "enabled": settings.BULLMARKET_ENABLED,
            "configured": self.get_cookie() is not None,
            "status": self.status,
            "saved_at": iso(self.saved_at),
            "last_ok": iso(self.last_ok),
            "expired_at": iso(self.expired_at),
            "last_error": self.last_error,
            "last_rows": self.last_rows,
            "storage": "archivo secrets/" if self.cookie_file.exists() else (
                ".env" if (self.env_cookie or "").strip() else None),
        }
