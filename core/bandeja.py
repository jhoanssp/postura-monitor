"""
Ícono en la bandeja del sistema — v4.5
Menú contextual con: estado, pausar, configuración, calibrar, desinstalar, salir.
"""

import sys
import subprocess
from pathlib import Path
from typing import Optional, Callable

from PySide6.QtWidgets import QSystemTrayIcon, QMenu, QApplication, QMessageBox
from PySide6.QtGui import QIcon, QPixmap, QColor, QPainter
from PySide6.QtCore import Qt, QTimer, Signal, QObject

from config.i18n import t, I18n
from utils.logger import crear_logger

logger = crear_logger("bandeja")

IMG_DIR = Path(__file__).parent.parent / "onboarding" / "img"


# ── Crear ícono desde logo o fallback de color ────────────────────────────────

def _crear_icono(estado: str = "correcto") -> QIcon:
    """Devuelve un QIcon con el logo o un círculo de color como fallback."""
    logo = IMG_DIR / "logo.jpg"
    if logo.exists():
        pix = QPixmap(str(logo))
        if not pix.isNull():
            return QIcon(pix.scaled(64, 64, Qt.KeepAspectRatio, Qt.SmoothTransformation))

    # Fallback: círculo de color según estado
    colores = {
        "correcto":     "#34c759",
        "advertencia":  "#ff9500",
        "incorrecto":   "#ff3b30",
        "pausado":      "#8e8e93",
        "sin_camara":   "#636366",
    }
    color = colores.get(estado, "#007aff")
    pix = QPixmap(64, 64)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QColor(color))
    p.setPen(Qt.NoPen)
    p.drawEllipse(4, 4, 56, 56)
    p.end()
    return QIcon(pix)


# ── Bandeja ───────────────────────────────────────────────────────────────────

class BandejaSistema(QObject):
    """
    Ícono en la bandeja del sistema con menú contextual.

    Señales:
        pausar_reanudar()  — el usuario pidió pausar o reanudar
        abrir_config()     — el usuario pidió abrir configuración
        salir()            — el usuario pidió salir
    """

    pausar_reanudar = Signal()
    abrir_config    = Signal()
    salir           = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pausado   = False
        self._estado    = "correcto"
        self._tray: Optional[QSystemTrayIcon] = None
        self._menu: Optional[QMenu] = None

        if not QSystemTrayIcon.isSystemTrayAvailable():
            logger.warning("Bandeja del sistema no disponible en este entorno.")
            return

        self._tray = QSystemTrayIcon(self)
        self._tray.setIcon(_crear_icono())
        self._tray.setToolTip(
            "Monitor de Postura\n" +
            ("Español" if I18n.idioma() == "es" else "English")
        )
        self._construir_menu()
        self._tray.activated.connect(self._on_activado)
        self._tray.show()
        logger.info("Ícono de bandeja iniciado.")

    # ── Menú ──────────────────────────────────────────────────────────────────

    def _construir_menu(self):
        self._menu = QMenu()

        # Título (deshabilitado, solo informativo)
        self._act_titulo = self._menu.addAction("Monitor de Postura")
        self._act_titulo.setEnabled(False)

        # Estado actual
        self._act_estado = self._menu.addAction("● " + t("estado_correcta"))
        self._act_estado.setEnabled(False)

        self._menu.addSeparator()

        # Pausar / Reanudar
        self._act_pausa = self._menu.addAction(
            "⏸  " + ("Pausar" if I18n.idioma() == "es" else "Pause")
        )
        self._act_pausa.triggered.connect(self._toggle_pausa)

        # Configuración
        self._act_config = self._menu.addAction(
            "⚙  " + ("Configuración" if I18n.idioma() == "es" else "Settings")
        )
        self._act_config.triggered.connect(self.abrir_config.emit)

        # Calibrar (NUEVO)
        self._act_calibrar = self._menu.addAction(
            "📏  " + ("Calibrar postura" if I18n.idioma() == "es" else "Calibrate posture")
        )
        self._act_calibrar.triggered.connect(self._ejecutar_calibracion)

        self._menu.addSeparator()

        # Desinstalar
        self._act_des = self._menu.addAction(
            "🗑  " + ("Desinstalar" if I18n.idioma() == "es" else "Uninstall")
        )
        self._act_des.triggered.connect(self._desinstalar)

        # Salir
        self._act_salir = self._menu.addAction(
            "✕  " + ("Salir" if I18n.idioma() == "es" else "Quit")
        )
        self._act_salir.triggered.connect(self.salir.emit)

        self._tray.setContextMenu(self._menu)

    # ── Actualizar estado ─────────────────────────────────────────────────────

    def actualizar_estado(self, estado: str, mensaje: str = ""):
        """
        estado: 'correcto' | 'advertencia' | 'incorrecto' | 'pausado' | 'sin_camara'
        """
        self._estado = estado
        if not self._tray:
            return

        iconos_estado = {
            "correcto":    "✅",
            "advertencia": "⚠️",
            "incorrecto":  "🔴",
            "pausado":     "⏸",
            "sin_camara":  "📵",
        }
        emoji = iconos_estado.get(estado, "●")
        texto = mensaje or {
            "correcto":    t("estado_correcta"),
            "advertencia": t("estado_advertencia"),
            "incorrecto":  t("estado_incorrecta"),
            "pausado":     "Pausado" if I18n.idioma()=="es" else "Paused",
            "sin_camara":  "Sin cámara" if I18n.idioma()=="es" else "No camera",
        }.get(estado, estado)

        self._tray.setIcon(_crear_icono(estado))
        self._tray.setToolTip(f"Monitor de Postura\n{emoji} {texto}")
        if self._act_estado:
            self._act_estado.setText(f"{emoji} {texto}")

    # ── Notificación emergente (balloon) ──────────────────────────────────────

    def notificar(self, titulo: str, mensaje: str, duracion_ms: int = 4000):
        if self._tray:
            self._tray.showMessage(titulo, mensaje,
                                   QSystemTrayIcon.MessageIcon.Information,
                                   duracion_ms)

    # ── Pausar / Reanudar ─────────────────────────────────────────────────────

    def _toggle_pausa(self):
        self._pausado = not self._pausado
        if self._pausado:
            self._act_pausa.setText(
                "▶  " + ("Reanudar" if I18n.idioma()=="es" else "Resume")
            )
            self.actualizar_estado("pausado")
        else:
            self._act_pausa.setText(
                "⏸  " + ("Pausar" if I18n.idioma()=="es" else "Pause")
            )
            self.actualizar_estado("correcto")
        self.pausar_reanudar.emit()

    @property
    def pausado(self) -> bool:
        return self._pausado

    # ── Clic en el ícono ──────────────────────────────────────────────────────

    def _on_activado(self, razon):
        # Clic izquierdo muestra el menú también
        if razon == QSystemTrayIcon.ActivationReason.Trigger:
            if self._tray and self._menu:
                self._tray.contextMenu().popup(
                    self._tray.geometry().center()
                )

    # ── Calibración desde bandeja ─────────────────────────────────────────────

    def _ejecutar_calibracion(self):
        """Lanza el proceso de calibración frontal en una ventana independiente."""
        # Detener temporalmente el monitor si está corriendo? No es necesario,
        # la calibración usa su propia cámara y no interfiere.
        try:
            # Ruta al ejecutable
            if getattr(sys, 'frozen', False):
                exe = sys.executable
                script = str(Path(__file__).parent.parent / "main.py")
                subprocess.Popen([exe, script, "--calibrar"])
            else:
                subprocess.Popen([sys.executable, "-m", "main", "--calibrar"])
            logger.info("Calibración lanzada desde bandeja.")
        except Exception as e:
            logger.error(f"Error lanzando calibración: {e}")
            QMessageBox.warning(None, "Error", "No se pudo iniciar la calibración.")

    # ── Desinstalar desde bandeja ─────────────────────────────────────────────

    def _desinstalar(self):
        idioma = I18n.idioma()
        titulo = "Desinstalar Monitor de Postura" if idioma=="es" else "Uninstall Posture Monitor"
        msg = (
            "¿Desinstalar el programa?\nLa configuración de Telegram se conservará."
            if idioma=="es" else
            "Uninstall the program?\nYour Telegram settings will be kept."
        )
        resp = QMessageBox.question(None, titulo, msg,
                                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if resp != QMessageBox.Yes:
            return

        try:
            from onboarding.wizard import desactivar_autoarranque
            desactivar_autoarranque()

            if sys.platform == "win32":
                import winreg
                k = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                    r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\Monitor de Postura_is1",
                    0, winreg.KEY_READ)
                uninstall, _ = winreg.QueryValueEx(k, "UninstallString")
                winreg.CloseKey(k)
                subprocess.Popen([uninstall, "/SILENT"])
                QApplication.quit()
            else:
                r = subprocess.run(["pkexec", "dpkg", "-r", "postura-monitor"],
                                   capture_output=True, text=True)
                if r.returncode != 0:
                    r = subprocess.run(["sudo", "dpkg", "-r", "postura-monitor"],
                                       capture_output=True, text=True)
                if r.returncode == 0:
                    ok = "Desinstalado correctamente." if idioma=="es" else "Uninstalled successfully."
                    QMessageBox.information(None, "OK", ok)
                    QApplication.quit()
                else:
                    raise RuntimeError(r.stderr)
        except Exception as e:
            err = (
                f"No se pudo desinstalar automáticamente.\n\nEjecuta:\n  sudo dpkg -r postura-monitor"
                if idioma=="es" else
                f"Could not uninstall automatically.\n\nRun:\n  sudo dpkg -r postura-monitor"
            )
            QMessageBox.warning(None, "Error", err)

    def ocultar(self):
        if self._tray:
            self._tray.hide()
