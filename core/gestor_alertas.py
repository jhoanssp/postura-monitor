"""
Gestor de alertas con cooldown y tiempo mínimo de mala postura — v4.4
Evita el spam de notificaciones.
"""

import time
from typing import Dict, Optional, Tuple
from core.analizador_posturas import NivelAlerta
from utils.logger import crear_logger

logger = crear_logger("gestor_alertas")


class GestorAlertas:
    """
    Controla cuándo se envía una alerta:
    - Requiere N segundos continuos de mala postura antes de alertar
    - Impone cooldown entre alertas del mismo tipo
    - Resetea el timer si la postura mejora
    """

    def __init__(
        self,
        segundos_antes_alerta: int = 10,
        cooldown_segundos: int = 120,
    ):
        self._segundos_antes = segundos_antes_alerta
        self._cooldown       = cooldown_segundos

        self._inicio_mala_postura: Optional[float] = None
        self._ultimo_alerta: Dict[str, float] = {}

    def actualizar(
        self, nivel: NivelAlerta, tipo: str
    ) -> Tuple[bool, float]:
        """
        Evalúa si se debe enviar una alerta.

        Returns:
            (debe_alertar, tiempo_mala_postura_segundos)
        """
        ahora = time.time()

        if nivel == NivelAlerta.INCORRECTO:
            if self._inicio_mala_postura is None:
                self._inicio_mala_postura = ahora
                logger.debug(f"Inicio mala postura: {tipo}")

            tiempo = ahora - self._inicio_mala_postura

            if tiempo >= self._segundos_antes:
                ultimo = self._ultimo_alerta.get(tipo, 0.0)
                if ahora - ultimo >= self._cooldown:
                    self._ultimo_alerta[tipo] = ahora
                    logger.info(
                        f"Alerta enviada: {tipo} "
                        f"({tiempo:.1f}s de mala postura)"
                    )
                    return True, tiempo
        else:
            # Postura mejoró — resetear timer
            if self._inicio_mala_postura is not None:
                logger.debug("Postura corregida, reset timer.")
            self._inicio_mala_postura = None

        return False, 0.0

    def tiempo_mala_postura(self) -> float:
        if self._inicio_mala_postura is None:
            return 0.0
        return time.time() - self._inicio_mala_postura

    def reset(self):
        self._inicio_mala_postura = None
