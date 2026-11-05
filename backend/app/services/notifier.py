"""
Notificaciones de escritorio de Windows (toast) sin dependencias externas.

Usa la API nativa de Windows (Windows.UI.Notifications) a través de PowerShell, el mismo
mecanismo que usan librerías como winotify. Seguridad:
- El script de PowerShell es fijo (se pasa con -EncodedCommand) y el título, el mensaje y
  la URL viajan por variables de entorno: el texto de una alerta nunca se ejecuta como código.
- Dentro del script se escapan para XML antes de armar el toast.
- Se lanza sin esperar (no bloquea el ciclo de mercado) y sin ventana.

Al hacer clic en la notificación se abre el dashboard.
En otros sistemas operativos (o si se deshabilita) solo se registra en el log.
"""

import base64
import logging
import os
import subprocess
import sys
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

# AppUserModelID de Windows PowerShell: permite mostrar toasts sin registrar una app propia
_APP_ID = r"{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe"

_PS_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] > $null
function E([string]$s) { [System.Security.SecurityElement]::Escape($s) }
$t = E $env:BONISTAS_TOAST_TITLE
$m = E $env:BONISTAS_TOAST_MESSAGE
$u = E $env:BONISTAS_TOAST_URL
$a = E $env:BONISTAS_TOAST_ATTRIBUTION
$xml = "<toast activationType='protocol' launch='$u'><visual><binding template='ToastGeneric'><text>$t</text><text>$m</text><text placement='attribution'>$a</text></binding></visual><audio src='ms-winsoundevent:Notification.Default'/></toast>"
$doc = New-Object Windows.Data.Xml.Dom.XmlDocument
$doc.LoadXml($xml)
$toast = [Windows.UI.Notifications.ToastNotification]::new($doc)
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('__APP_ID__').Show($toast)
""".replace("__APP_ID__", _APP_ID)

_ENCODED = base64.b64encode(_PS_SCRIPT.encode("utf-16-le")).decode("ascii")


def _clip(s: str, n: int) -> str:
    s = " ".join(str(s or "").split())
    return s if len(s) <= n else s[: n - 1] + "…"


class Notifier:
    """Interfaz: envía una notificación; devuelve True si se lanzó."""

    def send(self, title: str, message: str, url: Optional[str] = None) -> bool:  # pragma: no cover
        raise NotImplementedError


class LogNotifier(Notifier):
    def send(self, title: str, message: str, url: Optional[str] = None) -> bool:
        logger.info(f"[ALERTA] {title} — {message}")
        return False


class WindowsToastNotifier(Notifier):
    def __init__(self, attribution: str = "Bonistas Monitor"):
        self.attribution = attribution

    @staticmethod
    def available() -> bool:
        return sys.platform == "win32"

    def send(self, title: str, message: str, url: Optional[str] = None) -> bool:
        if not self.available():
            return LogNotifier().send(title, message, url)
        env = dict(os.environ)
        env.update({
            "BONISTAS_TOAST_TITLE": _clip(title, 120),
            "BONISTAS_TOAST_MESSAGE": _clip(message, 300),
            "BONISTAS_TOAST_URL": url or "",
            "BONISTAS_TOAST_ATTRIBUTION": self.attribution,
        })
        try:
            subprocess.Popen(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                 "-WindowStyle", "Hidden", "-EncodedCommand", _ENCODED],
                env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            logger.info(f"Notificación de Windows: {title}")
            return True
        except OSError as e:
            logger.warning(f"No se pudo mostrar la notificación de Windows: {e}")
            return False


class RecordingNotifier(Notifier):
    """Para tests: guarda lo que se habría notificado."""

    def __init__(self):
        self.sent: List[Tuple[str, str, Optional[str]]] = []

    def send(self, title: str, message: str, url: Optional[str] = None) -> bool:
        self.sent.append((title, message, url))
        return True
