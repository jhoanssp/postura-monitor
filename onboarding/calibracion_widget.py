"""
Widget de calibración de postura base — v4.5.1 CORREGIDO
Se incrusta en el wizard. Muestra la cámara en vivo y guía al usuario
a mantener postura correcta durante 5 segundos.
"""

import cv2
import numpy as np
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QProgressBar, QFrame,
)
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QImage, QPixmap

from core.calibrador import Calibrador
from core.deteccion_postura import DetectorPostura
from utils.logger import crear_logger

logger = crear_logger("calibracion_widget")


class CalibracionWidget(QWidget):
    """
    Muestra la cámara en vivo, guía al usuario a sentarse correctamente
    y captura su perfil corporal durante 5 segundos.
    """

    calibracion_completada = Signal()   # emitida al finalizar
    calibracion_cancelada  = Signal()   # emitida al saltar

    DURACION_SEG = 5

    def __init__(self, indice_camara: int = 0, parent=None):
        super().__init__(parent)
        self._idx    = indice_camara
        self._cap    = None
        self._detector  = DetectorPostura()
        self._calibrador = Calibrador()
        self._timer  = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._frames = 0
        self._total  = self.DURACION_SEG * 30   # ~30fps
        self._activo = False
        self._calibrando = False
        self._build_ui()

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setSpacing(16)

        # Título
        tit = QLabel("Calibración de Postura")
        tit.setAlignment(Qt.AlignCenter)
        tit.setStyleSheet("font-size:20px;font-weight:bold;")
        lay.addWidget(tit)

        # Instrucciones
        self._lbl_instr = QLabel(
            "Siéntate en tu postura CORRECTA habitual.\n"
            "Espalda recta, pantalla a la altura de los ojos.\n\n"
            "Cuando estés listo, presiona 'Iniciar calibración'."
        )
        self._lbl_instr.setAlignment(Qt.AlignCenter)
        self._lbl_instr.setWordWrap(True)
        self._lbl_instr.setStyleSheet(
            "color:#6c6c70;font-size:13px;"
            "background:rgba(0,122,255,0.08);border-radius:10px;padding:12px;"
        )
        lay.addWidget(self._lbl_instr)

        # Vista de cámara
        self._lbl_cam = QLabel("Cámara no disponible")
        self._lbl_cam.setAlignment(Qt.AlignCenter)
        self._lbl_cam.setMinimumSize(320, 240)
        self._lbl_cam.setStyleSheet(
            "background:#000;border-radius:10px;color:#aaa;font-size:12px;"
        )
        lay.addWidget(self._lbl_cam)

        # Progreso
        self._prog = QProgressBar()
        self._prog.setRange(0, 100)
        self._prog.setValue(0)
        self._prog.setTextVisible(True)
        self._prog.setStyleSheet(
            "QProgressBar{border-radius:6px;background:#2c2c2e;height:20px;}"
            "QProgressBar::chunk{background:#34c759;border-radius:6px;}"
        )
        lay.addWidget(self._prog)

        self._lbl_estado = QLabel("")
        self._lbl_estado.setAlignment(Qt.AlignCenter)
        self._lbl_estado.setStyleSheet("font-size:13px;font-weight:500;")
        lay.addWidget(self._lbl_estado)

        # Botones
        row = QHBoxLayout()
        self._btn_saltar = QPushButton("Saltar (usar valores estándar)")
        self._btn_saltar.setObjectName("secondary")
        self._btn_saltar.clicked.connect(self._saltar)
        self._btn_inicio = QPushButton("Iniciar calibración")
        self._btn_inicio.setObjectName("success")
        self._btn_inicio.clicked.connect(self._iniciar)
        row.addWidget(self._btn_saltar)
        row.addStretch()
        row.addWidget(self._btn_inicio)
        lay.addLayout(row)

    # ── Control ───────────────────────────────────────────────────────────────

    def activar(self):
        """Inicia la cámara para previsualización."""
        try:
            self._cap = cv2.VideoCapture(self._idx)
            if self._cap.isOpened():
                self._timer.start(33)   # ~30fps
                self._activo = True
                logger.info("Cámara activada para calibración.")
            else:
                self._lbl_cam.setText("No se pudo abrir la cámara")
        except Exception as e:
            logger.error(f"Cámara: {e}")
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
        self._frames = 0
        self._lbl_instr.setText(
            "✅ Mantén tu postura correcta durante 5 segundos...\n"
            "Espalda recta, mira al frente."
        )
        self._lbl_estado.setText("Capturando...")
        self._lbl_estado.setStyleSheet("color:#34c759;font-size:13px;font-weight:500;")

    def _saltar(self):
        self.desactivar()
        self.calibracion_cancelada.emit()

    # ── Tick ──────────────────────────────────────────────────────────────────

    def _tick(self):
        if not self._activo or self._cap is None:
            return
        ok, frame = self._cap.read()
        if not ok or frame is None:
            return

        # Detectar pose
        resultado = self._detector.detectar(frame)
        if resultado.pose_detectada:
            self._detector.dibujar_esqueleto(frame, resultado.landmarks_raw)

        # Si calibración activa y tenemos landmarks -> agregar frame
        if self._calibrando:
            if resultado.landmarks:
                progreso = self._calibrador.agregar_frame(resultado.landmarks, vista="frontal")
                pct = int(progreso * 100)
                self._prog.setValue(pct)
                segs_restantes = max(0, self.DURACION_SEG - int(progreso * self.DURACION_SEG))
                self._lbl_estado.setText(f"Capturando... {segs_restantes}s restantes")

                # Overlay de progreso en el frame
                h, w = frame.shape[:2]
                cv2.rectangle(frame, (0, h-8), (int(w * progreso), h), (52,199,89), -1)

                if progreso >= 1.0:
                    self._finalizar_calibracion()
                    return
            else:
                # No se detecta postura: mostrar advertencia
                self._lbl_estado.setText("⚠️ No se detecta tu cuerpo. Siéntate derecho.")
                self._lbl_estado.setStyleSheet("color:orange;")
                h, w = frame.shape[:2]
                cv2.putText(frame, "No se detecta postura", (w//2-100, h//2),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0,0,255), 2)

        # Mostrar frame en el widget
        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w, ch = frame_rgb.shape
        img = QImage(frame_rgb.data, w, h, ch * w, QImage.Format_RGB888)
        self._lbl_cam.setPixmap(
            QPixmap.fromImage(img).scaled(
                self._lbl_cam.width(), self._lbl_cam.height(),
                Qt.KeepAspectRatio, Qt.SmoothTransformation,
            )
        )

    def _finalizar_calibracion(self):
        perfil = self._calibrador.finalizar("frontal")
        self._calibrando = False
        self._timer.stop()

        if perfil:
            self._prog.setValue(100)
            self._lbl_estado.setText("✅ Calibración completada")
            self._lbl_estado.setStyleSheet("color:#34c759;font-size:14px;font-weight:bold;")
            self._lbl_instr.setText(
                f"✅ Perfil guardado correctamente.\n"
                f"Torso: {perfil.altura_torso:.3f} | "
                f"Cuello base: {perfil.neck_base_deg:.1f}° | "
                f"Factor distancia: {perfil.factor_distancia:.2f}"
            )
            # Pequeña pausa antes de cerrar
            from PySide6.QtCore import QTimer as QT
            QT.singleShot(1500, lambda: (self.desactivar(), self.calibracion_completada.emit()))
        else:
            self._lbl_estado.setText("⚠️ Error en calibración. Intenta de nuevo.")
            self._lbl_estado.setStyleSheet("color:orange;")
            self._btn_inicio.setEnabled(True)
            self._btn_saltar.setEnabled(True)
            self._calibrando = False
