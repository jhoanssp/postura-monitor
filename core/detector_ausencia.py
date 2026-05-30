"""
Detector de ausencia del usuario — v4.4
Sin detección >15s → AUSENTE (pausa alertas)
Sin movimiento >30min → INMOVIL (sedentarismo)
"""

import time
import numpy as np
from collections import deque
from enum import Enum
from typing import Optional, Dict
from utils.logger import crear_logger

logger = crear_logger("detector_ausencia")


class EstadoPresencia(Enum):
    PRESENTE = "presente"
    AUSENTE  = "ausente"
    INMOVIL  = "inmovil"


class DetectorAusencia:
    SEGUNDOS_AUSENTE  = 15
    SEGUNDOS_INMOVIL  = 1800
    BUFFER_VARIANZA   = 300
    UMBRAL_VARIANZA   = 0.0003

    def __init__(self):
        self._inicio_sin_deteccion: Optional[float] = None
        self._inicio_inmovil: Optional[float] = None
        self._buffer_x = deque(maxlen=self.BUFFER_VARIANZA)
        self._buffer_y = deque(maxlen=self.BUFFER_VARIANZA)
        self._estado   = EstadoPresencia.PRESENTE
        self._alerta_sedentarismo_emitida = False

    def actualizar(self, landmarks: Optional[Dict]) -> EstadoPresencia:
        ahora = time.time()

        if not landmarks:
            if self._inicio_sin_deteccion is None:
                self._inicio_sin_deteccion = ahora
            if ahora - self._inicio_sin_deteccion >= self.SEGUNDOS_AUSENTE:
                self._estado = EstadoPresencia.AUSENTE
            return self._estado

        self._inicio_sin_deteccion = None

        puntos = [landmarks.get(i) for i in [11,12,23,24] if landmarks.get(i)]
        if puntos:
            self._buffer_x.append(np.mean([p[0] for p in puntos]))
            self._buffer_y.append(np.mean([p[1] for p in puntos]))

        if len(self._buffer_x) >= 60:
            var = np.var(list(self._buffer_x)) + np.var(list(self._buffer_y))
            if var < self.UMBRAL_VARIANZA:
                if self._inicio_inmovil is None:
                    self._inicio_inmovil = ahora
                if ahora - self._inicio_inmovil >= self.SEGUNDOS_INMOVIL:
                    self._estado = EstadoPresencia.INMOVIL
                    return self._estado
            else:
                self._inicio_inmovil = None
                self._alerta_sedentarismo_emitida = False

        self._estado = EstadoPresencia.PRESENTE
        return self._estado

    @property
    def estado(self) -> EstadoPresencia:
        return self._estado

    @property
    def tiempo_inmovil_segundos(self) -> float:
        if self._inicio_inmovil is None:
            return 0.0
        return time.time() - self._inicio_inmovil

    @property
    def debe_alertar_sedentarismo(self) -> bool:
        if self._estado == EstadoPresencia.INMOVIL and not self._alerta_sedentarismo_emitida:
            self._alerta_sedentarismo_emitida = True
            return True
        return False

    def reset_sedentarismo(self):
        self._inicio_inmovil = None
        self._alerta_sedentarismo_emitida = False

    @property
    def presente(self) -> bool:
        return self._estado == EstadoPresencia.PRESENTE
