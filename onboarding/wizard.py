"""
Asistente de configuración inicial — v4.5.1
Opción C de calibración: pantalla opcional en onboarding + [C] en debug.
"""

import sys, os, re, subprocess, requests
from pathlib import Path

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QCheckBox, QTextEdit, QLineEdit, QGroupBox,
    QMessageBox, QStackedWidget, QFrame, QScrollArea,
)
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QPalette, QPixmap, QScreen

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from utils.logger import crear_logger
from onboarding.estado import OnboardingEstado
from config.credentials import get_telegram_bot_token, get_bot_username

logger = crear_logger("onboarding_wizard")

_BOT_TOKEN    = get_telegram_bot_token()
_BOT_USERNAME = get_bot_username()
IMG_DIR = Path(__file__).parent / "img"


def _pix(nombre, w, h):
    ruta = IMG_DIR / nombre
    if ruta.exists():
        p = QPixmap(str(ruta))
        if not p.isNull():
            return p.scaled(w, h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    return None

def _s(base, f): return max(int(base * f), int(base * 0.6))


# ── Autoarranque ──────────────────────────────────────────────────────────────

def _exe():
    return sys.executable if getattr(sys, "frozen", False) \
           else str(Path(__file__).resolve().parent.parent / "main.py")

def activar_autoarranque():
    try:
        if sys.platform == "win32":
            import winreg
            k = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_SET_VALUE)
            winreg.SetValueEx(k, "PosturaMonitor", 0, winreg.REG_SZ,
                f'"{_exe()}" --modo produccion --skip-onboarding')
            winreg.CloseKey(k)
        else:
            d = Path.home() / ".config" / "autostart"
            d.mkdir(parents=True, exist_ok=True)
            exe = "/opt/postura-monitor/postura-monitor" \
                  if Path("/opt/postura-monitor/postura-monitor").exists() else _exe()
            (d / "postura-monitor.desktop").write_text(
                "[Desktop Entry]\nType=Application\nName=Monitor de Postura\n"
                f"Exec={exe} --modo produccion --skip-onboarding\n"
                "Hidden=false\nNoDisplay=false\nX-GNOME-Autostart-enabled=true\n")
        return True
    except Exception as e:
        logger.error(f"Autoarranque: {e}"); return False

def desactivar_autoarranque():
    try:
        if sys.platform == "win32":
            import winreg
            k = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_SET_VALUE)
            try: winreg.DeleteValue(k, "PosturaMonitor")
            except FileNotFoundError: pass
            winreg.CloseKey(k)
        else:
            p = Path.home() / ".config" / "autostart" / "postura-monitor.desktop"
            if p.exists(): p.unlink()
        return True
    except Exception as e:
        logger.error(f"Desactivar: {e}"); return False

def autoarranque_activo():
    try:
        if sys.platform == "win32":
            import winreg
            k = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_READ)
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
            d = r.json()
            if d.get("ok") and d.get("result"):
                cid = d["result"][-1]["message"]["chat"]["id"]
                self.resultado.emit(f"Chat ID detectado: {cid}", "#34c759")
            else:
                self.resultado.emit("Envía un mensaje al bot primero.", "orange")
        except Exception as e:
            self.resultado.emit(f"Error: {str(e)[:60]}", "red")

class EnviadorPrueba(QThread):
    resultado = Signal(str, str)
    def __init__(self, cid): super().__init__(); self.cid = cid
    def run(self):
        try:
            r = requests.post(f"https://api.telegram.org/bot{_BOT_TOKEN}/sendMessage",
                json={"chat_id": self.cid, "text": "✅ Monitor de Postura configurado."}, timeout=10)
            if r.json().get("ok"):
                self.resultado.emit("✓ Mensaje enviado. Revisa Telegram.", "#34c759")
            else:
                self.resultado.emit("Error al enviar.", "red")
        except Exception as e:
            self.resultado.emit(f"Error: {str(e)[:60]}", "red")


# ── Ventana ───────────────────────────────────────────────────────────────────

class OnboardingWizard(QMainWindow):
    # Páginas: 0=Inicio 1=Términos 2=Telegram 3=Preferencias 4=Calibración 5=Listo

    def __init__(self):
        super().__init__()
        sg = QApplication.primaryScreen().availableGeometry()
        w  = min(960, int(sg.width()  * 0.85))
        h  = min(700, int(sg.height() * 0.90))
        self.resize(w, h); self.setMinimumSize(500, 380)
        self.move(sg.x()+(sg.width()-w)//2, sg.y()+(sg.height()-h)//2)
        self._f = min(w/960, h/700)

        self.terminos_aceptados = False
        self.chat_id_validado   = False
        self.chat_id            = ""

        self._dark = QApplication.palette().color(QPalette.Window).lightness() < 128
        self._estilos(); self._build_ui()

    def _estilos(self):
        d=self._dark; f=self._f
        bg="#1c1c1e" if d else "#f5f5f7"; card="#2c2c2e" if d else "#ffffff"
        txt="#f5f5f7" if d else "#1c1c1e"; brd="#38383a" if d else "#e5e5ea"
        pri="#0a84ff" if d else "#007aff"; prh="#409cff" if d else "#0051a8"
        sec="#8e8e93"; ok="#30d158" if d else "#34c759"
        hov="#3a3a3c" if d else "#e5e5ea"; red="#ff453a" if d else "#ff3b30"
        fs=lambda n: max(9,int(n*f))
        self.setStyleSheet(f"""
            QMainWindow{{background:{bg};}} QLabel{{color:{txt};background:transparent;}}
            QWidget#sidebar{{background:{card};border-right:1px solid {brd};}}
            QPushButton#nav{{background:transparent;color:{txt};border:none;
                border-radius:{_s(8,f)}px;text-align:left;
                padding:{_s(7,f)}px {_s(14,f)}px;font-size:{fs(13)}px;font-weight:500;}}
            QPushButton#nav:hover{{background:{hov};}} QPushButton#nav:checked{{background:{pri};color:white;}}
            QPushButton{{background:{pri};color:white;border:none;border-radius:{_s(8,f)}px;
                padding:{_s(7,f)}px {_s(18,f)}px;font-weight:500;font-size:{fs(12)}px;}}
            QPushButton:hover{{background:{prh};}}
            QPushButton#secondary{{background:{sec};}} QPushButton#secondary:hover{{background:#7a7a7e;}}
            QPushButton#success{{background:{ok};}} QPushButton#danger{{background:{red};}}
            QPushButton#danger:hover{{background:#cc2f26;}}
            QCheckBox{{spacing:6px;color:{txt};font-size:{fs(12)}px;}}
            QGroupBox{{font-weight:500;font-size:{fs(12)}px;border:1px solid {brd};
                border-radius:{_s(10,f)}px;margin-top:{_s(10,f)}px;background:{card};color:{txt};}}
            QGroupBox::title{{subcontrol-origin:margin;left:{_s(10,f)}px;padding:0 6px;background:{bg};}}
            QLineEdit{{border:1px solid {brd};border-radius:{_s(7,f)}px;padding:{_s(6,f)}px;
                background:{card};color:{txt};font-size:{fs(12)}px;}}
            QLineEdit:focus{{border-color:{pri};}}
            QTextEdit{{border:1px solid {brd};border-radius:{_s(7,f)}px;background:{card};
                color:{txt};padding:{_s(6,f)}px;font-size:{fs(11)}px;}}
            QScrollArea{{border:none;background:transparent;}} QWidget#content{{background:{bg};}}
        """)

    def _build_ui(self):
        central=QWidget(); self.setCentralWidget(central)
        ml=QHBoxLayout(central); ml.setContentsMargins(0,0,0,0); ml.setSpacing(0)

        sidebar=QWidget(); sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(_s(210,self._f))
        sl=QVBoxLayout(sidebar)
        sl.setContentsMargins(_s(16,self._f),_s(20,self._f),_s(16,self._f),_s(20,self._f))
        sl.setSpacing(5)

        logo_pix=_pix("logo.png",_s(170,self._f),_s(65,self._f))
        if logo_pix:
            lbl=QLabel(); lbl.setPixmap(logo_pix); lbl.setAlignment(Qt.AlignCenter)
            lbl.setContentsMargins(0,0,0,_s(12,self._f)); sl.addWidget(lbl)
        else:
            lbl=QLabel("Monitor de\nPostura")
            lbl.setStyleSheet(f"font-size:{max(9,int(15*self._f))}px;font-weight:bold;margin-bottom:{_s(12,self._f)}px;")
            sl.addWidget(lbl)

        self._nav=[]
        for txt,idx in [("Inicio",0),("Términos",1),("Telegram",2),
                         ("Preferencias",3),("Calibración",4),("Listo",5)]:
            b=QPushButton(txt); b.setObjectName("nav"); b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _,i=idx: self._ir(i))
            sl.addWidget(b); self._nav.append(b)

        sl.addStretch()
        btn_des=QPushButton("Desinstalar"); btn_des.setObjectName("danger")
        btn_des.setCursor(Qt.PointingHandCursor); btn_des.clicked.connect(self._desinstalar)
        sl.addWidget(btn_des)
        ml.addWidget(sidebar)

        content=QWidget(); content.setObjectName("content")
        cl=QVBoxLayout(content)
        cl.setContentsMargins(_s(24,self._f),_s(20,self._f),_s(24,self._f),_s(20,self._f))
        scroll=QScrollArea(); scroll.setWidgetResizable(True); scroll.setFrameShape(QFrame.NoFrame)
        self.stack=QStackedWidget(); scroll.setWidget(self.stack)
        cl.addWidget(scroll); ml.addWidget(content,stretch=1)

        for pg in [self._pg_inicio(), self._pg_terminos(), self._pg_telegram(),
                   self._pg_preferencias(), self._pg_calibracion(), self._pg_completado()]:
            self.stack.addWidget(pg)
        self._ir(0)

    def _ir(self, idx):
        if idx >= 2 and not self.terminos_aceptados:
            QMessageBox.warning(self,"Requerido","Acepta los términos primero."); return
        if idx >= 4 and not self.chat_id_validado:
            QMessageBox.warning(self,"Pendiente","Completa la configuración de Telegram."); return
        # Activar/desactivar widget de calibración
        if idx == 4:
            self._cal_widget.activar()
        else:
            if hasattr(self, '_cal_widget'):
                self._cal_widget.desactivar()
        self.stack.setCurrentIndex(idx)
        for i,b in enumerate(self._nav): b.setChecked(i==idx)

    # ── Página 0: Inicio ──────────────────────────────────────────────────────

    def _pg_inicio(self):
        w=QWidget(); lay=QVBoxLayout(w)
        lay.setSpacing(_s(14,self._f)); lay.setContentsMargins(0,0,0,0)
        img=_pix("monitoreo-postura.jpg",_s(160,self._f),_s(100,self._f))
        if img:
            lbl=QLabel(); lbl.setPixmap(img); lbl.setAlignment(Qt.AlignCenter); lay.addWidget(lbl)
        tit=QLabel("Monitor de Postura"); tit.setAlignment(Qt.AlignCenter)
        tit.setStyleSheet(f"font-size:{max(9,int(32*self._f))}px;font-weight:bold;margin-top:6px;")
        lay.addWidget(tit)
        sub=QLabel("Cuida tu espalda mientras estudias"); sub.setAlignment(Qt.AlignCenter)
        sub.setStyleSheet(f"font-size:{max(9,int(15*self._f))}px;color:#6c6c70;")
        lay.addWidget(sub)
        desc=QLabel("Analiza tu postura en tiempo real con IA.\nRecibe alertas por Telegram cuando detecta una mala posición sostenida.")
        desc.setAlignment(Qt.AlignCenter); desc.setWordWrap(True)
        desc.setStyleSheet(f"color:#6c6c70;font-size:{max(9,int(12*self._f))}px;background:rgba(0,0,0,0.05);border-radius:10px;padding:12px;")
        lay.addWidget(desc)
        row=QHBoxLayout(); row.setSpacing(_s(36,self._f))
        for img_n,texto in [("IA.jpg","Detección IA"),("telegram.png","Alertas Telegram"),("supabase.jpg","Datos nube")]:
            col=QVBoxLayout(); p=_pix(img_n,_s(38,self._f),_s(38,self._f))
            ic=QLabel(); ic.setAlignment(Qt.AlignCenter)
            if p: ic.setPixmap(p)
            else: ic.setText("●"); ic.setStyleSheet(f"font-size:{_s(30,self._f)}px;color:#007aff;")
            col.addWidget(ic)
            lt=QLabel(texto); lt.setAlignment(Qt.AlignCenter)
            lt.setStyleSheet(f"color:#6c6c70;font-size:{max(9,int(11*self._f))}px;font-weight:500;")
            col.addWidget(lt); fr=QWidget(); fr.setLayout(col); row.addWidget(fr)
        lay.addLayout(row); lay.addStretch()
        btn=QPushButton("Comenzar configuración"); btn.setFixedWidth(_s(240,self._f))
        btn.clicked.connect(lambda: self._ir(1))
        lay.addWidget(btn,alignment=Qt.AlignCenter); lay.addStretch()
        return w

    # ── Página 1: Términos ────────────────────────────────────────────────────

    def _pg_terminos(self):
        w=QWidget(); lay=QVBoxLayout(w); lay.setSpacing(_s(12,self._f))
        tit=QLabel("Términos y Condiciones")
        tit.setStyleSheet(f"font-size:{max(9,int(22*self._f))}px;font-weight:bold;")
        lay.addWidget(tit)
        te=QTextEdit(); te.setReadOnly(True)
        te.setPlainText(
            "TÉRMINOS Y CONDICIONES DE USO\n\n"
            "1. ACEPTACIÓN\nAl utilizar este software aceptas estos términos.\n\n"
            "2. PRIVACIDAD\n- Datos de postura almacenados en Supabase.\n"
            "- Imágenes NO se guardan ni transmiten.\n"
            "- Datos para análisis académico anonimizado.\n\n"
            "3. CÁMARA\nAcceso a cámara requerido. Procesamiento local.\n\n"
            "4. NOTIFICACIONES\nAlertas enviadas a tu Telegram configurado.\n\n"
            "5. RESPONSABILIDAD\nHerramienta de asistencia, no reemplaza consejo médico.\n\n"
            "6. LEY APLICABLE\nRepública del Ecuador.")
        lay.addWidget(te)
        self._chk=QCheckBox("He leído y acepto los términos y condiciones")
        lay.addWidget(self._chk)
        row=QHBoxLayout()
        b_back=QPushButton("Atrás"); b_back.setObjectName("secondary"); b_back.clicked.connect(lambda: self._ir(0))
        b_next=QPushButton("Aceptar y continuar"); b_next.setEnabled(False)
        b_next.clicked.connect(self._aceptar)
        self._chk.stateChanged.connect(lambda: b_next.setEnabled(self._chk.isChecked()))
        row.addWidget(b_back); row.addStretch(); row.addWidget(b_next)
        lay.addLayout(row)
        return w

    def _aceptar(self):
        self.terminos_aceptados=True; self._ir(2)

    # ── Página 2: Telegram ────────────────────────────────────────────────────

    def _pg_telegram(self):
        w=QWidget(); lay=QVBoxLayout(w); lay.setSpacing(_s(12,self._f))
        tit=QLabel("Configuración de Telegram")
        tit.setStyleSheet(f"font-size:{max(9,int(22*self._f))}px;font-weight:bold;")
        lay.addWidget(tit)
        card=QGroupBox(); cr=QHBoxLayout()
        cr.addWidget(QLabel("Bot:"))
        lbl_b=QLabel(_BOT_USERNAME); lbl_b.setStyleSheet("font-weight:bold;color:#007aff;")
        cr.addWidget(lbl_b)
        btn_c=QPushButton("Copiar"); btn_c.setFixedWidth(70)
        btn_c.clicked.connect(lambda: (QApplication.clipboard().setText(_BOT_USERNAME),
            QMessageBox.information(self,"Copiado",f"'{_BOT_USERNAME}' copiado.")))
        cr.addWidget(btn_c); cr.addStretch(); card.setLayout(cr); lay.addWidget(card)
        info=QLabel(f"1. Busca <b>{_BOT_USERNAME}</b> en Telegram y envíale cualquier mensaje\n"
                    "2. Haz clic en <b>Detectar mi Chat ID</b>")
        info.setTextFormat(Qt.RichText)
        info.setStyleSheet(f"color:#6c6c70;font-size:{max(9,int(12*self._f))}px;")
        lay.addWidget(info)
        g1=QGroupBox("Detección automática"); al=QVBoxLayout()
        btn_det=QPushButton("Detectar mi Chat ID"); btn_det.clicked.connect(self._detectar)
        al.addWidget(btn_det)
        self._lbl_res=QLabel(""); self._lbl_res.setAlignment(Qt.AlignCenter)
        al.addWidget(self._lbl_res); g1.setLayout(al); lay.addWidget(g1)
        g2=QGroupBox("O ingrésalo manualmente"); ml2=QVBoxLayout()
        self._inp_chat=QLineEdit(); self._inp_chat.setPlaceholderText("Ej: 123456789")
        ml2.addWidget(self._inp_chat)
        btn_p=QPushButton("Enviar mensaje de prueba"); btn_p.clicked.connect(self._prueba)
        ml2.addWidget(btn_p)
        self._lbl_prueba=QLabel(""); self._lbl_prueba.setAlignment(Qt.AlignCenter)
        ml2.addWidget(self._lbl_prueba); g2.setLayout(ml2); lay.addWidget(g2)
        lay.addStretch()
        row=QHBoxLayout()
        b_back=QPushButton("Atrás"); b_back.setObjectName("secondary"); b_back.clicked.connect(lambda: self._ir(1))
        b_next=QPushButton("Guardar y continuar"); b_next.clicked.connect(self._guardar_tg)
        row.addWidget(b_back); row.addStretch(); row.addWidget(b_next)
        lay.addLayout(row)
        return w

    def _detectar(self):
        self._lbl_res.setText("Consultando..."); self._lbl_res.setStyleSheet("color:orange;")
        self._dh=DetectorChatID(); self._dh.resultado.connect(self._on_det); self._dh.start()

    def _on_det(self,txt,col):
        self._lbl_res.setText(txt); self._lbl_res.setStyleSheet(f"color:{col};")
        m=re.search(r"\d{5,}",txt)
        if m: self._inp_chat.setText(m.group())

    def _prueba(self):
        cid=self._inp_chat.text().strip()
        if not cid: self._lbl_prueba.setText("Ingresa tu Chat ID primero"); return
        self._lbl_prueba.setText("Enviando..."); self._lbl_prueba.setStyleSheet("color:blue;")
        self._ph=EnviadorPrueba(cid); self._ph.resultado.connect(self._on_prueba); self._ph.start()

    def _on_prueba(self,txt,col):
        self._lbl_prueba.setText(txt); self._lbl_prueba.setStyleSheet(f"color:{col};")

    def _guardar_tg(self):
        cid=self._inp_chat.text().strip()
        if not cid:
            QMessageBox.warning(self,"Requerido","Detecta o ingresa tu Chat ID."); return
        self.chat_id=cid
        from config.settings import CONFIG_DIR
        env=CONFIG_DIR/"config.env"
        lineas=[l for l in (env.read_text("utf-8").splitlines() if env.exists() else [])
                if not l.startswith("TELEGRAM_CHAT_ID=")]
        lineas.append(f"TELEGRAM_CHAT_ID={cid}")
        env.write_text("\n".join(lineas)+"\n","utf-8")
        os.environ["TELEGRAM_CHAT_ID"]=cid
        self.chat_id_validado=True; self._ir(3)

    # ── Página 3: Preferencias ────────────────────────────────────────────────

    def _pg_preferencias(self):
        w=QWidget(); lay=QVBoxLayout(w); lay.setSpacing(_s(14,self._f))
        tit=QLabel("Preferencias")
        tit.setStyleSheet(f"font-size:{max(9,int(22*self._f))}px;font-weight:bold;")
        lay.addWidget(tit)
        g=QGroupBox("Inicio automático"); al=QVBoxLayout()
        desc=QLabel("Si lo activas, el monitor iniciará automáticamente\ncada vez que enciendas tu computadora.")
        desc.setStyleSheet(f"color:#6c6c70;font-size:{max(9,int(11*self._f))}px;"); desc.setWordWrap(True)
        al.addWidget(desc)
        self._chk_auto=QCheckBox("Iniciar Monitor de Postura con el sistema")
        self._chk_auto.setChecked(autoarranque_activo())
        al.addWidget(self._chk_auto); g.setLayout(al); lay.addWidget(g)
        info=QLabel("💡 Puedes cambiar esto después con: postura-monitor --configurar")
        info.setStyleSheet(f"color:#6c6c70;font-size:{max(9,int(11*self._f))}px;"
                          "background:rgba(0,122,255,0.08);border-radius:8px;padding:10px;")
        info.setWordWrap(True); lay.addWidget(info)
        lay.addStretch()
        row=QHBoxLayout()
        b_back=QPushButton("Atrás"); b_back.setObjectName("secondary"); b_back.clicked.connect(lambda: self._ir(2))
        b_next=QPushButton("Siguiente"); b_next.clicked.connect(self._guardar_pref)
        row.addWidget(b_back); row.addStretch(); row.addWidget(b_next)
        lay.addLayout(row)
        return w

    def _guardar_pref(self):
        if self._chk_auto.isChecked(): activar_autoarranque()
        else: desactivar_autoarranque()
        self._ir(4)

    # ── Página 4: Calibración (OPCIONAL) ─────────────────────────────────────

    def _pg_calibracion(self):
        w=QWidget(); lay=QVBoxLayout(w); lay.setSpacing(_s(14,self._f))

        tit=QLabel("Calibración de postura base")
        tit.setStyleSheet(f"font-size:{max(9,int(22*self._f))}px;font-weight:bold;")
        lay.addWidget(tit)

        desc=QLabel(
            "Esta calibración personaliza los umbrales de detección a tu cuerpo y distancia a la cámara.\n\n"
            "Si la omites, se usarán valores estándar de la bibliografía científica.\n"
            "Puedes calibrar más adelante con: postura-monitor --calibrar"
        )
        desc.setWordWrap(True)
        desc.setStyleSheet(
            f"color:#6c6c70;font-size:{max(9,int(12*self._f))}px;"
            "background:rgba(0,122,255,0.08);border-radius:10px;padding:12px;"
        )
        lay.addWidget(desc)

        # Widget de calibración embebido
        try:
            from onboarding.calibracion_widget import CalibracionWidget
            self._cal_widget = CalibracionWidget(indice_camara=0)
            self._cal_widget.calibracion_completada.connect(lambda: self._ir(5))
            self._cal_widget.calibracion_cancelada.connect(lambda: self._ir(5))
            lay.addWidget(self._cal_widget)
        except Exception as e:
            logger.error(f"Error cargando widget calibración: {e}")
            # Fallback si no hay cámara disponible
            self._cal_widget = QWidget()
            lbl_err = QLabel("⚠️  Cámara no disponible para calibración.\nPuedes calibrar más tarde.")
            lbl_err.setAlignment(Qt.AlignCenter)
            lbl_err.setStyleSheet(f"color:#6c6c70;font-size:{max(9,int(12*self._f))}px;")
            layout_err = QVBoxLayout(self._cal_widget)
            layout_err.addWidget(lbl_err)
            lay.addWidget(self._cal_widget)
            row_fb = QHBoxLayout()
            b_skip_fb = QPushButton("Omitir y finalizar"); b_skip_fb.setObjectName("secondary")
            b_skip_fb.clicked.connect(lambda: self._ir(5))
            row_fb.addStretch(); row_fb.addWidget(b_skip_fb)
            lay.addLayout(row_fb)

        return w

    # ── Página 5: Completado ──────────────────────────────────────────────────

    def _pg_completado(self):
        w=QWidget(); lay=QVBoxLayout(w); lay.setSpacing(_s(14,self._f))

        from core.calibrador import Calibrador
        calibrado = Calibrador().tiene_perfil()

        tit=QLabel("¡Todo listo!")
        tit.setAlignment(Qt.AlignCenter)
        tit.setStyleSheet(f"font-size:{max(9,int(28*self._f))}px;font-weight:bold;")
        lay.addWidget(tit)

        cal_txt = "✓ Postura calibrada a tu perfil personal" if calibrado \
                  else "→ Usando umbrales estándar (calibra con --calibrar)"
        auto_txt = "✓ Se iniciará automáticamente con el sistema" \
                   if autoarranque_activo() else "→ Inicio manual: ejecuta 'postura-monitor'"

        msg=QLabel(f"✓ Telegram configurado correctamente\n✓ Configuración guardada\n{cal_txt}\n{auto_txt}")
        msg.setAlignment(Qt.AlignCenter)
        msg.setStyleSheet(f"color:#6c6c70;font-size:{max(9,int(13*self._f))}px;")
        lay.addWidget(msg)
        lay.addStretch()
        btn=QPushButton("Iniciar Monitor"); btn.setObjectName("success")
        btn.setFixedWidth(_s(200,self._f)); btn.clicked.connect(self._finalizar)
        lay.addWidget(btn,alignment=Qt.AlignCenter)
        lay.addStretch()
        return w

    def _finalizar(self):
        if hasattr(self,'_cal_widget'): self._cal_widget.desactivar()
        OnboardingEstado().marcar_completado(); self.close()

    # ── Desinstalar ───────────────────────────────────────────────────────────

    def _desinstalar(self):
        resp=QMessageBox.question(self,"Desinstalar",
            "¿Desinstalar Monitor de Postura?\nLa configuración de Telegram se conservará.",
            QMessageBox.Yes|QMessageBox.No,QMessageBox.No)
        if resp!=QMessageBox.Yes: return
        exito=False
        try:
            desactivar_autoarranque()
            if sys.platform=="win32":
                import winreg
                k=winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                    r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\Monitor de Postura_is1",
                    0,winreg.KEY_READ)
                u,_=winreg.QueryValueEx(k,"UninstallString"); winreg.CloseKey(k)
                subprocess.Popen([u,"/SILENT"]); exito=True
            else:
                r=subprocess.run(["pkexec","dpkg","-r","postura-monitor"],capture_output=True,text=True)
                if r.returncode!=0:
                    r=subprocess.run(["sudo","dpkg","-r","postura-monitor"],capture_output=True,text=True)
                exito=r.returncode==0
        except Exception as e:
            logger.error(f"Desinstalar: {e}")
        if exito:
            QMessageBox.information(self,"Desinstalado","Monitor de Postura desinstalado.")
            QApplication.quit()
        else:
            QMessageBox.warning(self,"Error",
                "No se pudo desinstalar automáticamente.\n\n"
                "Linux: sudo dpkg -r postura-monitor\n"
                "Windows: Panel de Control → Programas → Desinstalar")

    def closeEvent(self, event):
        if hasattr(self,'_cal_widget'): self._cal_widget.desactivar()
        super().closeEvent(event)


# ── Funciones de entrada ──────────────────────────────────────────────────────

def mostrar_onboarding_si_necesario() -> bool:
    estado=OnboardingEstado()
    if estado.completado: return True
    try:
        app=QApplication.instance() or QApplication(sys.argv)
        w=OnboardingWizard(); w.show(); app.exec()
        return OnboardingEstado().completado
    except Exception as e:
        logger.error(f"Wizard: {e}"); return False

def mostrar_configuracion() -> None:
    try:
        app=QApplication.instance() or QApplication(sys.argv)
        w=OnboardingWizard(); w._ir(3); w.show(); app.exec()
    except Exception as e:
        logger.error(f"Config: {e}")
