"""
Tipos de columna propios.

SQLite no guarda la zona horaria: `DateTime(timezone=True)` devuelve fechas "naive" aunque se
hayan guardado en UTC, y al serializarlas sin zona el navegador las interpreta como hora local
(ej. 04:09 en lugar de 01:09 ART). UTCDateTime normaliza a UTC al guardar y devuelve siempre
fechas con tzinfo=UTC.
"""

from datetime import timezone

from sqlalchemy.types import DateTime, TypeDecorator


class UTCDateTime(TypeDecorator):
    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None and value.tzinfo is not None:
            value = value.astimezone(timezone.utc)
        return value

    def process_result_value(self, value, dialect):
        if value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value
