"""
Widget de calibración de postura base — v4.5.4 CORREGIDO
- Mejor feedback visual cuando no detecta cuerpo
- Muestra el esqueleto en tiempo real
- Timeout y mensajes de ayuda
- Usa la misma cámara que el monitor principal
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
    TIMEOUT_SIN_DETECCION = 10  # segundos sin detectar cuerpo -> mensaje de ayuda

    def __init__(self, indice_camara: int = 0, parent=None):
        super().__init__(parent)
        self._idx    = indice_camara
        self._cap    = None
        self._detector  = DetectorPostura(confianza_deteccion=0.6, confianza_seguimiento=0.6, umbral_visibilidad=0.4)
        self._calibrador = Calibrador()
        self._timer  = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._frames = 0
        self._total  = self.DURACION_SEG * 30   # ~30fps
        self._activo = False
        self._calibrando = False
        self._inicio_sin_deteccion = None
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
        if self._activo:
            return
        try:
            self._cap = cv2.VideoCapture(self._idx)
            if self._cap.isOpened():
                # Configurar resolución
                self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
                self._timer.start(33)   # ~30fps
                self._activo = True
                logger.info(f"Cámara {self._idx} activada para calibración.")
                self._lbl_cam.setText("Cámara lista")
            else:
                self._lbl_cam.setText(f"No se pudo abrir la cámara {self._idx}")
                logger.error(f"No se pudo abrir cámara {self._idx}")
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
        self._inicio_sin_deteccion = None
        self._lbl_instr.setText(
            "✅ Mantén tu postura correcta durante 5 segundos...\n"
            "Espalda recta, mira al frente."
        )
        self._lbl_estado.setText("Capturando...")
        self._lbl_estado.setStyleSheet("color:#34c759;font-size:13px;font-weight:500;")
        self._prog.setValue(0)

    def _saltar(self):
        self.desactivar()
        self.calibracion_cancelada.emit()

    # ── Tick ──────────────────────────────────────────────────────────────────

    def _tick(self):
        if not self._activo or self._cap is None:
            return
        ok, frame = self._cap.read()
        if not ok or frame is None:
            # Mostrar mensaje de error de cámara
            self._lbl_cam.setText("Error leyendo cámara")
            return

        # Espejo para que el usuario se vea natural
        frame = cv2.flip(frame, 1)

        # Detectar pose
        resultado = self._detector.detectar(frame)
        if resultado.pose_detectada:
            self._detector.dibujar_esqueleto(frame, resultado.landmarks_raw)
            # Reset contador sin detección
            self._inicio_sin_deteccion = None
        else:
            # Marcar tiempo sin detección
            if self._inicio_sin_deteccion is None:
                self._inicio_sin_deteccion = cv2.getTickCount() / cv2.getTickFrequency()
            elapsed = (cv2.getTickCount() / cv2.getTickFrequency()) - self._inicio_sin_deteccion
            cv2.putText(frame, "Cuerpo no detectado", (20, 40),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0,0,255), 2)
            if elapsed > self.TIMEOUT_SIN_DETECCION and not self._calibrando:
                self._lbl_estado.setText("⚠️ No se detecta tu cuerpo. Asegúrate de estar frente a la cámara.")
                self._lbl_estado.setStyleSheet("color:orange;")

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
                # No se detectan landmarks: mostrar advertencia en la UI
                self._lbl_estado.setText("⚠️ No se detecta tu cuerpo. Siéntate derecho.")
                self._lbl_estado.setStyleSheet("color:orange;")
                # También dibujar texto en el frame
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
        self._timer.stop()  # Detener temporalmente para mostrar mensaje

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
            # Reactivar timer para seguir mostrando cámara
            self._timer.start(33)
