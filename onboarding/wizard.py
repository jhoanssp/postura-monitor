"""
Asistente de configuración inicial — v4.3
- Logo en sidebar
- Multiidioma (ES / EN)
- Ventana adaptativa
- Autoarranque opcional
- Botón desinstalar
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
    QMessageBox, QStackedWidget, QFrame, QScrollArea, QButtonGroup,
    QRadioButton,
)
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QPalette, QPixmap, QScreen

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from utils.logger import crear_logger
from onboarding.estado import OnboardingEstado
from config.credentials import get_telegram_bot_token, get_bot_username
from config.i18n import I18n, t

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


def _s(base: int, f: float) -> int:
    return max(int(base * f), int(base * 0.6))


# ── Autoarranque ──────────────────────────────────────────────────────────────

def _exe_path() -> str:
    return sys.executable if getattr(sys, "frozen", False) \
           else str(Path(__file__).resolve().parent.parent / "main.py")


def activar_autoarranque() -> bool:
    try:
        if sys.platform == "win32":
            import winreg
            k = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                r"Software\\Microsoft\\Windows\\CurrentVersion\\Run",
                0, winreg.KEY_SET_VALUE)
            winreg.SetValueEx(k, "PosturaMonitor", 0, winreg.REG_SZ,
                f'"{_exe_path()}" --modo produccion --skip-onboarding')
            winreg.CloseKey(k)
        else:
            d = Path.home() / ".config" / "autostart"
            d.mkdir(parents=True, exist_ok=True)
            exe = "/opt/postura-monitor/postura-monitor" \
                  if Path("/opt/postura-monitor/postura-monitor").exists() \
                  else _exe_path()
            (d / "postura-monitor.desktop").write_text(
                "[Desktop Entry]\nType=Application\nName=Monitor de Postura\n"
                f"Exec={exe} --modo produccion --skip-onboarding\n"
                "Hidden=false\nNoDisplay=false\nX-GNOME-Autostart-enabled=true\n"
            )
        return True
    except Exception as e:
        logger.error(f"Autoarranque: {e}"); return False


def desactivar_autoarranque() -> bool:
    try:
        if sys.platform == "win32":
            import winreg
            k = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                r"Software\\Microsoft\\Windows\\CurrentVersion\\Run",
                0, winreg.KEY_SET_VALUE)
            try: winreg.DeleteValue(k, "PosturaMonitor")
            except FileNotFoundError: pass
            winreg.CloseKey(k)
        else:
            p = Path.home() / ".config" / "autostart" / "postura-monitor.desktop"
            if p.exists(): p.unlink()
        return True
    except Exception as e:
        logger.error(f"Desactivar autoarranque: {e}"); return False


def autoarranque_activo() -> bool:
    try:
        if sys.platform == "win32":
            import winreg
            k = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                r"Software\\Microsoft\\Windows\\CurrentVersion\\Run", 0, winreg.KEY_READ)
            try: winreg.QueryValueEx(k, "PosturaMonitor"); return True
            except FileNotFoundError: return False
            finally: winreg.CloseKey(k)
        else:
            return (Path.home() / ".config" / "autostart" / "postura-monitor.desktop").exists()
    except: return False


# ── Hilos de red ──────────────────────────────────────────────────────────────

class DetectorChatID(QThread):
    resultado = Signal(str, str)
    def run(self):
        try:
            r = requests.get(f"https://api.telegram.org/bot{_BOT_TOKEN}/getUpdates", timeout=10)
            data = r.json()
            if data.get("ok") and data.get("result"):
                cid = data["result"][-1]["message"]["chat"]["id"]
                self.resultado.emit(f"Chat ID: {cid}", "#34c759")
            else:
                self.resultado.emit(t("telegram_sin_id"), "orange")
        except Exception as e:
            self.resultado.emit(f"Error: {str(e)[:60]}", "red")


class EnviadorPrueba(QThread):
    resultado = Signal(str, str)
    def __init__(self, chat_id):
        super().__init__(); self.chat_id = chat_id
    def run(self):
        try:
            r = requests.post(
                f"https://api.telegram.org/bot{_BOT_TOKEN}/sendMessage",
                json={"chat_id": self.chat_id, "text": t("notif_conexion_ok")},
                timeout=10,
            )
            if r.json().get("ok"):
                self.resultado.emit("✓ " + ("Mensaje enviado" if I18n.idioma()=="es" else "Message sent"), "#34c759")
            else:
                self.resultado.emit("Error", "red")
        except Exception as e:
            self.resultado.emit(f"Error: {str(e)[:60]}", "red")


# ── Ventana ───────────────────────────────────────────────────────────────────

class OnboardingWizard(QMainWindow):
    def __init__(self):
        super().__init__()

        # Escala adaptativa
        screen: QScreen = QApplication.primaryScreen()
        sg = screen.availableGeometry()
        w = min(960, int(sg.width()  * 0.85))
        h = min(700, int(sg.height() * 0.90))
        self.resize(w, h)
        self.setMinimumSize(500, 380)
        self.move(sg.x() + (sg.width()-w)//2, sg.y() + (sg.height()-h)//2)
        self._f = min(w/960, h/700)

        self.terminos_aceptados = False
        self.chat_id_validado   = False
        self.chat_id            = ""

        self._detectar_tema()
        self._aplicar_estilos()
        self._build_ui()
        self._actualizar_textos()

    # ── Tema ──────────────────────────────────────────────────────────────────

    def _detectar_tema(self):
        if hasattr(QApplication.styleHints(), "colorScheme"):
            self._dark = QApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark
        else:
            self._dark = QApplication.palette().color(QPalette.Window).lightness() < 128

    def _aplicar_estilos(self):
        d = self._dark
        f = self._f
        bg   = "#1c1c1e" if d else "#f5f5f7"
        card = "#2c2c2e" if d else "#ffffff"
        txt  = "#f5f5f7" if d else "#1c1c1e"
        brd  = "#38383a" if d else "#e5e5ea"
        pri  = "#0a84ff" if d else "#007aff"
        prh  = "#409cff" if d else "#0051a8"
        sec  = "#8e8e93"
        ok   = "#30d158" if d else "#34c759"
        hov  = "#3a3a3c" if d else "#e5e5ea"
        red  = "#ff453a" if d else "#ff3b30"
        fs   = lambda n: max(9, int(n * f))

        self.setStyleSheet(f"""
            QMainWindow {{ background:{bg}; }}
            QLabel {{ color:{txt}; background:transparent; }}
            QWidget#sidebar {{ background:{card}; border-right:1px solid {brd}; }}
            QPushButton#navButton {{
                background:transparent; color:{txt}; border:none;
                border-radius:{_s(8,f)}px; text-align:left;
                padding:{_s(7,f)}px {_s(14,f)}px; font-size:{fs(13)}px; font-weight:500;
            }}
            QPushButton#navButton:hover {{ background:{hov}; }}
            QPushButton#navButton:checked {{ background:{pri}; color:white; }}
            QPushButton {{
                background:{pri}; color:white; border:none;
                border-radius:{_s(8,f)}px; padding:{_s(7,f)}px {_s(18,f)}px;
                font-weight:500; font-size:{fs(12)}px;
            }}
            QPushButton:hover {{ background:{prh}; }}
            QPushButton#secondary {{ background:{sec}; }}
            QPushButton#secondary:hover {{ background:#7a7a7e; }}
            QPushButton#success {{ background:{ok}; }}
            QPushButton#danger {{ background:{red}; }}
            QPushButton#danger:hover {{ background:#cc2f26; }}
            QCheckBox {{ spacing:6px; color:{txt}; font-size:{fs(12)}px; }}
            QRadioButton {{ spacing:6px; color:{txt}; font-size:{fs(12)}px; }}
            QGroupBox {{
                font-weight:500; font-size:{fs(12)}px;
                border:1px solid {brd}; border-radius:{_s(10,f)}px;
                margin-top:{_s(10,f)}px; background:{card}; color:{txt};
            }}
            QGroupBox::title {{ subcontrol-origin:margin; left:{_s(10,f)}px; padding:0 6px; background:{bg}; }}
            QLineEdit {{
                border:1px solid {brd}; border-radius:{_s(7,f)}px;
                padding:{_s(6,f)}px; background:{card}; color:{txt}; font-size:{fs(12)}px;
            }}
            QLineEdit:focus {{ border-color:{pri}; }}
            QTextEdit {{
                border:1px solid {brd}; border-radius:{_s(7,f)}px;
                background:{card}; color:{txt}; padding:{_s(6,f)}px; font-size:{fs(11)}px;
            }}
            QScrollArea {{ border:none; background:transparent; }}
            QWidget#contentArea {{ background:{bg}; }}
        """)

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        central = QWidget(); self.setCentralWidget(central)
        ml = QHBoxLayout(central); ml.setContentsMargins(0,0,0,0); ml.setSpacing(0)

        # Sidebar
        sidebar = QWidget(); sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(_s(210, self._f))
        sl = QVBoxLayout(sidebar)
        sl.setContentsMargins(_s(16,self._f), _s(20,self._f), _s(16,self._f), _s(20,self._f))
        sl.setSpacing(5)

        # Logo
        logo_pix = cargar_imagen("logo.jpg", (_s(160,self._f), _s(60,self._f)))
        if logo_pix:
            lbl_logo = QLabel(); lbl_logo.setPixmap(logo_pix)
            lbl_logo.setAlignment(Qt.AlignCenter)
            lbl_logo.setContentsMargins(0, 0, 0, _s(12, self._f))
            sl.addWidget(lbl_logo)
        else:
            # Fallback: texto si no hay logo
            lbl_logo = QLabel("Monitor de\nPostura")
            lbl_logo.setStyleSheet(
                f"font-size:{max(9,int(15*self._f))}px;font-weight:bold;"
                f"margin-bottom:{_s(12,self._f)}px;"
            )
            sl.addWidget(lbl_logo)

        # Botones de navegación
        self._nav_btns = []
        claves = ["nav_inicio","nav_terminos","nav_telegram","nav_preferencias","nav_listo"]
        for idx, clave in enumerate(claves):
            btn = QPushButton(t(clave))
            btn.setObjectName("navButton"); btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda _, i=idx: self.cambiar_pantalla(i))
            btn.setProperty("i18n_key", clave)
            sl.addWidget(btn); self._nav_btns.append(btn)

        sl.addStretch()

        # Botón desinstalar
        self._btn_des = QPushButton(t("btn_desinstalar"))
        self._btn_des.setObjectName("danger")
        self._btn_des.setCursor(Qt.PointingHandCursor)
        self._btn_des.clicked.connect(self._desinstalar)
        sl.addWidget(self._btn_des)

        ml.addWidget(sidebar)

        # Área de contenido
        content = QWidget(); content.setObjectName("contentArea")
        cl = QVBoxLayout(content)
        cl.setContentsMargins(_s(24,self._f), _s(20,self._f), _s(24,self._f), _s(20,self._f))
        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setFrameShape(QFrame.NoFrame)
        self.stacked = QStackedWidget(); scroll.setWidget(self.stacked)
        cl.addWidget(scroll); ml.addWidget(content, stretch=1)

        # Páginas
        self._pags = [
            self._pag_inicio(), self._pag_terminos(), self._pag_telegram(),
            self._pag_preferencias(), self._pag_completado(),
        ]
        for p in self._pags:
            self.stacked.addWidget(p)

        self.cambiar_pantalla(0)

    # ── Navegación ────────────────────────────────────────────────────────────

    def cambiar_pantalla(self, idx: int):
        if idx >= 2 and not self.terminos_aceptados:
            QMessageBox.warning(self, t("aceptacion_requerida"), t("aceptacion_requerida_msg")); return
        if idx >= 4 and not self.chat_id_validado:
            QMessageBox.warning(self, t("config_pendiente"), t("config_pendiente_msg")); return
        self.stacked.setCurrentIndex(idx)
        for i, btn in enumerate(self._nav_btns):
            btn.setChecked(i == idx)

    # ── Actualizar textos (al cambiar idioma) ─────────────────────────────────

    def _actualizar_textos(self):
        self.setWindowTitle(t("app_title"))
        for btn in self._nav_btns:
            clave = btn.property("i18n_key")
            if clave: btn.setText(t(clave))
        self._btn_des.setText(t("btn_desinstalar"))

    # ── Página 0: Inicio ──────────────────────────────────────────────────────

    def _pag_inicio(self):
        w = QWidget(); lay = QVBoxLayout(w)
        lay.setSpacing(_s(14, self._f)); lay.setContentsMargins(0,0,0,0)

        # Logo grande en la página de inicio
        logo_pix = cargar_imagen("logo.png", (_s(140,self._f), _s(80,self._f)))
        if logo_pix:
            lbl = QLabel(); lbl.setPixmap(logo_pix); lbl.setAlignment(Qt.AlignCenter)
            lay.addWidget(lbl)
        else:
            pix = cargar_imagen("monitoreo-postura.jpg", (_s(90,self._f),)*2)
            if pix:
                lbl = QLabel(); lbl.setPixmap(pix); lbl.setAlignment(Qt.AlignCenter)
                lay.addWidget(lbl)

        self._lbl_subtitulo = QLabel(t("app_subtitle"))
        self._lbl_subtitulo.setAlignment(Qt.AlignCenter)
        self._lbl_subtitulo.setStyleSheet(
            f"font-size:{max(9,int(16*self._f))}px;color:#6c6c70;")
        lay.addWidget(self._lbl_subtitulo)

        self._lbl_desc = QLabel(t("app_desc"))
        self._lbl_desc.setAlignment(Qt.AlignCenter); self._lbl_desc.setWordWrap(True)
        self._lbl_desc.setStyleSheet(
            f"color:#6c6c70;font-size:{max(9,int(12*self._f))}px;"
            "background:rgba(0,0,0,0.05);border-radius:10px;padding:12px;"
        )
        lay.addWidget(self._lbl_desc)

        row = QHBoxLayout(); row.setSpacing(_s(36, self._f))
        self._feats = []
        for img, clave in [("IA.jpg","feat_ia"),("telegram.png","feat_telegram"),("supabase.jpg","feat_nube")]:
            col = QVBoxLayout()
            p = cargar_imagen(img, (_s(36,self._f),)*2)
            ic = QLabel(); ic.setAlignment(Qt.AlignCenter)
            if p: ic.setPixmap(p)
            else: ic.setText("●"); ic.setStyleSheet(f"font-size:{_s(30,self._f)}px;color:#007aff;")
            col.addWidget(ic)
            lt = QLabel(t(clave)); lt.setAlignment(Qt.AlignCenter)
            lt.setStyleSheet(f"color:#6c6c70;font-size:{max(9,int(11*self._f))}px;font-weight:500;")
            lt.setProperty("i18n_key", clave)
            col.addWidget(lt)
            fr = QWidget(); fr.setLayout(col); row.addWidget(fr)
            self._feats.append(lt)
        lay.addLayout(row)

        lay.addStretch()
        self._btn_comenzar = QPushButton(t("btn_comenzar"))
        self._btn_comenzar.setFixedWidth(_s(240, self._f))
        self._btn_comenzar.clicked.connect(lambda: self.cambiar_pantalla(1))
        lay.addWidget(self._btn_comenzar, alignment=Qt.AlignCenter)
        lay.addStretch()
        return w

    # ── Página 1: Términos ────────────────────────────────────────────────────

    def _pag_terminos(self):
        w = QWidget(); lay = QVBoxLayout(w); lay.setSpacing(_s(12,self._f))

        self._lbl_term_tit = QLabel(t("terminos_titulo"))
        self._lbl_term_tit.setStyleSheet(f"font-size:{max(9,int(22*self._f))}px;font-weight:bold;")
        lay.addWidget(self._lbl_term_tit)

        self._term_text = QTextEdit(); self._term_text.setReadOnly(True)
        self._term_text.setPlainText(t("terminos_texto"))
        lay.addWidget(self._term_text)

        self._chk_terminos = QCheckBox(t("terminos_check"))
        lay.addWidget(self._chk_terminos)

        row = QHBoxLayout()
        self._btn_term_back = QPushButton(t("btn_atras")); self._btn_term_back.setObjectName("secondary")
        self._btn_term_back.clicked.connect(lambda: self.cambiar_pantalla(0))
        self._btn_term_next = QPushButton(t("btn_aceptar")); self._btn_term_next.setEnabled(False)
        self._btn_term_next.clicked.connect(self._aceptar_terminos)
        self._chk_terminos.stateChanged.connect(
            lambda: self._btn_term_next.setEnabled(self._chk_terminos.isChecked()))
        row.addWidget(self._btn_term_back); row.addStretch(); row.addWidget(self._btn_term_next)
        lay.addLayout(row)
        return w

    def _aceptar_terminos(self):
        if self._chk_terminos.isChecked():
            self.terminos_aceptados = True
            self.cambiar_pantalla(2)

    # ── Página 2: Telegram ────────────────────────────────────────────────────

    def _pag_telegram(self):
        w = QWidget(); lay = QVBoxLayout(w); lay.setSpacing(_s(12,self._f))

        self._lbl_tg_tit = QLabel(t("telegram_titulo"))
        self._lbl_tg_tit.setStyleSheet(f"font-size:{max(9,int(22*self._f))}px;font-weight:bold;")
        lay.addWidget(self._lbl_tg_tit)

        card = QGroupBox(); cr = QHBoxLayout()
        self._lbl_bot_label = QLabel(t("telegram_bot_label"))
        cr.addWidget(self._lbl_bot_label)
        lbl_bot = QLabel(_BOT_USERNAME); lbl_bot.setStyleSheet("font-weight:bold;color:#007aff;")
        cr.addWidget(lbl_bot)
        self._btn_cpy = QPushButton(t("btn_copiar")); self._btn_cpy.setFixedWidth(70)
        self._btn_cpy.clicked.connect(self._copiar_bot)
        cr.addWidget(self._btn_cpy); cr.addStretch(); card.setLayout(cr); lay.addWidget(card)

        self._lbl_tg_info = QLabel(t("telegram_info", bot=_BOT_USERNAME))
        self._lbl_tg_info.setTextFormat(Qt.RichText)
        self._lbl_tg_info.setStyleSheet(f"color:#6c6c70;font-size:{max(9,int(12*self._f))}px;")
        lay.addWidget(self._lbl_tg_info)

        g_auto = QGroupBox(); self._grp_auto_tit = g_auto
        al = QVBoxLayout()
        self._btn_det = QPushButton(t("btn_detectar"))
        self._btn_det.clicked.connect(self._detectar_chat_id)
        al.addWidget(self._btn_det)
        self._lbl_resultado = QLabel(""); self._lbl_resultado.setAlignment(Qt.AlignCenter)
        al.addWidget(self._lbl_resultado); g_auto.setLayout(al); lay.addWidget(g_auto)

        g_man = QGroupBox(); self._grp_man_tit = g_man
        ml2 = QVBoxLayout()
        self.input_chat = QLineEdit(); self.input_chat.setPlaceholderText(t("telegram_placeholder"))
        ml2.addWidget(self.input_chat)
        self._btn_prueba = QPushButton(t("btn_prueba"))
        self._btn_prueba.clicked.connect(self._enviar_prueba)
        ml2.addWidget(self._btn_prueba)
        self._lbl_prueba = QLabel(""); self._lbl_prueba.setAlignment(Qt.AlignCenter)
        ml2.addWidget(self._lbl_prueba); g_man.setLayout(ml2); lay.addWidget(g_man)

        lay.addStretch()
        row = QHBoxLayout()
        self._btn_tg_back = QPushButton(t("btn_atras")); self._btn_tg_back.setObjectName("secondary")
        self._btn_tg_back.clicked.connect(lambda: self.cambiar_pantalla(1))
        self._btn_tg_next = QPushButton(t("btn_guardar"))
        self._btn_tg_next.clicked.connect(self._guardar_y_avanzar)
        row.addWidget(self._btn_tg_back); row.addStretch(); row.addWidget(self._btn_tg_next)
        lay.addLayout(row)
        return w

    def _copiar_bot(self):
        QApplication.clipboard().setText(_BOT_USERNAME)
        QMessageBox.information(self, t("telegram_copiado"),
                                t("telegram_msg_copiado", bot=_BOT_USERNAME))

    def _detectar_chat_id(self):
        self._lbl_resultado.setText(t("telegram_consultando"))
        self._lbl_resultado.setStyleSheet("color:orange;")
        self._det_hilo = DetectorChatID()
        self._det_hilo.resultado.connect(self._on_detectar)
        self._det_hilo.start()

    def _on_detectar(self, texto, color):
        self._lbl_resultado.setText(texto); self._lbl_resultado.setStyleSheet(f"color:{color};")
        m = re.search(r"\d{5,}", texto)
        if m: self.input_chat.setText(m.group())

    def _enviar_prueba(self):
        cid = self.input_chat.text().strip()
        if not cid:
            self._lbl_prueba.setText(t("telegram_sin_id"))
            self._lbl_prueba.setStyleSheet("color:orange;"); return
        self._lbl_prueba.setText(t("telegram_enviando"))
        self._lbl_prueba.setStyleSheet("color:blue;")
        self._env_hilo = EnviadorPrueba(cid)
        self._env_hilo.resultado.connect(self._on_prueba)
        self._env_hilo.start()

    def _on_prueba(self, texto, color):
        self._lbl_prueba.setText(texto); self._lbl_prueba.setStyleSheet(f"color:{color};")

    def _guardar_y_avanzar(self):
        cid = self.input_chat.text().strip()
        if not cid:
            QMessageBox.warning(self, t("telegram_requerido"), t("telegram_requerido_desc")); return
        self.chat_id = cid
        from config.settings import CONFIG_DIR
        env = CONFIG_DIR / "config.env"
        lineas = [l for l in (env.read_text("utf-8").splitlines() if env.exists() else [])
                  if not l.startswith("TELEGRAM_CHAT_ID=")]
        lineas.append(f"TELEGRAM_CHAT_ID={cid}")
        env.write_text("\n".join(lineas) + "\n", "utf-8")
        os.environ["TELEGRAM_CHAT_ID"] = cid
        self.chat_id_validado = True
        self.cambiar_pantalla(3)

    # ── Página 3: Preferencias ────────────────────────────────────────────────

    def _pag_preferencias(self):
        w = QWidget(); lay = QVBoxLayout(w); lay.setSpacing(_s(14,self._f))

        self._lbl_pref_tit = QLabel(t("pref_titulo"))
        self._lbl_pref_tit.setStyleSheet(f"font-size:{max(9,int(22*self._f))}px;font-weight:bold;")
        lay.addWidget(self._lbl_pref_tit)

        # Autoarranque
        g_auto = QGroupBox()
        self._grp_auto_pref = g_auto
        al = QVBoxLayout()
        self._lbl_auto_desc = QLabel(t("pref_auto_desc"))
        self._lbl_auto_desc.setStyleSheet(f"color:#6c6c70;font-size:{max(9,int(11*self._f))}px;")
        self._lbl_auto_desc.setWordWrap(True)
        al.addWidget(self._lbl_auto_desc)
        self._chk_auto = QCheckBox(t("pref_auto_check"))
        self._chk_auto.setChecked(autoarranque_activo())
        al.addWidget(self._chk_auto); g_auto.setLayout(al); lay.addWidget(g_auto)

        # Idioma
        g_lang = QGroupBox()
        self._grp_lang = g_lang
        ll = QVBoxLayout()
        self._bg_lang = QButtonGroup(self)
        self._rb_es = QRadioButton("Español")
        self._rb_en = QRadioButton("English")
        self._bg_lang.addButton(self._rb_es, 0)
        self._bg_lang.addButton(self._rb_en, 1)
        if I18n.idioma() == "en":
            self._rb_en.setChecked(True)
        else:
            self._rb_es.setChecked(True)

        row_lang = QHBoxLayout()
        row_lang.addWidget(self._rb_es); row_lang.addWidget(self._rb_en); row_lang.addStretch()
        ll.addLayout(row_lang)

        # Cambio en tiempo real
        self._rb_es.toggled.connect(lambda checked: self._cambiar_idioma("es") if checked else None)
        self._rb_en.toggled.connect(lambda checked: self._cambiar_idioma("en") if checked else None)
        g_lang.setLayout(ll); lay.addWidget(g_lang)

        # Info
        self._lbl_pref_info = QLabel(t("pref_info"))
        self._lbl_pref_info.setStyleSheet(
            f"color:#6c6c70;font-size:{max(9,int(11*self._f))}px;"
            "background:rgba(0,122,255,0.08);border-radius:8px;padding:10px;")
        self._lbl_pref_info.setWordWrap(True)
        lay.addWidget(self._lbl_pref_info)

        lay.addStretch()
        row = QHBoxLayout()
        self._btn_pref_back = QPushButton(t("btn_atras")); self._btn_pref_back.setObjectName("secondary")
        self._btn_pref_back.clicked.connect(lambda: self.cambiar_pantalla(2))
        self._btn_pref_next = QPushButton(t("btn_finalizar")); self._btn_pref_next.setObjectName("success")
        self._btn_pref_next.clicked.connect(self._guardar_preferencias)
        row.addWidget(self._btn_pref_back); row.addStretch(); row.addWidget(self._btn_pref_next)
        lay.addLayout(row)
        return w

    def _cambiar_idioma(self, lang: str):
        I18n.guardar(lang)
        self._actualizar_textos()
        self._refrescar_paginas()

    def _refrescar_paginas(self):
        """Actualiza los textos de todas las páginas al cambiar idioma."""
        # Página inicio
        self._lbl_subtitulo.setText(t("app_subtitle"))
        self._lbl_desc.setText(t("app_desc"))
        self._btn_comenzar.setText(t("btn_comenzar"))
        for lbl in self._feats:
            lbl.setText(t(lbl.property("i18n_key")))
        # Términos
        self._lbl_term_tit.setText(t("terminos_titulo"))
        self._term_text.setPlainText(t("terminos_texto"))
        self._chk_terminos.setText(t("terminos_check"))
        self._btn_term_back.setText(t("btn_atras"))
        self._btn_term_next.setText(t("btn_aceptar"))
        # Telegram
        self._lbl_tg_tit.setText(t("telegram_titulo"))
        self._lbl_bot_label.setText(t("telegram_bot_label"))
        self._btn_cpy.setText(t("btn_copiar"))
        self._lbl_tg_info.setText(t("telegram_info", bot=_BOT_USERNAME))
        self._grp_auto_tit.setTitle(t("telegram_auto"))
        self._grp_man_tit.setTitle(t("telegram_manual"))
        self._btn_det.setText(t("btn_detectar"))
        self.input_chat.setPlaceholderText(t("telegram_placeholder"))
        self._btn_prueba.setText(t("btn_prueba"))
        self._btn_tg_back.setText(t("btn_atras"))
        self._btn_tg_next.setText(t("btn_guardar"))
        # Preferencias
        self._lbl_pref_tit.setText(t("pref_titulo"))
        self._grp_auto_pref.setTitle(t("pref_autoarranque"))
        self._lbl_auto_desc.setText(t("pref_auto_desc"))
        self._chk_auto.setText(t("pref_auto_check"))
        self._grp_lang.setTitle(t("pref_idioma"))
        self._lbl_pref_info.setText(t("pref_info"))
        self._btn_pref_back.setText(t("btn_atras"))
        self._btn_pref_next.setText(t("btn_finalizar"))
        # Completado
        self._lbl_done_tit.setText(t("done_titulo"))
        self._lbl_done_msg.setText(
            t("done_telegram") + "\n" + t("done_config") + "\n" +
            (t("done_auto_si") if autoarranque_activo() else t("done_auto_no"))
        )
        self._btn_iniciar.setText(t("btn_iniciar"))

    def _guardar_preferencias(self):
        if self._chk_auto.isChecked():
            activar_autoarranque()
        else:
            desactivar_autoarranque()
        self.cambiar_pantalla(4)

    # ── Página 4: Completado ──────────────────────────────────────────────────

    def _pag_completado(self):
        w = QWidget(); lay = QVBoxLayout(w); lay.setSpacing(_s(14,self._f))

        self._lbl_done_tit = QLabel(t("done_titulo"))
        self._lbl_done_tit.setAlignment(Qt.AlignCenter)
        self._lbl_done_tit.setStyleSheet(f"font-size:{max(9,int(28*self._f))}px;font-weight:bold;")
        lay.addWidget(self._lbl_done_tit)

        self._lbl_done_msg = QLabel(
            t("done_telegram") + "\n" + t("done_config") + "\n" +
            (t("done_auto_si") if autoarranque_activo() else t("done_auto_no"))
        )
        self._lbl_done_msg.setAlignment(Qt.AlignCenter)
        self._lbl_done_msg.setStyleSheet(f"color:#6c6c70;font-size:{max(9,int(13*self._f))}px;")
        lay.addWidget(self._lbl_done_msg)

        lay.addStretch()
        self._btn_iniciar = QPushButton(t("btn_iniciar"))
        self._btn_iniciar.setObjectName("success")
        self._btn_iniciar.setFixedWidth(_s(200,self._f))
        self._btn_iniciar.clicked.connect(self._finalizar)
        lay.addWidget(self._btn_iniciar, alignment=Qt.AlignCenter)
        lay.addStretch()
        return w

    def _finalizar(self):
        OnboardingEstado().marcar_completado(); self.close()

    # ── Desinstalar ───────────────────────────────────────────────────────────

    def _desinstalar(self):
        resp = QMessageBox.question(self, t("des_titulo"), t("des_mensaje"),
                                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if resp != QMessageBox.Yes: return
        exito = False
        try:
            desactivar_autoarranque()
            if sys.platform == "win32":
                import winreg
                k = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                    r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\Monitor de Postura_is1",
                    0, winreg.KEY_READ)
                uninstall, _ = winreg.QueryValueEx(k, "UninstallString"); winreg.CloseKey(k)
                subprocess.Popen([uninstall, "/SILENT"]); exito = True
            else:
                r = subprocess.run(["pkexec","dpkg","-r","postura-monitor"],
                                   capture_output=True, text=True)
                if r.returncode != 0:
                    r = subprocess.run(["sudo","dpkg","-r","postura-monitor"],
                                       capture_output=True, text=True)
                exito = r.returncode == 0
        except Exception as e:
            logger.error(f"Desinstalar: {e}")
        if exito:
            QMessageBox.information(self, t("des_exito"), t("des_exito_msg")); QApplication.quit()
        else:
            QMessageBox.warning(self, "Error", t("des_error_msg"))


# ── Funciones de entrada ──────────────────────────────────────────────────────

def mostrar_onboarding_si_necesario() -> bool:
    estado = OnboardingEstado()
    if estado.completado: return True
    try:
        app = QApplication.instance() or QApplication(sys.argv)
        w = OnboardingWizard(); w.show(); app.exec()
        return OnboardingEstado().completado
    except Exception as e:
        logger.error(f"Wizard: {e}"); return False


def mostrar_configuracion() -> None:
    try:
        app = QApplication.instance() or QApplication(sys.argv)
        w = OnboardingWizard(); w.cambiar_pantalla(3); w.show(); app.exec()
    except Exception as e:
        logger.error(f"Configuración: {e}")
