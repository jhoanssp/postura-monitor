"""
Adaptador de base de datos que usa Supabase como backend.
Incluye paso automático del chat_id de Telegram.
"""

from typing import Dict, Any, Optional
from pathlib import Path

from database.supabase_client import supabase
from utils.logger import crear_logger
from config import telegram  # Para obtener el chat_id actual

logger = crear_logger("base_datos")


class BaseDatosPostura:
    def __init__(self, ruta_db: Path = None):
        self.supabase = supabase
        logger.info("BaseDatosPostura inicializado (backend: Supabase)")

    def iniciar_sesion(self, usuario: str = "estudiante") -> int:
        """
        Inicia una nueva sesión, asociando automáticamente el chat_id de Telegram
        que esté configurado en el archivo .env.
        """
        chat_id = telegram.chat_id if telegram.habilitado else None
        return self.supabase.iniciar_sesion(usuario, chat_id)

    def cerrar_sesion(self, sesion_id: int, duracion_segundos: float) -> None:
        self.supabase.cerrar_sesion(sesion_id, duracion_segundos)

    def guardar_postura(
        self,
        sesion_id: int,
        estado: str,
        angulo_cuello: Optional[float],
        angulo_espalda: Optional[float],
        inclinacion_lateral: Optional[float],
    ) -> None:
        self.supabase.guardar_postura(sesion_id, estado, angulo_cuello, angulo_espalda, inclinacion_lateral)

    def guardar_alerta(
        self,
        sesion_id: int,
        tipo_alerta: str,
        tiempo_mala_postura: float,
        notificado_telegram: bool = False,
    ) -> Optional[int]:
        return self.supabase.guardar_alerta(sesion_id, tipo_alerta, tiempo_mala_postura, notificado_telegram)

    def marcar_alerta_telegram(self, alerta_id: int) -> None:
        self.supabase.marcar_alerta_telegram(alerta_id)

    def obtener_resumen_sesion(self, sesion_id: int) -> Dict[str, Any]:
        return self.supabase.obtener_resumen_sesion(sesion_id)
