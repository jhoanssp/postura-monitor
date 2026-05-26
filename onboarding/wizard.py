"""
Asistente de configuración inicial - PySide6 (Qt6) — v4.2
- Ventana adaptativa a la resolución de pantalla
- Opción de autoarranque al iniciar sesión
- Opción de desinstalar
"""

import sys
import os
import re
import subprocess
import requests
from pathlib import Path

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QCheckBox, QTextEdit, QLineEdit, QGroupBox,
    QMessageBox, QStackedWidget, QFrame, QScrollArea, QSizePolicy
)
from PySide6.QtCore import Qt, QThread, Signal, QSize
from PySide6.QtGui import QFont, QPalette, QColor, QPixmap, QScreen

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from utils.logger import crear_logger
from onboarding.estado import OnboardingEstado
from config.credentials import get_telegram_bot_token, get_bot_username

logger = crear_logger("onboarding_wizard")

_BOT_TOKEN    = get_telegram_bot_token()
_BOT_USERNAME = get_bot_username()
IMG_DIR = Path(__file__).parent / "img"


# ── Helpers ───────────────────────────────────────────────────────────────────

def cargar_imagen(nombre, tamaño=(48, 48)):
    ruta = IMG_DIR / nombre
    if ruta.exists():
        pix = QPixmap(str(ruta))
        if not pix.isNull():
            return pix.scaled(tamaño[0], tamaño[1],
                              Qt.KeepAspectRatio, Qt.SmoothTransformation)
    return None


def _escala(base: int, factor: float) -> int:
    return max(int(base * factor), int(base * 0.6))


# ── Autoarranque ──────────────────────────────────────────────────────────────

def _exe_path() -> str:
    if getattr(sys, "frozen", False):
        return sys.executable
    return str(Path(__file__).resolve().parent.parent / "main.py")


def activar_autoarranque() -> bool:
    try:
        if sys.platform == "win32":
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run",
                0, winreg.KEY_SET_VALUE,
            )
            winreg.SetValueEx(key, "PosturaMonitor", 0, winreg.REG_SZ,
                              f'"{_exe_path()}" --modo produccion --skip-onboarding')
            winreg.CloseKey(key)
        else:
            autostart = Path.home() / ".config" / "autostart"
            autostart.mkdir(parents=True, exist_ok=True)
            desktop = autostart / "postura-monitor.desktop"
            exe = "/opt/postura-monitor/postura-monitor" \
                  if Path("/opt/postura-monitor/postura-monitor").exists() \
                  else _exe_path()
            desktop.write_text(
                "[Desktop Entry]\n"
                "Type=Application\n"
                "Name=Monitor de Postura\n"
                f"Exec={exe} --modo produccion --skip-onboarding\n"
                "Hidden=false\n"
                "NoDisplay=false\n"
                "X-GNOME-Autostart-enabled=true\n"
            )
        logger.info("Autoarranque activado.")
        return True
    except Exception as e:
        logger.error(f"Error activando autoarranque: {e}")
        return False


def desactivar_autoarranque() -> bool:
    try:
        if sys.platform == "win32":
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run",
                0, winreg.KEY_SET_VALUE,
            )
            try:
                winreg.DeleteValue(key, "PosturaMonitor")
            except FileNotFoundError:
                pass
            winreg.CloseKey(key)
        else:
            desktop = Path.home() / ".config" / "autostart" / "postura-monitor.desktop"
            if desktop.exists():
                desktop.unlink()
        logger.info("Autoarranque desactivado.")
        return True
    except Exception as e:
        logger.error(f"Error desactivando autoarranque: {e}")
        return False


def autoarranque_activo() -> bool:
    try:
        if sys.platform == "win32":
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run",
                0, winreg.KEY_READ,
            )
            try:
                winreg.QueryValueEx(key, "PosturaMonitor")
                return True
            except FileNotFoundError:
                return False
            finally:
                winreg.CloseKey(key)
        else:
            return (Path.home() / ".config" / "autostart" /
                    "postura-monitor.desktop").exists()
    except Exception:
        return False


# ── Hilos de red ──────────────────────────────────────────────────────────────

class DetectorChatID(QThread):
    resultado = Signal(str, str)

    def run(self):
        try:
            r = requests.get(
                f"https://api.telegram.org/bot{_BOT_TOKEN}/getUpdates",
                timeout=10,
            )
            data = r.json()
            if data.get("ok") and data.get("result"):
                cid = data["result"][-1]["message"]["chat"]["id"]
                self.resultado.emit(f"Chat ID detectado: {cid}", "#34c759")
            else:
                self.resultado.emit(
                    "No se encontraron mensajes. Envía un mensaje al bot primero.",
                    "orange",
                )
        except Exception as e:
            self.resultado.emit(f"Error: {str(e)[:60]}", "red")


class EnviadorPrueba(QThread):
    resultado = Signal(str, str)

    def __init__(self, chat_id: str):
        super().__init__()
        self.chat_id = chat_id

    def run(self):
        try:
            r = requests.post(
                f"https://api.telegram.org/bot{_BOT_TOKEN}/sendMessage",
                json={"chat_id": self.chat_id,
                      "text": "✅ Monitor de Postura configurado correctamente."},
                timeout=10,
            )
            if r.json().get("ok"):
                self.resultado.emit("Mensaje enviado. Revisa Telegram.", "#34c759")
            else:
                self.resultado.emit("Error al enviar mensaje.", "red")
        except Exception as e:
            self.resultado.emit(f"Error: {str(e)[:60]}", "red")


# ── Ventana principal ─────────────────────────────────────────────────────────

class OnboardingWizard(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Monitor de Postura — Configuración")

        # ── Tamaño adaptativo a la pantalla ──────────────────────────────────
        screen: QScreen = QApplication.primaryScreen()
        sg = screen.availableGeometry()
        sw, sh = sg.width(), sg.height()

        # Ocupar máximo 85% del ancho y 90% del alto
        w = min(950, int(sw * 0.85))
        h = min(700, int(sh * 0.90))
        self.resize(w, h)

        # Factor de escala para fuentes e imágenes
        self._f = min(w / 950, h / 700)

        # Centrar en pantalla
        self.move(
            sg.x() + (sw - w) // 2,
            sg.y() + (sh - h) // 2,
        )
        self.setMinimumSize(480, 360)

        self.es_tema_oscuro = self._detectar_tema()
        self._aplicar_estilos()
        self._configurar_ui()

        self.terminos_aceptados  = False
        self.chat_id_validado    = False
        self.chat_id             = ""

    # ── Tema ──────────────────────────────────────────────────────────────────

    def _detectar_tema(self) -> bool:
        if hasattr(QApplication.styleHints(), "colorScheme"):
            return QApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark
        return QApplication.palette().color(QPalette.Window).lightness() < 128

    def _fs(self, size: int) -> int:
        """Font size escalado."""
        return max(9, int(size * self._f))

    def _aplicar_estilos(self):
        d   = self.es_tema_oscuro
        bg  = "#1c1c1e" if d else "#f5f5f7"
        card= "#2c2c2e" if d else "#ffffff"
        txt = "#f5f5f7" if d else "#1c1c1e"
        sub = "#aeaeb2" if d else "#6c6c70"
        brd = "#38383a" if d else "#e5e5ea"
        pri = "#0a84ff" if d else "#007aff"
        prh = "#409cff" if d else "#0051a8"
        sec = "#8e8e93"
        ok  = "#30d158" if d else "#34c759"
        hov = "#3a3a3c" if d else "#e5e5ea"
        red = "#ff453a" if d else "#ff3b30"
        f   = self._f

        self.setStyleSheet(f"""
            QMainWindow {{ background-color: {bg}; }}
            QLabel {{ color: {txt}; background: transparent; }}
            QWidget#sidebar {{
                background-color: {card};
                border-right: 1px solid {brd};
            }}
            QPushButton#navButton {{
                background: transparent; color: {txt};
                border: none; border-radius: {_escala(8,f)}px;
                text-align: left; padding: {_escala(7,f)}px {_escala(14,f)}px;
                font-size: {self._fs(13)}px; font-weight: 500;
            }}
            QPushButton#navButton:hover {{ background: {hov}; }}
            QPushButton#navButton:checked {{ background: {pri}; color: white; }}
            QPushButton {{
                background: {pri}; color: white;
                border: none; border-radius: {_escala(8,f)}px;
                padding: {_escala(7,f)}px {_escala(18,f)}px;
                font-weight: 500; font-size: {self._fs(12)}px;
            }}
            QPushButton:hover {{ background: {prh}; }}
            QPushButton#secondary {{ background: {sec}; }}
            QPushButton#secondary:hover {{ background: #7a7a7e; }}
            QPushButton#success {{ background: {ok}; }}
            QPushButton#danger {{ background: {red}; }}
            QPushButton#danger:hover {{ background: #cc2f26; }}
            QCheckBox {{ spacing: 6px; color: {txt}; font-size: {self._fs(12)}px; }}
            QGroupBox {{
                font-weight: 500; font-size: {self._fs(12)}px;
                border: 1px solid {brd}; border-radius: {_escala(10,f)}px;
                margin-top: {_escala(10,f)}px;
                background: {card}; color: {txt};
            }}
            QGroupBox::title {{
                subcontrol-origin: margin; left: {_escala(10,f)}px;
                padding: 0 6px; background: {bg};
            }}
            QLineEdit {{
                border: 1px solid {brd}; border-radius: {_escala(7,f)}px;
                padding: {_escala(6,f)}px; background: {card}; color: {txt};
                font-size: {self._fs(12)}px;
            }}
            QLineEdit:focus {{ border-color: {pri}; }}
            QTextEdit {{
                border: 1px solid {brd}; border-radius: {_escala(7,f)}px;
                background: {card}; color: {txt};
                padding: {_escala(6,f)}px; font-size: {self._fs(11)}px;
            }}
            QScrollArea {{ border: none; background: transparent; }}
            QWidget#contentArea {{ background: {bg}; }}
        """)

    # ── Layout ────────────────────────────────────────────────────────────────

    def _configurar_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        ml = QHBoxLayout(central)
        ml.setContentsMargins(0, 0, 0, 0)
        ml.setSpacing(0)

        sidebar_w = _escala(200, self._f)
        sidebar = QWidget(); sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(sidebar_w)
        sl = QVBoxLayout(sidebar)
        sl.setContentsMargins(
            _escala(16,self._f), _escala(24,self._f),
            _escala(16,self._f), _escala(24,self._f),
        )
        sl.setSpacing(6)

        logo = QLabel("Monitor de\nPostura")
        logo.setStyleSheet(
            f"font-size:{self._fs(16)}px;font-weight:bold;margin-bottom:{_escala(16,self._f)}px;"
        )
        sl.addWidget(logo)

        self.nav_buttons = []
        for texto, idx in [("Inicio",0),("Términos",1),("Telegram",2),
                           ("Preferencias",3),("Listo",4)]:
            btn = QPushButton(texto)
            btn.setObjectName("navButton")
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda _, i=idx: self.cambiar_pantalla(i))
            sl.addWidget(btn)
            self.nav_buttons.append(btn)

        sl.addStretch()

        # Botón desinstalar en sidebar
        btn_des = QPushButton("Desinstalar")
        btn_des.setObjectName("danger")
        btn_des.setCursor(Qt.PointingHandCursor)
        btn_des.clicked.connect(self._desinstalar)
        sl.addWidget(btn_des)

        ml.addWidget(sidebar)

        content = QWidget(); content.setObjectName("contentArea")
        cl = QVBoxLayout(content)
        cl.setContentsMargins(
            _escala(24,self._f), _escala(24,self._f),
            _escala(24,self._f), _escala(24,self._f),
        )
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        self.stacked = QStackedWidget()
        scroll.setWidget(self.stacked)
        cl.addWidget(scroll)
        ml.addWidget(content, stretch=1)

        for pg in [self._pagina_inicio(), self._pagina_terminos(),
                   self._pagina_telegram(), self._pagina_preferencias(),
                   self._pagina_completado()]:
            self.stacked.addWidget(pg)

        self.cambiar_pantalla(0)

    def cambiar_pantalla(self, index: int):
        if index >= 2 and not self.terminos_aceptados:
            QMessageBox.warning(self, "Aceptación requerida",
                                "Debes aceptar los términos primero.")
            return
        if index >= 4 and not self.chat_id_validado:
            QMessageBox.warning(self, "Configuración pendiente",
                                "Completa la configuración de Telegram.")
            return
        self.stacked.setCurrentIndex(index)
        for i, btn in enumerate(self.nav_buttons):
            btn.setChecked(i == index)

    # ── Página 0: Inicio ──────────────────────────────────────────────────────

    def _pagina_inicio(self):
        w = QWidget(); lay = QVBoxLayout(w)
        lay.setSpacing(_escala(16, self._f))
        lay.setContentsMargins(0,0,0,0)

        pix = cargar_imagen("monitoreo-postura.jpg",
                            (_escala(100,self._f),)*2)
        if pix:
            lbl = QLabel(); lbl.setPixmap(pix); lbl.setAlignment(Qt.AlignCenter)
            lay.addWidget(lbl)

        for text, size, extra in [
            ("Monitor de Postura", 36, "margin-top:8px;"),
            ("Cuida tu espalda mientras estudias", 16, "color:#6c6c70;"),
        ]:
            lbl = QLabel(text); lbl.setAlignment(Qt.AlignCenter)
            lbl.setStyleSheet(
                f"font-size:{self._fs(size)}px;font-weight:bold;{extra}"
                if size > 20 else
                f"font-size:{self._fs(size)}px;{extra}"
            )
            lay.addWidget(lbl)

        desc = QLabel(
            "Analiza tu postura en tiempo real con IA.\n"
            "Recibe alertas por Telegram cuando detecta una mala posición sostenida."
        )
        desc.setAlignment(Qt.AlignCenter)
        desc.setWordWrap(True)
        desc.setStyleSheet(
            f"color:#6c6c70;font-size:{self._fs(12)}px;"
            "background:rgba(0,0,0,0.05);border-radius:10px;padding:12px;"
        )
        lay.addWidget(desc)

        row = QHBoxLayout(); row.setSpacing(_escala(40, self._f))
        for img, texto in [("IA.jpg","Detección con IA"),
                           ("telegram.png","Alertas Telegram"),
                           ("supabase.jpg","Datos en la nube")]:
            col = QVBoxLayout()
            p = cargar_imagen(img, (_escala(40,self._f),)*2)
            ic = QLabel(); ic.setAlignment(Qt.AlignCenter)
            if p: ic.setPixmap(p)
            else: ic.setText("●"); ic.setStyleSheet(f"font-size:{self._fs(32)}px;color:#007aff;")
            col.addWidget(ic)
            lt = QLabel(texto); lt.setAlignment(Qt.AlignCenter)
            lt.setStyleSheet(f"color:#6c6c70;font-size:{self._fs(11)}px;font-weight:500;")
            col.addWidget(lt)
            fr = QWidget(); fr.setLayout(col); row.addWidget(fr)
        lay.addLayout(row)

        lay.addStretch()
        btn = QPushButton("Comenzar configuración")
        btn.setFixedWidth(_escala(240, self._f))
        btn.clicked.connect(lambda: self.cambiar_pantalla(1))
        lay.addWidget(btn, alignment=Qt.AlignCenter)
        lay.addStretch()
        return w

    # ── Página 1: Términos ────────────────────────────────────────────────────

    def _pagina_terminos(self):
        w = QWidget(); lay = QVBoxLayout(w); lay.setSpacing(_escala(14,self._f))
        tit = QLabel("Términos y Condiciones")
        tit.setStyleSheet(f"font-size:{self._fs(22)}px;font-weight:bold;")
        lay.addWidget(tit)

        te = QTextEdit(); te.setReadOnly(True)
        te.setPlainText(
            "TÉRMINOS Y CONDICIONES DE USO\n\n"
            "1. ACEPTACIÓN\nAl utilizar este software, aceptas estos términos.\n\n"
            "2. PRIVACIDAD\n"
            "- Los datos de postura se almacenan en Supabase (nube).\n"
            "- Las imágenes NO se guardan ni transmiten.\n"
            "- Los datos se usan para análisis académico anonimizado.\n\n"
            "3. CÁMARA\nSe requiere acceso a la cámara web. "
            "Las imágenes se procesan localmente en tu equipo.\n\n"
            "4. NOTIFICACIONES\nEl sistema enviará alertas a tu cuenta de Telegram configurada.\n\n"
            "5. RESPONSABILIDAD\nHerramienta de asistencia. No reemplaza consejo médico.\n\n"
            "6. LEY APLICABLE\nRepública del Ecuador."
        )
        lay.addWidget(te)

        self.chk_terminos = QCheckBox("He leído y acepto los términos y condiciones")
        lay.addWidget(self.chk_terminos)

        row = QHBoxLayout()
        back = QPushButton("Atrás"); back.setObjectName("secondary")
        back.clicked.connect(lambda: self.cambiar_pantalla(0))
        nxt = QPushButton("Aceptar y continuar"); nxt.setEnabled(False)
        nxt.clicked.connect(self._aceptar_terminos)
        self.chk_terminos.stateChanged.connect(
            lambda: nxt.setEnabled(self.chk_terminos.isChecked())
        )
        row.addWidget(back); row.addStretch(); row.addWidget(nxt)
        lay.addLayout(row)
        return w

    def _aceptar_terminos(self):
        if self.chk_terminos.isChecked():
            self.terminos_aceptados = True
            self.cambiar_pantalla(2)

    # ── Página 2: Telegram ────────────────────────────────────────────────────

    def _pagina_telegram(self):
        w = QWidget(); lay = QVBoxLayout(w); lay.setSpacing(_escala(14,self._f))

        tit = QLabel("Configuración de Telegram")
        tit.setStyleSheet(f"font-size:{self._fs(22)}px;font-weight:bold;")
        lay.addWidget(tit)

        card = QGroupBox()
        cr = QHBoxLayout()
        cr.addWidget(QLabel("Bot:"))
        lbl_bot = QLabel(_BOT_USERNAME)
        lbl_bot.setStyleSheet("font-weight:bold;color:#007aff;")
        cr.addWidget(lbl_bot)
        btn_cpy = QPushButton("Copiar"); btn_cpy.setFixedWidth(70)
        btn_cpy.clicked.connect(self._copiar_bot)
        cr.addWidget(btn_cpy); cr.addStretch()
        card.setLayout(cr); lay.addWidget(card)

        info = QLabel(
            f"1. Busca <b>{_BOT_USERNAME}</b> en Telegram y envíale cualquier mensaje\n"
            "2. Haz clic en <b>Detectar mi Chat ID</b>"
        )
        info.setTextFormat(Qt.RichText)
        info.setStyleSheet(f"color:#6c6c70;font-size:{self._fs(12)}px;")
        lay.addWidget(info)

        g_auto = QGroupBox("Detección automática")
        al = QVBoxLayout()
        btn_det = QPushButton("Detectar mi Chat ID")
        btn_det.clicked.connect(self._detectar_chat_id)
        al.addWidget(btn_det)
        self.lbl_resultado = QLabel("")
        self.lbl_resultado.setAlignment(Qt.AlignCenter)
        al.addWidget(self.lbl_resultado)
        g_auto.setLayout(al); lay.addWidget(g_auto)

        g_man = QGroupBox("O ingrésalo manualmente")
        ml = QVBoxLayout()
        self.input_chat = QLineEdit()
        self.input_chat.setPlaceholderText("Ej: 123456789")
        ml.addWidget(self.input_chat)
        btn_prueba = QPushButton("Enviar mensaje de prueba")
        btn_prueba.clicked.connect(self._enviar_prueba)
        ml.addWidget(btn_prueba)
        self.lbl_prueba = QLabel(""); self.lbl_prueba.setAlignment(Qt.AlignCenter)
        ml.addWidget(self.lbl_prueba)
        g_man.setLayout(ml); lay.addWidget(g_man)

        lay.addStretch()
        row = QHBoxLayout()
        back = QPushButton("Atrás"); back.setObjectName("secondary")
        back.clicked.connect(lambda: self.cambiar_pantalla(1))
        nxt = QPushButton("Guardar y continuar")
        nxt.clicked.connect(self._guardar_y_avanzar)
        row.addWidget(back); row.addStretch(); row.addWidget(nxt)
        lay.addLayout(row)
        return w

    def _copiar_bot(self):
        QApplication.clipboard().setText(_BOT_USERNAME)
        QMessageBox.information(self, "Copiado", f"'{_BOT_USERNAME}' copiado.")

    def _detectar_chat_id(self):
        self.lbl_resultado.setText("Consultando..."); self.lbl_resultado.setStyleSheet("color:orange;")
        self._detector_hilo = DetectorChatID()
        self._detector_hilo.resultado.connect(self._on_detectar)
        self._detector_hilo.start()

    def _on_detectar(self, texto, color):
        self.lbl_resultado.setText(texto); self.lbl_resultado.setStyleSheet(f"color:{color};")
        if "detectado" in texto:
            m = re.search(r"\d+", texto)
            if m: self.input_chat.setText(m.group())

    def _enviar_prueba(self):
        cid = self.input_chat.text().strip()
        if not cid:
            self.lbl_prueba.setText("Ingresa tu Chat ID primero"); self.lbl_prueba.setStyleSheet("color:orange;"); return
        self.lbl_prueba.setText("Enviando..."); self.lbl_prueba.setStyleSheet("color:blue;")
        self._enviador_hilo = EnviadorPrueba(cid)
        self._enviador_hilo.resultado.connect(self._on_prueba)
        self._enviador_hilo.start()

    def _on_prueba(self, texto, color):
        self.lbl_prueba.setText(texto); self.lbl_prueba.setStyleSheet(f"color:{color};")

    def _guardar_y_avanzar(self):
        cid = self.input_chat.text().strip()
        if not cid:
            QMessageBox.warning(self, "Chat ID requerido", "Detecta o ingresa tu Chat ID."); return
        self.chat_id = cid
        from config.settings import CONFIG_DIR
        (CONFIG_DIR / "config.env").write_text(f"TELEGRAM_CHAT_ID={cid}\n", encoding="utf-8")
        os.environ["TELEGRAM_CHAT_ID"] = cid
        logger.info(f"Chat ID guardado.")
        self.chat_id_validado = True
        self.cambiar_pantalla(3)

    # ── Página 3: Preferencias ────────────────────────────────────────────────

    def _pagina_preferencias(self):
        w = QWidget(); lay = QVBoxLayout(w); lay.setSpacing(_escala(16,self._f))

        tit = QLabel("Preferencias")
        tit.setStyleSheet(f"font-size:{self._fs(22)}px;font-weight:bold;")
        lay.addWidget(tit)

        # Autoarranque
        g_auto = QGroupBox("Inicio automático")
        al = QVBoxLayout()
        desc_auto = QLabel(
            "Si lo activas, el monitor se iniciará automáticamente\n"
            "cada vez que enciendas tu computadora."
        )
        desc_auto.setStyleSheet(f"color:#6c6c70;font-size:{self._fs(11)}px;")
        desc_auto.setWordWrap(True)
        al.addWidget(desc_auto)

        self.chk_autoarranque = QCheckBox("Iniciar Monitor de Postura con el sistema")
        self.chk_autoarranque.setChecked(autoarranque_activo())
        al.addWidget(self.chk_autoarranque)
        g_auto.setLayout(al); lay.addWidget(g_auto)

        # Info
        info = QLabel(
            "💡 Puedes cambiar estas preferencias más adelante\n"
            "ejecutando el comando: postura-monitor --configurar"
        )
        info.setStyleSheet(f"color:#6c6c70;font-size:{self._fs(11)}px;"
                          "background:rgba(0,122,255,0.08);border-radius:8px;padding:10px;")
        info.setWordWrap(True)
        lay.addWidget(info)

        lay.addStretch()
        row = QHBoxLayout()
        back = QPushButton("Atrás"); back.setObjectName("secondary")
        back.clicked.connect(lambda: self.cambiar_pantalla(2))
        nxt = QPushButton("Guardar y finalizar")
        nxt.setObjectName("success")
        nxt.clicked.connect(self._guardar_preferencias)
        row.addWidget(back); row.addStretch(); row.addWidget(nxt)
        lay.addLayout(row)
        return w

    def _guardar_preferencias(self):
        if self.chk_autoarranque.isChecked():
            activar_autoarranque()
        else:
            desactivar_autoarranque()
        self.cambiar_pantalla(4)

    # ── Página 4: Completado ──────────────────────────────────────────────────

    def _pagina_completado(self):
        w = QWidget(); lay = QVBoxLayout(w); lay.setSpacing(_escala(16,self._f))

        tit = QLabel("¡Todo listo!")
        tit.setAlignment(Qt.AlignCenter)
        tit.setStyleSheet(f"font-size:{self._fs(30)}px;font-weight:bold;")
        lay.addWidget(tit)

        auto_txt = "✓ Se iniciará automáticamente con el sistema" \
                   if autoarranque_activo() else \
                   "→ Inicio manual (ejecuta 'postura-monitor')"

        msg = QLabel(
            f"✓ Telegram configurado correctamente\n"
            f"✓ Datos guardados en ~/.config/postura-monitor/\n"
            f"{auto_txt}"
        )
        msg.setAlignment(Qt.AlignCenter)
        msg.setStyleSheet(f"color:#6c6c70;font-size:{self._fs(13)}px;")
        lay.addWidget(msg)

        lay.addStretch()
        btn = QPushButton("Iniciar Monitor")
        btn.setObjectName("success")
        btn.setFixedWidth(_escala(200, self._f))
        btn.clicked.connect(self._finalizar)
        lay.addWidget(btn, alignment=Qt.AlignCenter)
        lay.addStretch()
        return w

    def _finalizar(self):
        OnboardingEstado().marcar_completado()
        self.close()

    # ── Desinstalar ───────────────────────────────────────────────────────────

    def _desinstalar(self):
        resp = QMessageBox.question(
            self, "Desinstalar Monitor de Postura",
            "¿Estás seguro de que deseas desinstalar el programa?\n\n"
            "Se eliminarán los archivos de la aplicación.\n"
            "Tu configuración de Telegram NO se eliminará.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if resp != QMessageBox.Yes:
            return

        exito = False
        try:
            desactivar_autoarranque()
            if sys.platform == "win32":
                # Buscar desinstalador de Windows
                import winreg
                key = winreg.OpenKey(
                    winreg.HKEY_LOCAL_MACHINE,
                    r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\Monitor de Postura_is1",
                    0, winreg.KEY_READ,
                )
                uninstall, _ = winreg.QueryValueEx(key, "UninstallString")
                winreg.CloseKey(key)
                subprocess.Popen([uninstall, "/SILENT"])
                exito = True
            else:
                # Linux: dpkg -r
                result = subprocess.run(
                    ["pkexec", "dpkg", "-r", "postura-monitor"],
                    capture_output=True, text=True,
                )
                exito = result.returncode == 0
                if not exito:
                    # Intentar con sudo directo
                    result2 = subprocess.run(
                        ["sudo", "dpkg", "-r", "postura-monitor"],
                        capture_output=True, text=True,
                    )
                    exito = result2.returncode == 0
        except Exception as e:
            logger.error(f"Error en desinstalación: {e}")

        if exito:
            QMessageBox.information(
                self, "Desinstalado",
                "Monitor de Postura se ha desinstalado correctamente."
            )
            QApplication.quit()
        else:
            QMessageBox.warning(
                self, "Error",
                "No se pudo desinstalar automáticamente.\n\n"
                "En Linux ejecuta:\n  sudo dpkg -r postura-monitor\n\n"
                "En Windows usa:\n  Panel de Control → Programas → Desinstalar"
            )


# ── Función de entrada ────────────────────────────────────────────────────────

def mostrar_onboarding_si_necesario() -> bool:
    estado = OnboardingEstado()
    if estado.completado:
        return True
    try:
        app = QApplication.instance() or QApplication(sys.argv)
        wizard = OnboardingWizard()
        wizard.show()
        app.exec()
        return OnboardingEstado().completado
    except Exception as e:
        logger.error(f"Error iniciando wizard: {e}")
        return False


def mostrar_configuracion() -> None:
    """Permite reabrir el wizard desde --configurar."""
    try:
        app = QApplication.instance() or QApplication(sys.argv)
        wizard = OnboardingWizard()
        wizard.cambiar_pantalla(3)  # Abrir directo en Preferencias
        wizard.show()
        app.exec()
    except Exception as e:
        logger.error(f"Error abriendo configuración: {e}")
