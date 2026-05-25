"""
Módulo de captura de video desde la webcam.
"""

import cv2
import numpy as np
from typing import Optional, Tuple

from config.settings import ConfiguracionCamara
from utils.logger import crear_logger

logger = crear_logger("captura_video")


class CapturaVideo:
    def __init__(self, config: ConfiguracionCamara):
        self.config = config
        self._captura: Optional[cv2.VideoCapture] = None
        self.activa: bool = False

    def iniciar(self) -> bool:
        logger.info(f"Iniciando cámara en índice {self.config.indice_camara}...")
        self._captura = cv2.VideoCapture(self.config.indice_camara)
        if not self._captura.isOpened():
            logger.error(f"No se pudo abrir la cámara {self.config.indice_camara}.")
            return False
        self._captura.set(cv2.CAP_PROP_FRAME_WIDTH, self.config.ancho_frame)
        self._captura.set(cv2.CAP_PROP_FRAME_HEIGHT, self.config.alto_frame)
        self._captura.set(cv2.CAP_PROP_FPS, self.config.fps_objetivo)
        ancho_real = int(self._captura.get(cv2.CAP_PROP_FRAME_WIDTH))
        alto_real = int(self._captura.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps_real = self._captura.get(cv2.CAP_PROP_FPS)
        logger.info(f"Cámara iniciada: {ancho_real}x{alto_real} @ {fps_real:.1f} FPS")
        self.activa = True
        return True

    def leer_frame(self) -> Tuple[bool, Optional[np.ndarray]]:
        if not self.activa or self._captura is None:
            return False, None
        exito, frame = self._captura.read()
        if not exito:
            return False, None
        return True, frame

    def liberar(self) -> None:
        if self._captura is not None:
            self._captura.release()
            self.activa = False
            logger.info("Cámara liberada.")

    def __enter__(self):
        self.iniciar()
        return self

    def __exit__(self, tipo_exc, valor_exc, traceback_exc):
        self.liberar()
