"""
Tests de la etapa 5: alertas del dashboard y notificaciones de Windows.

Nunca se muestra una notificación real: se usa RecordingNotifier (o el envío está anulado en conftest).
"""

import base64
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.arbitrage.engine import ArbitrageEngine
from backend.app.db.models import Alert, ArbitrageSignal
from backend.app.db.session import Base
from backend.app.schemas.arbitrage import ArbitrageSignalCreate
from backend.app.services import notifier as notifier_mod
from backend.app.services.alert_service import (
    COOLDOWN_MINUTES, SOURCE_DOWN_AFTER, AlertService, get_prefs, update_prefs,
)
from backend.app.services.notifier import RecordingNotifier, WindowsToastNotifier


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    s = sessionmaker(bind=engine)()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture
def rec():
    return RecordingNotifier()


@pytest.fixture
def svc(rec):
    return AlertService(notifier=rec)


def gen(net=0.6, confirmation="DEMORA_20MIN", sell="AL30D CI", buy="AL30D 24HS"):
    return ArbitrageSignalCreate(
        strategy_name="CI_24HS", leg_sell_ticker=sell, leg_buy_ticker=buy, metric_name="GANANCIA_NETA_PCT",
        metric_value=Decimal(str(net)), action_recommended="VENDER_CI_COMPRAR_24HS", net_profit_pct=net,
        confirmation=confirmation, notes="nota de prueba",
    )


def engine_with(svc):
    e = ArbitrageEngine()
    e.listeners.append(svc.on_evaluation)
    return e


# ---------------------------------------------------------------------------
# Señales
# ---------------------------------------------------------------------------

def test_new_signal_alerts_once(db, svc, rec):
    e = engine_with(svc)
    e._reconcile(db, [gen()])
    e._reconcile(db, [gen()])          # sigue activa: no se vuelve a avisar
    e._reconcile(db, [gen(net=0.7)])
    assert len(rec.sent) == 1
    a = db.query(Alert).one()
    assert a.kind == "OPORTUNIDAD" and a.notified and "+0.60%" in a.title and "demora" in a.title
    assert a.signal_id == db.query(ArbitrageSignal).one().id


def test_flicker_within_cooldown_is_silent(db, svc, rec):
    e = engine_with(svc)
    e._reconcile(db, [gen()])
    e._reconcile(db, [])               # expira
    e._reconcile(db, [gen()])          # reaparece enseguida
    assert len(rec.sent) == 1 and db.query(Alert).count() == 1


def test_reappears_after_cooldown(db, svc, rec):
    e = engine_with(svc)
    e._reconcile(db, [gen()])
    e._reconcile(db, [])
    for k in svc._last_notified:
        svc._last_notified[k] -= timedelta(minutes=COOLDOWN_MINUTES + 1)
    e._reconcile(db, [gen()])
    assert len(rec.sent) == 2


def test_upgrade_to_realtime_alerts(db, svc, rec):
    e = engine_with(svc)
    e._reconcile(db, [gen(confirmation="DEMORA_20MIN")])
    e._reconcile(db, [gen(confirmation="TIEMPO_REAL")])
    e._reconcile(db, [gen(confirmation="TIEMPO_REAL")])
    kinds = [a.kind for a in db.query(Alert).order_by(Alert.id)]
    assert kinds == ["OPORTUNIDAD", "CONFIRMADA"] and len(rec.sent) == 2
    assert e.last_upgraded_signals == []


def test_only_realtime_preference(db, svc, rec):
    update_prefs(db, {"only_realtime": True})
    e = engine_with(svc)
    e._reconcile(db, [gen(confirmation="DEMORA_20MIN")])
    assert rec.sent == [] and db.query(Alert).count() == 1          # queda en el panel
    e._reconcile(db, [gen(confirmation="DEMORA_20MIN"), gen(confirmation="TIEMPO_REAL", sell="GD30D CI", buy="GD30D 24HS")])
    assert len(rec.sent) == 1 and "tiempo real" in rec.sent[0][0]


def test_windows_disabled_still_records(db, svc, rec):
    update_prefs(db, {"windows": False})
    engine_with(svc)._reconcile(db, [gen()])
    assert rec.sent == [] and db.query(Alert).one().notified is False


def test_listener_failure_does_not_break_engine(db):
    e = ArbitrageEngine()
    e.listeners.append(lambda *a: 1 / 0)
    assert len(e._reconcile(db, [gen()])) == 1


# ---------------------------------------------------------------------------
# Fuentes
# ---------------------------------------------------------------------------

def health(failures, err="timeout"):
    return {"BYMA": {"consecutive_failures": failures, "last_error": err}}


def test_source_down_and_recovery(db, svc, rec):
    for n in range(1, SOURCE_DOWN_AFTER):
        svc.check_sources(db, health(n))
    assert rec.sent == []
    svc.check_sources(db, health(SOURCE_DOWN_AFTER))
    svc.check_sources(db, health(SOURCE_DOWN_AFTER + 1))   # sigue caída: un solo aviso
    svc.check_sources(db, health(0))
    svc.check_sources(db, health(0))
    assert [a.kind for a in db.query(Alert).order_by(Alert.id)] == ["FUENTE_CAIDA", "FUENTE_OK"]


def test_session_expired_alert_once(db, svc, rec):
    hb = {"BULLMARKET": {"consecutive_failures": 5, "last_error": "302"}}
    svc.check_sources(db, hb, bm_just_expired=True, bm_status="VENCIDA")
    svc.check_sources(db, hb, bm_just_expired=False, bm_status="VENCIDA")
    assert [a.kind for a in db.query(Alert)] == ["SESION_VENCIDA"]   # no además "fuente caída"


def test_sources_preference_mutes_toast(db, svc, rec):
    update_prefs(db, {"sources": False})
    svc.check_sources(db, {}, bm_just_expired=True, bm_status="VENCIDA")
    assert rec.sent == [] and db.query(Alert).count() == 1


# ---------------------------------------------------------------------------
# Preferencias y consultas
# ---------------------------------------------------------------------------

def test_prefs_validation(db):
    assert get_prefs(db).windows is True
    with pytest.raises(ValueError):
        update_prefs(db, {"windows": "si"})
    with pytest.raises(ValueError):
        update_prefs(db, {"otra": True})


def test_list_and_mark_read(db, svc):
    for i in range(3):
        svc.emit(db, "PRUEBA", "INFO", f"t{i}", "m")
    assert AlertService.unread_count(db) == 3
    newest = AlertService.list_alerts(db)
    assert [a.title for a in newest] == ["t2", "t1", "t0"]
    assert [a.title for a in AlertService.list_alerts(db, after_id=newest[1].id)] == ["t2"]
    AlertService.mark_read(db, [newest[0].id])
    assert AlertService.unread_count(db) == 2
    AlertService.mark_read(db)
    assert AlertService.unread_count(db) == 0


def test_notifier_failure_is_swallowed(db):
    class Boom(RecordingNotifier):
        def send(self, *a, **k):
            raise RuntimeError("sin escritorio")
    a = AlertService(notifier=Boom()).emit(db, "PRUEBA", "INFO", "t", "m")
    assert a.id and a.notified is False


# ---------------------------------------------------------------------------
# Notificador de Windows: el texto viaja por variables de entorno, nunca en el comando
# ---------------------------------------------------------------------------

def test_windows_toast_passes_text_via_env(monkeypatch):
    calls = {}

    class FakePopen:
        def __init__(self, args, env=None, **kw):
            calls["args"], calls["env"] = args, env

    monkeypatch.setattr(notifier_mod.subprocess, "Popen", FakePopen)
    monkeypatch.setattr(WindowsToastNotifier, "available", staticmethod(lambda: True))
    # conftest anula send(); acá se prueba el original (capturado al importar el módulo)
    malicious = "'; Remove-Item C:\\ -Recurse; '<x>"
    ok = _ORIGINAL_SEND(WindowsToastNotifier(), malicious, "mensaje " * 100, "http://127.0.0.1:8050/")
    assert ok
    assert all(malicious not in a for a in calls["args"])
    assert calls["env"]["BONISTAS_TOAST_TITLE"] == malicious
    assert len(calls["env"]["BONISTAS_TOAST_MESSAGE"]) <= 300
    script = base64.b64decode(calls["args"][-1]).decode("utf-16-le")
    assert "SecurityElement]::Escape" in script and "$env:BONISTAS_TOAST_TITLE" in script


_ORIGINAL_SEND = WindowsToastNotifier.send     # capturado al importar, antes de conftest


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

def test_api_alerts(client):
    r = client.get("/api/v1/settings/notifications")
    assert r.status_code == 200 and set(r.json()) == {"windows", "only_realtime", "sources"}
    assert client.put("/api/v1/settings/notifications", json={"windows": "x"}).status_code == 422
    assert client.put("/api/v1/settings/notifications", json={"only_realtime": True}).json()["only_realtime"] is True

    t = client.post("/api/v1/alerts/test").json()
    assert t["kind"] == "PRUEBA"
    data = client.get("/api/v1/alerts").json()
    assert data["unread"] >= 1 and data["alerts"][0]["id"] == t["id"]
    assert client.get("/api/v1/alerts", params={"after_id": t["id"]}).json()["alerts"] == []
    assert client.post("/api/v1/alerts/read", json={}).json()["unread"] == 0
    client.put("/api/v1/settings/notifications", json={"only_realtime": False})
