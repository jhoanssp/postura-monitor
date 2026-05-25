"""
Asistente de configuración inicial - PySide6 (Qt6)
El usuario solo necesita proveer su TELEGRAM_CHAT_ID.
Las credenciales del bot y Supabase están integradas en la app.
"""

import sys
import os
import re
import requests
from pathlib import Path

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QCheckBox, QTextEdit, QLineEdit, QGroupBox,
    QMessageBox, QStackedWidget, QFrame, QScrollArea
)
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QFont, QPalette, QColor, QPixmap

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from utils.logger import crear_logger
from onboarding.estado import OnboardingEstado
from config.credentials import get_telegram_bot_token, get_bot_username

logger = crear_logger("onboarding_wizard")

# Credenciales obtenidas de módulo ofuscado — NO están en texto plano aquí
_BOT_TOKEN    = get_telegram_bot_token()
_BOT_USERNAME = get_bot_username()

IMG_DIR = Path(__file__).parent / "img"


def cargar_imagen(nombre, tamaño=(48, 48)):
    ruta = IMG_DIR / nombre
    if ruta.exists():
        pix = QPixmap(str(ruta))
        if not pix.isNull():
            return pix.scaled(tamaño[0], tamaño[1], Qt.KeepAspectRatio, Qt.SmoothTransformation)
    return None


# ── Hilos de red ──────────────────────────────────────────────────────────────

class DetectorChatID(QThread):
    resultado = Signal(str, str)

    def run(self):
        try:
            url = f"https://api.telegram.org/bot{_BOT_TOKEN}/getUpdates"
            r = requests.get(url, timeout=10)
            data = r.json()
            if data.get("ok") and data.get("result"):
                ultimo = data["result"][-1]
                cid = ultimo["message"]["chat"]["id"]
                self.resultado.emit(f"Chat ID detectado: {cid}", "#34c759")
            else:
                self.resultado.emit(
                    "No se encontraron mensajes. Envía un mensaje al bot primero.", "orange"
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
            url = f"https://api.telegram.org/bot{_BOT_TOKEN}/sendMessage"
            payload = {
                "chat_id": self.chat_id,
                "text": "✅ Conexión exitosa. Tu monitor de postura está configurado.",
            }
            r = requests.post(url, json=payload, timeout=10)
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
        self.setWindowTitle("Monitor de Postura — Configuración inicial")
        self.setFixedSize(950, 700)

        self.es_tema_oscuro = self._detectar_tema()
        self._aplicar_estilos()
        self._configurar_ui()

        self.terminos_aceptados = False
        self.chat_id_validado   = False
        self.chat_id            = ""

    # ── Tema ──────────────────────────────────────────────────────────────────

    def _detectar_tema(self) -> bool:
        if hasattr(QApplication.styleHints(), "colorScheme"):
            return QApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark
        bg = QApplication.palette().color(QPalette.Window)
        return bg.lightness() < 128

    def _aplicar_estilos(self):
        d = self.es_tema_oscuro
        bg   = "#1c1c1e" if d else "#f5f5f7"
        card = "#2c2c2e" if d else "#ffffff"
        txt  = "#f5f5f7" if d else "#1c1c1e"
        sub  = "#aeaeb2" if d else "#6c6c70"
        brd  = "#38383a" if d else "#e5e5ea"
        pri  = "#0a84ff" if d else "#007aff"
        prih = "#409cff" if d else "#0051a8"
        sec  = "#8e8e93"
        ok   = "#30d158" if d else "#34c759"
        hov  = "#3a3a3c" if d else "#e5e5ea"

        self.setStyleSheet(f"""
            QMainWindow {{ background-color: {bg}; }}
            QLabel {{ color: {txt}; background: transparent; }}
            QWidget#sidebar {{
                background-color: {card};
                border-right: 1px solid {brd};
            }}
            QPushButton#navButton {{
                background-color: transparent; color: {txt};
                border: none; border-radius: 8px;
                text-align: left; padding: 8px 16px;
                font-size: 14px; font-weight: 500;
            }}
            QPushButton#navButton:hover {{ background-color: {hov}; }}
            QPushButton#navButton:checked {{ background-color: {pri}; color: white; }}
            QPushButton {{
                background-color: {pri}; color: white;
                border: none; border-radius: 8px;
                padding: 8px 20px; font-weight: 500; font-size: 13px;
            }}
            QPushButton:hover {{ background-color: {prih}; }}
            QPushButton#secondary {{ background-color: {sec}; }}
            QPushButton#secondary:hover {{ background-color: #7a7a7e; }}
            QPushButton#success {{ background-color: {ok}; }}
            QCheckBox {{ spacing: 8px; color: {txt}; }}
            QGroupBox {{
                font-weight: 500; border: 1px solid {brd};
                border-radius: 12px; margin-top: 12px;
                background-color: {card}; color: {txt};
            }}
            QGroupBox::title {{
                subcontrol-origin: margin; left: 12px;
                padding: 0 8px; background-color: {bg};
            }}
            QLineEdit {{
                border: 1px solid {brd}; border-radius: 8px;
                padding: 8px; background: {card}; color: {txt};
            }}
            QLineEdit:focus {{ border-color: {pri}; }}
            QTextEdit {{
                border: 1px solid {brd}; border-radius: 8px;
                background: {card}; color: {txt}; padding: 8px;
            }}
            QScrollArea {{ border: none; background: transparent; }}
            QWidget#contentArea {{ background-color: {bg}; }}
        """)

    # ── Layout principal ──────────────────────────────────────────────────────

    def _configurar_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        ml = QHBoxLayout(central)
        ml.setContentsMargins(0, 0, 0, 0)
        ml.setSpacing(0)

        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(220)
        sl = QVBoxLayout(sidebar)
        sl.setContentsMargins(20, 30, 20, 30)
        sl.setSpacing(8)

        logo = QLabel("Monitor de Postura")
        logo.setStyleSheet("font-size: 18px; font-weight: bold; margin-bottom: 20px;")
        sl.addWidget(logo)

        self.nav_buttons = []
        secciones = {"Inicio": 0, "Términos": 1, "Telegram": 2, "Listo": 3}
        for texto, idx in secciones.items():
            btn = QPushButton(texto)
            btn.setObjectName("navButton")
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda _, i=idx: self.cambiar_pantalla(i))
            sl.addWidget(btn)
            self.nav_buttons.append(btn)

        sl.addStretch()
        ml.addWidget(sidebar)

        content = QWidget()
        content.setObjectName("contentArea")
        cl = QVBoxLayout(content)
        cl.setContentsMargins(30, 30, 30, 30)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        self.stacked = QStackedWidget()
        scroll.setWidget(self.stacked)
        cl.addWidget(scroll)
        ml.addWidget(content, stretch=1)

        for pagina in [
            self._pagina_inicio(),
            self._pagina_terminos(),
            self._pagina_telegram(),
            self._pagina_completado(),
        ]:
            self.stacked.addWidget(pagina)

        self.cambiar_pantalla(0)

    def cambiar_pantalla(self, index: int):
        if index == 2 and not self.terminos_aceptados:
            QMessageBox.warning(self, "Aceptación requerida",
                                "Debes aceptar los términos antes de continuar.")
            return
        if index == 3 and not self.chat_id_validado:
            QMessageBox.warning(self, "Configuración pendiente",
                                "Completa la configuración de Telegram primero.")
            return
        self.stacked.setCurrentIndex(index)
        for i, btn in enumerate(self.nav_buttons):
            btn.setChecked(i == index)

    # ── Página 0: Inicio ──────────────────────────────────────────────────────

    def _pagina_inicio(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setSpacing(25)
        lay.setContentsMargins(0, 0, 0, 0)

        pix = cargar_imagen("monitoreo-postura.jpg", (120, 120))
        if pix:
            lbl = QLabel(); lbl.setPixmap(pix); lbl.setAlignment(Qt.AlignCenter)
            lay.addWidget(lbl)

        for text, style in [
            ("Monitor de Postura",
             "font-size: 42px; font-weight: bold; margin-top: 10px;"),
            ("Cuida tu espalda mientras estudias",
             "color: #6c6c70; font-size: 18px;"),
            ("Recibe alertas en tiempo real · Datos en la nube",
             "color: #6c6c70; font-size: 15px; margin-bottom: 15px;"),
        ]:
            lbl = QLabel(text)
            lbl.setAlignment(Qt.AlignCenter)
            lbl.setStyleSheet(style)
            lay.addWidget(lbl)

        desc = QLabel(
            "Esta aplicación usa inteligencia artificial para analizar tu postura.\n"
            "Si detecta una mala posición sostenida te enviará una notificación\n"
            "por Telegram para ayudarte a corregirla."
        )
        desc.setAlignment(Qt.AlignCenter)
        desc.setWordWrap(True)
        desc.setStyleSheet(
            "color:#6c6c70;font-size:13px;background-color:rgba(0,0,0,0.05);"
            "border-radius:12px;padding:15px;margin:5px 0 20px;"
        )
        lay.addWidget(desc)

        row = QHBoxLayout()
        row.setSpacing(50)
        for img, texto in [("IA.jpg", "Detección con IA"),
                           ("telegram.png", "Notificaciones Telegram"),
                           ("supabase.jpg", "Datos en la nube")]:
            col = QVBoxLayout()
            p = cargar_imagen(img, (48, 48))
            ic = QLabel(); ic.setAlignment(Qt.AlignCenter)
            if p:
                ic.setPixmap(p)
            else:
                ic.setText("●"); ic.setStyleSheet("font-size:48px;color:#007aff;")
            col.addWidget(ic)
            lt = QLabel(texto)
            lt.setAlignment(Qt.AlignCenter)
            lt.setStyleSheet("color:#6c6c70;font-size:14px;font-weight:500;margin-top:8px;")
            col.addWidget(lt)
            fr = QWidget(); fr.setLayout(col)
            row.addWidget(fr)
        lay.addLayout(row)

        lay.addStretch()
        btn = QPushButton("Comenzar configuración")
        btn.setFixedWidth(260)
        btn.setStyleSheet("font-size:14px;padding:10px;")
        btn.clicked.connect(lambda: self.cambiar_pantalla(1))
        lay.addWidget(btn, alignment=Qt.AlignCenter)
        lay.addStretch()
        return w

    # ── Página 1: Términos ────────────────────────────────────────────────────

    def _pagina_terminos(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setSpacing(16)

        tit = QLabel("Términos y Condiciones")
        tit.setStyleSheet("font-size:24px;font-weight:bold;")
        lay.addWidget(tit)

        te = QTextEdit()
        te.setReadOnly(True)
        te.setPlainText("""TÉRMINOS Y CONDICIONES DE USO

1. ACEPTACIÓN
Al utilizar este software, aceptas estos términos.

2. PRIVACIDAD DE DATOS
- Los datos de postura se almacenan en Supabase (nube).
- Las imágenes de la cámara NO se guardan ni transmiten.
- Los datos se usan para análisis académico anonimizado.

3. USO DE LA CÁMARA
Se requiere acceso a la cámara web. Las imágenes se procesan localmente en tu equipo.

4. NOTIFICACIONES
El sistema enviará alertas a tu cuenta de Telegram configurada.

5. RESPONSABILIDAD
Esta es una herramienta de asistencia. No reemplaza consejo médico profesional.

6. LEY APLICABLE
República del Ecuador.

Al hacer clic en "Acepto", confirmas que has leído y aceptas estos términos.""")
        lay.addWidget(te)

        self.chk_terminos = QCheckBox("He leído y acepto los términos y condiciones")
        lay.addWidget(self.chk_terminos)

        lay.addSpacing(10)
        row = QHBoxLayout()
        back = QPushButton("Atrás")
        back.setObjectName("secondary")
        back.clicked.connect(lambda: self.cambiar_pantalla(0))
        nxt = QPushButton("Aceptar y continuar")
        nxt.setEnabled(False)
        nxt.clicked.connect(self._aceptar_terminos)
        self.chk_terminos.stateChanged.connect(lambda: nxt.setEnabled(self.chk_terminos.isChecked()))
        row.addWidget(back); row.addStretch(); row.addWidget(nxt)
        lay.addLayout(row)
        return w

    def _aceptar_terminos(self):
        if self.chk_terminos.isChecked():
            self.terminos_aceptados = True
            self.cambiar_pantalla(2)

    # ── Página 2: Telegram ────────────────────────────────────────────────────

    def _pagina_telegram(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setSpacing(20)

        pix = cargar_imagen("telegram.png", (64, 64))
        if pix:
            lbl = QLabel(); lbl.setPixmap(pix); lbl.setAlignment(Qt.AlignCenter)
            lay.addWidget(lbl)

        tit = QLabel("Configuración de Telegram")
        tit.setAlignment(Qt.AlignCenter)
        tit.setStyleSheet("font-size:24px;font-weight:bold;")
        lay.addWidget(tit)

        # Tarjeta del bot
        card = QGroupBox()
        cr = QHBoxLayout()
        cr.addWidget(QLabel("Bot de Telegram:"))
        lbl_bot = QLabel(_BOT_USERNAME)
        lbl_bot.setStyleSheet("font-weight:bold;color:#007aff;")
        cr.addWidget(lbl_bot)
        btn_cpy = QPushButton("Copiar")
        btn_cpy.setFixedWidth(80)
        btn_cpy.clicked.connect(self._copiar_bot)
        cr.addWidget(btn_cpy)
        cr.addStretch()
        card.setLayout(cr)
        lay.addWidget(card)

        info = QLabel(
            f"1. Busca <b>{_BOT_USERNAME}</b> en Telegram y envíale cualquier mensaje\n"
            "2. Haz clic en <b>'Detectar mi Chat ID'</b> para obtenerlo automáticamente"
        )
        info.setTextFormat(Qt.RichText)
        info.setStyleSheet("color:#6c6c70;")
        lay.addWidget(info)

        # Detección automática
        g_auto = QGroupBox("Detección automática del Chat ID")
        al = QVBoxLayout()
        btn_det = QPushButton("Detectar mi Chat ID")
        btn_det.clicked.connect(self._detectar_chat_id)
        al.addWidget(btn_det)
        self.lbl_resultado = QLabel("")
        self.lbl_resultado.setAlignment(Qt.AlignCenter)
        al.addWidget(self.lbl_resultado)
        g_auto.setLayout(al)
        lay.addWidget(g_auto)

        # Ingreso manual
        g_man = QGroupBox("O ingrésalo manualmente")
        ml = QVBoxLayout()
        self.input_chat = QLineEdit()
        self.input_chat.setPlaceholderText("Ej: 123456789")
        ml.addWidget(self.input_chat)
        btn_prueba = QPushButton("Enviar mensaje de prueba")
        btn_prueba.clicked.connect(self._enviar_prueba)
        ml.addWidget(btn_prueba)
        self.lbl_prueba = QLabel("")
        self.lbl_prueba.setAlignment(Qt.AlignCenter)
        ml.addWidget(self.lbl_prueba)
        g_man.setLayout(ml)
        lay.addWidget(g_man)

        lay.addStretch()
        row = QHBoxLayout()
        back = QPushButton("Atrás")
        back.setObjectName("secondary")
        back.clicked.connect(lambda: self.cambiar_pantalla(1))
        nxt = QPushButton("Guardar y continuar")
        nxt.clicked.connect(self._guardar_y_avanzar)
        row.addWidget(back); row.addStretch(); row.addWidget(nxt)
        lay.addLayout(row)
        return w

    def _copiar_bot(self):
        QApplication.clipboard().setText(_BOT_USERNAME)
        QMessageBox.information(self, "Copiado", f"'{_BOT_USERNAME}' copiado al portapapeles")

    def _detectar_chat_id(self):
        self.lbl_resultado.setText("Consultando...")
        self.lbl_resultado.setStyleSheet("color:orange;")
        self._detector_hilo = DetectorChatID()
        self._detector_hilo.resultado.connect(self._on_detectar)
        self._detector_hilo.start()

    def _on_detectar(self, texto: str, color: str):
        self.lbl_resultado.setText(texto)
        self.lbl_resultado.setStyleSheet(f"color:{color};")
        if "detectado" in texto:
            m = re.search(r"\d+", texto)
            if m:
                self.input_chat.setText(m.group())

    def _enviar_prueba(self):
        cid = self.input_chat.text().strip()
        if not cid:
            self.lbl_prueba.setText("Detecta o ingresa tu Chat ID primero")
            self.lbl_prueba.setStyleSheet("color:orange;")
            return
        self.lbl_prueba.setText("Enviando...")
        self.lbl_prueba.setStyleSheet("color:blue;")
        self._enviador_hilo = EnviadorPrueba(cid)
        self._enviador_hilo.resultado.connect(self._on_prueba)
        self._enviador_hilo.start()

    def _on_prueba(self, texto: str, color: str):
        self.lbl_prueba.setText(texto)
        self.lbl_prueba.setStyleSheet(f"color:{color};")

    def _guardar_y_avanzar(self):
        cid = self.input_chat.text().strip()
        if not cid:
            QMessageBox.warning(self, "Chat ID requerido",
                                "Debes detectar o ingresar manualmente tu Chat ID.")
            return
        self.chat_id = cid

        # Guardar SOLO el Chat ID del usuario en su directorio de config
        from config.settings import CONFIG_DIR
        env_path = CONFIG_DIR / "config.env"
        with open(env_path, "w", encoding="utf-8") as f:
            f.write(f"TELEGRAM_CHAT_ID={cid}\n")

        # Actualizar entorno en memoria para esta sesión
        os.environ["TELEGRAM_CHAT_ID"] = cid

        logger.info(f"Chat ID guardado en {env_path}")
        self.chat_id_validado = True
        self.cambiar_pantalla(3)

    # ── Página 3: Completado ──────────────────────────────────────────────────

    def _pagina_completado(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setSpacing(20)

        tit = QLabel("¡Todo listo!")
        tit.setAlignment(Qt.AlignCenter)
        tit.setStyleSheet("font-size:32px;font-weight:bold;")
        lay.addWidget(tit)

        msg = QLabel(
            "Tu monitor de postura está configurado.\n\n"
            "✓ La cámara se activará automáticamente\n"
            "✓ Recibirás alertas por Telegram\n"
            "✓ Los datos se guardarán de forma segura en la nube"
        )
        msg.setAlignment(Qt.AlignCenter)
        msg.setStyleSheet("color:#6c6c70;font-size:14px;")
        lay.addWidget(msg)

        lay.addStretch()
        btn = QPushButton("Iniciar Monitor")
        btn.setObjectName("success")
        btn.setFixedWidth(200)
        btn.clicked.connect(self._finalizar)
        lay.addWidget(btn, alignment=Qt.AlignCenter)

        nota = QLabel("Tu configuración se guardó en ~/.config/postura-monitor/")
        nota.setAlignment(Qt.AlignCenter)
        nota.setStyleSheet("color:#6c6c70;font-size:11px;margin-top:20px;")
        lay.addWidget(nota)
        lay.addStretch()
        return w

    def _finalizar(self):
        OnboardingEstado().marcar_completado()
        self.close()


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
        print("\n❌ Error: No se pudo iniciar el asistente de configuración.")
        print("Instala PySide6: pip install PySide6\n")
        return False
