"""
Alertas: deciden QUÉ avisar y CUÁNDO, las guardan para el panel del dashboard y disparan la
notificación de Windows.

Eventos:
- OPORTUNIDAD: aparece una señal nueva (solo cuando aparece, no en cada ciclo mientras siga activa).
- CONFIRMADA: una señal detectada con BYMA (demora) pasa a estar confirmada con Bull Market.
- SESION_VENCIDA: Bull Market rechazó la cookie (una sola vez por vencimiento).
- FUENTE_CAIDA / FUENTE_OK: una fuente falla N ciclos seguidos / vuelve a responder.

Anti-ruido: si una señal desaparece y reaparece (puntas que oscilan) no se vuelve a avisar
hasta pasados COOLDOWN_MINUTES desde el último aviso con la misma clave.

Preferencias (tabla user_settings, clave "notifications", editables en el dashboard):
- windows: mostrar notificaciones de Windows (el panel del dashboard siempre registra todo).
- only_realtime: notificar en Windows solo oportunidades confirmadas en tiempo real.
- sources: avisar sesión vencida y fuentes caídas.
"""

import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from backend.app.config import settings
from backend.app.db.models import Alert, ArbitrageSignal, UserSetting
from backend.app.services.notifier import LogNotifier, Notifier, WindowsToastNotifier

logger = logging.getLogger(__name__)

SETTINGS_KEY = "notifications"
COOLDOWN_MINUTES = 15
SOURCE_DOWN_AFTER = 3          # fallas consecutivas (≈ 3 min con polling de 60 s)
WATCHED_SOURCES = ("BYMA", "BONISTAS", "BULLMARKET")

CONFIRMATION_LABEL = {
    "TIEMPO_REAL": "confirmada en tiempo real",
    "PARCIAL": "parcial (una pata con demora)",
    "DEMORA_20MIN": "detectada con 20 min de demora",
}


@dataclass
class NotificationPrefs:
    windows: bool = True
    only_realtime: bool = False
    sources: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def get_prefs(db: Session) -> NotificationPrefs:
    row = db.get(UserSetting, SETTINGS_KEY)
    prefs = NotificationPrefs()
    if row and isinstance(row.value, dict):
        for k in prefs.to_dict():
            if k in row.value:
                setattr(prefs, k, bool(row.value[k]))
    return prefs


def update_prefs(db: Session, values: Dict[str, Any]) -> NotificationPrefs:
    prefs = get_prefs(db)
    for k, v in values.items():
        if k not in prefs.to_dict():
            raise ValueError(f"Preferencia desconocida: {k}")
        if not isinstance(v, bool):
            raise ValueError(f"{k} debe ser true o false")
        setattr(prefs, k, v)
    row = db.get(UserSetting, SETTINGS_KEY)
    if row is None:
        db.add(UserSetting(key=SETTINGS_KEY, value=prefs.to_dict()))
    else:
        row.value = prefs.to_dict()
    db.commit()
    return prefs


def _pct(v: Optional[float]) -> str:
    return f"{v:+.2f}%" if v is not None else "s/d"


def dashboard_url() -> str:
    host = "127.0.0.1" if settings.HOST in ("0.0.0.0", "::") else settings.HOST
    return f"http://{host}:{settings.PORT}/"


class AlertService:
    def __init__(self, notifier: Optional[Notifier] = None):
        if notifier is None:
            notifier = WindowsToastNotifier() if settings.WINDOWS_NOTIFICATIONS else LogNotifier()
        self.notifier = notifier
        self._last_notified: Dict[str, datetime] = {}
        self._down: set = set()

    # ------------------------------------------------------------------ núcleo
    def _in_cooldown(self, key: str, now: datetime) -> bool:
        last = self._last_notified.get(key)
        return last is not None and now - last < timedelta(minutes=COOLDOWN_MINUTES)

    def emit(self, db: Session, kind: str, severity: str, title: str, message: str,
             dedupe_key: Optional[str] = None, signal_id: Optional[int] = None,
             toast: bool = True, now: Optional[datetime] = None) -> Optional[Alert]:
        """Registra la alerta y (si corresponde) muestra la notificación. None si estaba en cooldown."""
        now = now or datetime.now(timezone.utc)
        if dedupe_key and self._in_cooldown(dedupe_key, now):
            return None
        alert = Alert(timestamp=now, kind=kind, severity=severity, title=title[:160], message=message,
                      signal_id=signal_id, dedupe_key=dedupe_key, read=False, notified=False)
        if toast:
            try:
                alert.notified = bool(self.notifier.send(title, message, dashboard_url()))
            except Exception as e:      # la notificación nunca debe cortar el ciclo
                logger.warning(f"Notificación fallida: {e}")
        db.add(alert)
        db.commit()
        if dedupe_key:
            self._last_notified[dedupe_key] = now
        return alert

    # ------------------------------------------------------------------ señales
    @staticmethod
    def _signal_text(s: ArbitrageSignal) -> str:
        return f"{s.leg_sell_ticker} → {s.leg_buy_ticker}. {(s.notes or '')[:220]}"

    def on_evaluation(self, db: Session, new: List[ArbitrageSignal], upgraded: List[ArbitrageSignal]) -> None:
        """Listener del motor: se llama después de cada evaluación."""
        prefs = get_prefs(db)
        for s in new:
            realtime = s.confirmation == "TIEMPO_REAL"
            toast = prefs.windows and (realtime or not prefs.only_realtime)
            label = CONFIRMATION_LABEL.get(s.confirmation, s.confirmation or "")
            self.emit(
                db, "OPORTUNIDAD", "OPORTUNIDAD",
                f"{s.strategy_name} {_pct(s.net_profit_pct)} neto · {label}",
                self._signal_text(s), dedupe_key=f"SIGNAL|{s.signal_key}", signal_id=s.id, toast=toast,
            )
        for s in upgraded:
            # Siempre se avisa: es justamente el momento de operar
            self.emit(
                db, "CONFIRMADA", "OPORTUNIDAD",
                f"Confirmada en tiempo real: {s.strategy_name} {_pct(s.net_profit_pct)} neto",
                self._signal_text(s), dedupe_key=f"CONFIRMED|{s.signal_key}", signal_id=s.id,
                toast=prefs.windows,
            )

    # ------------------------------------------------------------------ fuentes
    def check_sources(self, db: Session, health: Dict[str, Dict], bm_just_expired: bool = False,
                      bm_status: Optional[str] = None) -> None:
        prefs = get_prefs(db)
        toast = prefs.windows and prefs.sources
        if bm_just_expired:
            self.emit(db, "SESION_VENCIDA", "AVISO", "Sesión de Bull Market vencida",
                      "Iniciá sesión de nuevo y pegá la cookie nueva en el dashboard. "
                      "Mientras tanto se usan puntas de BYMA (20 min de demora).",
                      toast=toast)
        for name in WATCHED_SOURCES:
            st = health.get(name)
            if not st:
                continue
            if name == "BULLMARKET" and bm_status in ("VENCIDA", "NO_CONFIGURADA"):
                self._down.discard(name)       # el vencimiento ya se avisó aparte
                continue
            failures = st.get("consecutive_failures", 0)
            if failures >= SOURCE_DOWN_AFTER and name not in self._down:
                self._down.add(name)
                self.emit(db, "FUENTE_CAIDA", "AVISO", f"Fuente caída: {name}",
                          f"{failures} consultas seguidas con error. Último error: {st.get('last_error') or '-'}",
                          toast=toast)
            elif failures == 0 and name in self._down:
                self._down.discard(name)
                self.emit(db, "FUENTE_OK", "INFO", f"Fuente recuperada: {name}",
                          "Volvió a responder normalmente.", toast=toast)

    # ------------------------------------------------------------------ consultas
    @staticmethod
    def list_alerts(db: Session, limit: int = 50, unread_only: bool = False,
                    after_id: Optional[int] = None) -> List[Alert]:
        q = select(Alert).order_by(Alert.id.desc()).limit(limit)
        if unread_only:
            q = q.where(Alert.read.is_(False))
        if after_id is not None:
            q = q.where(Alert.id > after_id)
        return list(db.execute(q).scalars())

    @staticmethod
    def unread_count(db: Session) -> int:
        from sqlalchemy import func
        return db.execute(select(func.count(Alert.id)).where(Alert.read.is_(False))).scalar() or 0

    @staticmethod
    def mark_read(db: Session, ids: Optional[List[int]] = None) -> int:
        stmt = update(Alert).where(Alert.read.is_(False))
        if ids:
            stmt = stmt.where(Alert.id.in_(ids))
        n = db.execute(stmt.values(read=True)).rowcount
        db.commit()
        return n or 0

    @staticmethod
    def to_dict(a: Alert) -> Dict[str, Any]:
        return {
            "id": a.id, "timestamp": a.timestamp.isoformat() if a.timestamp else None,
            "kind": a.kind, "severity": a.severity, "title": a.title, "message": a.message,
            "signal_id": a.signal_id, "notified": a.notified, "read": a.read,
        }
