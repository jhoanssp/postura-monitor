"""
Widget de calibración frontal simplificado — v4.6.0
Solo requiere hombros y nariz. Muestra esqueleto y barra de progreso.
"""

import cv2
import numpy as np
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QProgressBar,
)
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QImage, QPixmap

from core.calibrador import Calibrador
from core.deteccion_postura import DetectorPostura
from utils.logger import crear_logger

logger = crear_logger("calibracion_widget")


class CalibracionWidget(QWidget):
    calibracion_completada = Signal()
    calibracion_cancelada  = Signal()

    DURACION_SEG = 3   # solo 3 segundos, más rápido

    def __init__(self, indice_camara: int = 0, parent=None):
        super().__init__(parent)
        self._idx = indice_camara
        self._cap = None
        self._detector = DetectorPostura(confianza_deteccion=0.5, confianza_seguimiento=0.5, umbral_visibilidad=0.3)
        self._calibrador = Calibrador()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._activo = False
        self._calibrando = False
        self._build_ui()

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setSpacing(12)

        tit = QLabel("Calibración frontal")
        tit.setAlignment(Qt.AlignCenter)
        tit.setStyleSheet("font-size:18px;font-weight:bold;")
        lay.addWidget(tit)

        instr = QLabel(
            "Siéntate recto, mira al frente.\n"
            "Asegúrate de que se vean tus hombros y nariz.\n\n"
            "Presiona 'Iniciar' y mantén la postura 3 segundos."
        )
        instr.setWordWrap(True)
        instr.setAlignment(Qt.AlignCenter)
        instr.setStyleSheet("color:#6c6c70;font-size:12px;padding:8px;")
        lay.addWidget(instr)

        self._lbl_cam = QLabel("Cámara no disponible")
        self._lbl_cam.setAlignment(Qt.AlignCenter)
        self._lbl_cam.setMinimumSize(320, 240)
        self._lbl_cam.setStyleSheet("background:#000;border-radius:8px;")
        lay.addWidget(self._lbl_cam)

        self._prog = QProgressBar()
        self._prog.setRange(0, 100)
        self._prog.setValue(0)
        self._prog.setStyleSheet(
            "QProgressBar{border-radius:4px;background:#2c2c2e;height:16px;}"
            "QProgressBar::chunk{background:#34c759;border-radius:4px;}"
        )
        lay.addWidget(self._prog)

        self._lbl_estado = QLabel("")
        self._lbl_estado.setAlignment(Qt.AlignCenter)
        self._lbl_estado.setStyleSheet("font-size:12px;")
        lay.addWidget(self._lbl_estado)

        row = QHBoxLayout()
        self._btn_saltar = QPushButton("Saltar (usar estándar)")
        self._btn_saltar.setObjectName("secondary")
        self._btn_saltar.clicked.connect(self._saltar)
        self._btn_inicio = QPushButton("Iniciar calibración")
        self._btn_inicio.setObjectName("success")
        self._btn_inicio.clicked.connect(self._iniciar)
        row.addWidget(self._btn_saltar)
        row.addStretch()
        row.addWidget(self._btn_inicio)
        lay.addLayout(row)

    def activar(self):
        if self._activo:
            return
        try:
            self._cap = cv2.VideoCapture(self._idx)
            if self._cap.isOpened():
                self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
                self._timer.start(33)
                self._activo = True
                logger.info(f"Cámara {self._idx} activada para calibración.")
                self._lbl_cam.setText("Cámara lista")
            else:
                self._lbl_cam.setText(f"No se pudo abrir cámara {self._idx}")
        except Exception as e:
            logger.error(f"Error cámara: {e}")
            self._lbl_cam.setText("Error de cámara")

    def desactivar(self):
        self._timer.stop()
        self._activo = False
        self._calibrando = False
        if self._cap:
            self._cap.release()
            self._cap = None
        logger.info("Calibración desactivada.")

    def _iniciar(self):
        if not self._activo or self._cap is None:
            self._lbl_estado.setText("Cámara no disponible")
            return
        self._btn_inicio.setEnabled(False)
        self._btn_saltar.setEnabled(False)
        self._calibrador.iniciar()
        self._calibrando = True
        self._lbl_estado.setText("Capturando... mantén postura")
        self._lbl_estado.setStyleSheet("color:#34c759;")
        self._prog.setValue(0)

    def _saltar(self):
        self.desactivar()
        self.calibracion_cancelada.emit()

    def _tick(self):
        if not self._activo or self._cap is None:
            return
        ok, frame = self._cap.read()
        if not ok or frame is None:
            return

        # Espejo para naturalidad
        frame = cv2.flip(frame, 1)

        # Detectar pose
        resultado = self._detector.detectar(frame)
        if resultado.pose_detectada:
            self._detector.dibujar_esqueleto(frame, resultado.landmarks_raw)

        # Calibración activa
        if self._calibrando:
            if resultado.landmarks:
                progreso = self._calibrador.agregar_frame(resultado.landmarks, vista="frontal")
                pct = int(progreso * 100)
                self._prog.setValue(pct)
                if progreso >= 1.0:
                    self._finalizar_calibracion()
                    return
                # Mostrar tiempo restante
                segs = max(0, self.DURACION_SEG - int(progreso * self.DURACION_SEG))
                self._lbl_estado.setText(f"Capturando... {segs}s restantes")
            else:
                self._lbl_estado.setText("⚠️ No se ven hombros y nariz. Ajústate.")
                self._lbl_estado.setStyleSheet("color:orange;")
                cv2.putText(frame, "Cuerpo no detectado", (20, 40),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0,0,255), 2)

        # Mostrar frame en UI
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb.shape
        img = QImage(rgb.data, w, h, ch * w, QImage.Format_RGB888)
        self._lbl_cam.setPixmap(
            QPixmap.fromImage(img).scaled(
                self._lbl_cam.width(), self._lbl_cam.height(),
                Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
        )

    def _finalizar_calibracion(self):
        perfil = self._calibrador.finalizar("frontal")
        self._calibrando = False
        self._timer.stop()

        if perfil:
            self._prog.setValue(100)
            self._lbl_estado.setText("✅ Calibración exitosa")
            self._lbl_estado.setStyleSheet("color:#34c759;font-weight:bold;")
            # Cerrar tras 1.5 segundos
            from PySide6.QtCore import QTimer as QT
            QT.singleShot(1500, lambda: (self.desactivar(), self.calibracion_completada.emit()))
        else:
            self._lbl_estado.setText("❌ Error. Intenta de nuevo.")
            self._lbl_estado.setStyleSheet("color:red;")
            self._btn_inicio.setEnabled(True)
            self._btn_saltar.setEnabled(True)
            self._calibrando = False
            self._timer.start(33)  # seguir mostrando cámara
