"""
Módulo de detección de postura con MediaPipe.
Responsabilidad única: detectar puntos clave del cuerpo en un frame.
Incluye puntos de rodillas y tobillos para análisis completo.
"""

import cv2
import mediapipe as mp
import numpy as np
from dataclasses import dataclass, field
from typing import Optional, Dict

from utils.logger import crear_logger

logger = crear_logger("deteccion_postura")

mp_pose = mp.solutions.pose
mp_dibujo = mp.solutions.drawing_utils


class PuntoClave:
    """Índices de landmarks de MediaPipe Pose (33 puntos en total)."""
    NARIZ = 0
    OJO_IZQ = 2
    OJO_DER = 5
    OREJA_IZQ = 7
    OREJA_DER = 8
    HOMBRO_IZQ = 11
    HOMBRO_DER = 12
    CODO_IZQ = 13
    CODO_DER = 14
    MUNECA_IZQ = 15
    MUNECA_DER = 16
    CADERA_IZQ = 23
    CADERA_DER = 24
    RODILLA_IZQ = 25
    RODILLA_DER = 26
    TOBILLO_IZQ = 27
    TOBILLO_DER = 28


@dataclass
class PuntoLandmark:
    """Representa un punto clave detectado con sus coordenadas normalizadas."""
    x: float          # 0.0 a 1.0 (relativo al ancho del frame)
    y: float          # 0.0 a 1.0 (relativo al alto del frame)
    z: float          # Profundidad relativa (positivo = más lejos)
    visibilidad: float  # 0.0 a 1.0


@dataclass
class ResultadoDeteccion:
    """Contiene todos los puntos detectados en un frame."""
    landmarks: Dict[int, PuntoLandmark] = field(default_factory=dict)
    pose_detectada: bool = False
    landmarks_raw: Optional[object] = None


class DetectorPostura:
    """
    Envuelve MediaPipe Pose para detectar puntos clave del cuerpo.
    """

    # Puntos clave relevantes para el análisis de postura (incluye rodillas y tobillos)
    PUNTOS_RELEVANTES = [
        PuntoClave.NARIZ,
        PuntoClave.OREJA_IZQ,
        PuntoClave.OREJA_DER,
        PuntoClave.HOMBRO_IZQ,
        PuntoClave.HOMBRO_DER,
        PuntoClave.CODO_IZQ,
        PuntoClave.CODO_DER,
        PuntoClave.MUNECA_IZQ,
        PuntoClave.MUNECA_DER,
        PuntoClave.CADERA_IZQ,
        PuntoClave.CADERA_DER,
        PuntoClave.RODILLA_IZQ,
        PuntoClave.RODILLA_DER,
        PuntoClave.TOBILLO_IZQ,
        PuntoClave.TOBILLO_DER,
    ]

    def __init__(
        self,
        confianza_deteccion: float = 0.6,
        confianza_seguimiento: float = 0.6,
        umbral_visibilidad: float = 0.5,
    ):
        """
        Args:
            confianza_deteccion: Umbral para iniciar detección de pose.
            confianza_seguimiento: Umbral para continuar seguimiento de pose.
            umbral_visibilidad: Confianza mínima para usar un punto detectado.
        """
        self.umbral_visibilidad = umbral_visibilidad

        self._pose = mp_pose.Pose(
            static_image_mode=False,
            model_complexity=1,           # 0=rápido, 1=balanceado, 2=preciso
            smooth_landmarks=True,
            enable_segmentation=False,
            min_detection_confidence=confianza_deteccion,
            min_tracking_confidence=confianza_seguimiento,
        )
        logger.info("MediaPipe Pose inicializado correctamente.")

    def detectar(self, frame_bgr: np.ndarray) -> ResultadoDeteccion:
        """
        Detecta la pose en un frame y devuelve los puntos clave.
        """
        frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        frame_rgb.flags.writeable = False
        resultado_mp = self._pose.process(frame_rgb)
        frame_rgb.flags.writeable = True

        if not resultado_mp.pose_landmarks:
            return ResultadoDeteccion(pose_detectada=False)

        landmarks = self._extraer_landmarks(resultado_mp.pose_landmarks)

        return ResultadoDeteccion(
            landmarks=landmarks,
            pose_detectada=True,
            landmarks_raw=resultado_mp.pose_landmarks,
        )

    def _extraer_landmarks(self, pose_landmarks) -> Dict[int, PuntoLandmark]:
        """
        Convierte los landmarks de MediaPipe a nuestro modelo de datos.
        """
        landmarks = {}

        for indice in self.PUNTOS_RELEVANTES:
            punto = pose_landmarks.landmark[indice]

            if punto.visibility >= self.umbral_visibilidad:
                landmarks[indice] = PuntoLandmark(
                    x=punto.x,
                    y=punto.y,
                    z=punto.z,
                    visibilidad=punto.visibility,
                )

        return landmarks

    def dibujar_esqueleto(
        self,
        frame: np.ndarray,
        landmarks_raw,
        color_conexiones: tuple = (100, 200, 100),
        color_puntos: tuple = (0, 200, 255),
    ) -> np.ndarray:
        """
        Dibuja el esqueleto de MediaPipe sobre el frame.
        """
        if landmarks_raw is None:
            return frame

        estilo_puntos = mp_dibujo.DrawingSpec(
            color=color_puntos,
            thickness=2,
            circle_radius=4,
        )
        estilo_conexiones = mp_dibujo.DrawingSpec(
            color=color_conexiones,
            thickness=2,
        )

        mp_dibujo.draw_landmarks(
            image=frame,
            landmark_list=landmarks_raw,
            connections=mp_pose.POSE_CONNECTIONS,
            landmark_drawing_spec=estilo_puntos,
            connection_drawing_spec=estilo_conexiones,
        )

        return frame

    def cerrar(self) -> None:
        """Libera los recursos de MediaPipe."""
        self._pose.close()
        logger.info("MediaPipe Pose cerrado.")

    def __enter__(self):
        return self

    def __exit__(self, tipo_exc, valor_exc, traceback_exc):
        self.cerrar()
