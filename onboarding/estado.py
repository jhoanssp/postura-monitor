"""
Maneja el estado del onboarding — guardado en el directorio de config del usuario.
"""

import json
from pathlib import Path

from utils.logger import crear_logger

logger = crear_logger("onboarding_estado")


def _get_estado_path() -> Path:
    """Ruta al archivo de estado en el directorio de config del usuario."""
    from config.settings import CONFIG_DIR
    return CONFIG_DIR / ".onboarding_completed"


class OnboardingEstado:
    def __init__(self, archivo_estado: Path = None):
        self.archivo_estado = archivo_estado or _get_estado_path()
        self._estado = self._cargar()

    def _cargar(self):
        if not self.archivo_estado.exists():
            return {"completado": False, "version": 4}
        try:
            with open(self.archivo_estado, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error cargando estado: {e}")
            return {"completado": False, "version": 4}

    def guardar(self, completado: bool = True):
        self._estado = {"completado": completado, "version": 4}
        self.archivo_estado.parent.mkdir(parents=True, exist_ok=True)
        with open(self.archivo_estado, "w", encoding="utf-8") as f:
            json.dump(self._estado, f, indent=2)
        logger.info(f"Estado de onboarding guardado en: {self.archivo_estado}")

    @property
    def completado(self):
        return self._estado.get("completado", False)

    def marcar_completado(self):
        self.guardar(completado=True)

    def reset(self):
        """Permite re-ejecutar el onboarding (útil para soporte)."""
        self.guardar(completado=False)
