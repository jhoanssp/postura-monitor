"""
Notificaciones del sistema (desktop) — v4.4
Linux: notify-send | Windows: plyer / win10toast
Sin internet, sin APIs, funciona siempre.
"""

import sys
import subprocess
from pathlib import Path
from utils.logger import crear_logger

logger = crear_logger("notif_local")

ICON_PATH = str(Path(__file__).parent.parent / "onboarding" / "img" / "logo.jpg")


def _notificar_linux(titulo: str, mensaje: str, urgencia: str = "normal"):
    try:
        cmd = ["notify-send", titulo, mensaje,
               "--urgency", urgencia,
               "--app-name", "Monitor de Postura",
               "--expire-time", "5000"]
        if Path(ICON_PATH).exists():
            cmd += ["--icon", ICON_PATH]
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except FileNotFoundError:
        logger.warning("notify-send no encontrado.")
        return False


def _notificar_windows(titulo: str, mensaje: str):
    try:
        from plyer import notification
        notification.notify(
            title=titulo, message=mensaje,
            app_name="Monitor de Postura",
            app_icon=ICON_PATH if Path(ICON_PATH).exists() else "",
            timeout=5,
        )
        return True
    except ImportError:
        try:
            from win10toast import ToastNotifier
            ToastNotifier().show_toast(titulo, mensaje, duration=5, threaded=True)
            return True
        except ImportError:
            logger.warning("plyer y win10toast no disponibles.")
            return False


def notificar(titulo: str, mensaje: str, urgente: bool = False) -> bool:
    """Envía una notificación del sistema. Cross-platform."""
    try:
        if sys.platform == "win32":
            return _notificar_windows(titulo, mensaje)
        else:
            urgencia = "critical" if urgente else "normal"
            return _notificar_linux(titulo, mensaje, urgencia)
    except Exception as e:
        logger.error(f"Notificación local fallida: {e}")
        return False


class GestorNotificacionesLocal:
    """Gestor de notificaciones desktop con cooldown para no saturar."""

    COOLDOWN_SEG = 120   # misma alerta máx cada 2 min

    def __init__(self):
        self._ultimo: dict = {}

    def _puede_notificar(self, clave: str) -> bool:
        import time
        ahora = time.time()
        ultimo = self._ultimo.get(clave, 0)
        if ahora - ultimo >= self.COOLDOWN_SEG:
            self._ultimo[clave] = ahora
            return True
        return False

    def alerta_postura(self, tipo: str, tiempo_seg: float,
                       angulo_cuello: float = None) -> bool:
        if not self._puede_notificar(f"postura_{tipo}"):
            return False
        mins = int(tiempo_seg // 60)
        segs = int(tiempo_seg % 60)
        dur  = f"{mins}m {segs}s" if mins > 0 else f"{segs}s"
        msg  = f"Lleva {dur} con mala postura\n{tipo}"
        if angulo_cuello:
            msg += f"\nÁngulo cuello: {angulo_cuello:.1f}°"
        return notificar("⚠️ Mala Postura Detectada", msg, urgente=True)

    def alerta_sedentarismo(self, tiempo_seg: float) -> bool:
        if not self._puede_notificar("sedentarismo"):
            return False
        mins = int(tiempo_seg // 60)
        return notificar(
            "🪑 Pausa Activa",
            f"Llevas {mins} minutos sin moverte.\n¡Levántate y estira!",
            urgente=False,
        )

    def inicio_monitor(self) -> bool:
        return notificar(
            "Monitor de Postura",
            "Monitoreando tu postura en segundo plano.",
        )
