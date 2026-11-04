"""
Migraciones mínimas para bases SQLite existentes.

`Base.metadata.create_all` crea tablas nuevas pero NO agrega columnas a tablas que ya existen.
Esta función agrega (ALTER TABLE ... ADD COLUMN) las columnas declaradas en los modelos que
falten en la base, sin tocar los datos. Solo agrega: nunca borra ni modifica columnas.
"""

import logging
from typing import List

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from backend.app.db.session import Base

logger = logging.getLogger(__name__)


def add_missing_columns(engine: Engine) -> List[str]:
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    added: List[str] = []
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if table.name not in existing_tables:
                continue  # la crea create_all
            present = {c["name"] for c in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in present:
                    continue
                col_type = column.type.compile(dialect=engine.dialect)
                conn.execute(text(f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {col_type}'))
                added.append(f"{table.name}.{column.name}")
    if added:
        logger.info(f"Migración: columnas agregadas {added}")
    return added
