"""
Registro en memoria del estado de cada fuente de datos (última consulta OK, último error).
Lo consume el dashboard y, en la etapa 5, las notificaciones de "fuente caída".
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from threading import Lock
from typing import Dict, Optional


@dataclass
class SourceStatus:
    name: str
    last_success: Optional[datetime] = None
    last_error: Optional[str] = None
    last_error_at: Optional[datetime] = None
    consecutive_failures: int = 0
    details: Dict = field(default_factory=dict)

    @property
    def healthy(self) -> bool:
        return self.last_success is not None and self.consecutive_failures == 0

    def to_dict(self) -> Dict:
        d = asdict(self)
        d["healthy"] = self.healthy
        for k in ("last_success", "last_error_at"):
            d[k] = d[k].isoformat() if d[k] else None
        return d


class SourceHealthRegistry:
    def __init__(self):
        self._lock = Lock()
        self._sources: Dict[str, SourceStatus] = {}

    def _get(self, name: str) -> SourceStatus:
        if name not in self._sources:
            self._sources[name] = SourceStatus(name=name)
        return self._sources[name]

    def success(self, name: str, **details) -> None:
        with self._lock:
            s = self._get(name)
            s.last_success = datetime.now(timezone.utc)
            s.consecutive_failures = 0
            s.details = details

    def failure(self, name: str, error: Exception | str) -> None:
        with self._lock:
            s = self._get(name)
            s.last_error = str(error)[:300]
            s.last_error_at = datetime.now(timezone.utc)
            s.consecutive_failures += 1

    def snapshot(self) -> Dict[str, Dict]:
        with self._lock:
            return {name: s.to_dict() for name, s in self._sources.items()}

    def reset(self) -> None:
        with self._lock:
            self._sources.clear()


source_health = SourceHealthRegistry()
