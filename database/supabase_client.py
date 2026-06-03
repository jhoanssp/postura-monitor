"""
Cliente para Supabase (PostgreSQL en la nube) - Versión con soporte para chat_id de Telegram.
"""

import os
import requests
from typing import Dict, Any, Optional
from datetime import datetime
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils.logger import crear_logger

logger = crear_logger("supabase_client")


class SupabaseClient:
    def __init__(self):
        self.url = os.environ.get("SUPABASE_URL", "").strip()
        self.anon_key = os.environ.get("SUPABASE_ANON_KEY", "").strip()
        self.habilitado = bool(self.url and self.anon_key)
        if self.habilitado:
            logger.info(f"Supabase configurado: {self.url}")
            self._test_connection()
        else:
            logger.warning("Supabase no configurado. Verifica .env")

    def _headers(self) -> Dict[str, str]:
        return {
            "apikey": self.anon_key,
            "Authorization": f"Bearer {self.anon_key}",
            "Content-Type": "application/json",
            "Prefer": "return=representation"
        }

    def _test_connection(self):
        try:
            response = requests.get(f"{self.url}/rest/v1/sesiones?limit=1", headers=self._headers(), timeout=10)
            if response.status_code == 200:
                logger.info("Conexión a Supabase OK. Tabla 'sesiones' accesible.")
            elif response.status_code == 404:
                logger.error("Tabla 'sesiones' no encontrada. Ejecuta el script SQL de creación.")
            elif response.status_code == 401:
                logger.error("Error 401: Clave anónima inválida o sin permisos.")
            else:
                logger.error(f"Respuesta inesperada: {response.status_code} - {response.text[:200]}")
        except Exception as e:
            logger.error(f"No se pudo conectar a Supabase: {e}")

    def iniciar_sesion(self, usuario: str = "estudiante", chat_id: str = None) -> int:
        if not self.habilitado:
            return -1
        ahora = datetime.now().isoformat()
        payload = {
            "inicio": ahora,
            "usuario": usuario,
            "telegram_chat_id": chat_id,   # Nueva columna
            "fin": None,
            "duracion_segundos": 0
        }
        try:
            response = requests.post(
                f"{self.url}/rest/v1/sesiones",
                headers=self._headers(),
                json=payload,
                timeout=10
            )
            if response.status_code == 201:
                data = response.json()
                sesion_id = data[0]["id"] if isinstance(data, list) else data.get("id")
                logger.info(f"Sesión iniciada en Supabase. ID: {sesion_id} (Chat ID: {chat_id})")
                return sesion_id if sesion_id is not None else -1
            else:
                logger.error(f"Error HTTP {response.status_code} al iniciar sesión: {response.text[:300]}")
                if response.status_code in (401, 403):
                    logger.error("Posible problema de permisos (RLS). Ejecuta: ALTER TABLE sesiones DISABLE ROW LEVEL SECURITY;")
                return -1
        except Exception as e:
            logger.error(f"Excepción iniciando sesión: {e}")
            return -1

    def cerrar_sesion(self, sesion_id: int, duracion_segundos: float) -> None:
        if not self.habilitado or sesion_id == -1:
            return
        ahora = datetime.now().isoformat()
        payload = {"fin": ahora, "duracion_segundos": duracion_segundos}
        try:
            response = requests.patch(
                f"{self.url}/rest/v1/sesiones?id=eq.{sesion_id}",
                headers=self._headers(),
                json=payload,
                timeout=10
            )
            if response.status_code == 200:
                logger.info(f"Sesión {sesion_id} cerrada en Supabase")
            else:
                logger.error(f"Error cerrando sesión {sesion_id}: {response.status_code}")
        except Exception as e:
            logger.error(f"Excepción cerrando sesión: {e}")

    def guardar_postura(
        self,
        sesion_id: int,
        estado: str,
        angulo_cuello: Optional[float],
        angulo_espalda: Optional[float],
        inclinacion_lateral: Optional[float],
    ) -> bool:
        if not self.habilitado or sesion_id == -1:
            return False
        ahora = datetime.now().isoformat()
        payload = {
            "sesion_id": sesion_id,
            "timestamp": ahora,
            "estado": estado,
            "angulo_cuello": angulo_cuello,
            "angulo_espalda": angulo_espalda,
            "inclinacion_lateral": inclinacion_lateral,
        }
        try:
            response = requests.post(
                f"{self.url}/rest/v1/registros_postura",
                headers=self._headers(),
                json=payload,
                timeout=10
            )
            return response.status_code == 201
        except Exception as e:
            logger.error(f"Excepción guardando postura: {e}")
            return False

    def guardar_alerta(
        self,
        sesion_id: int,
        tipo_alerta: str,
        tiempo_mala_postura: float,
        notificado_telegram: bool = False,
    ) -> Optional[int]:
        if not self.habilitado or sesion_id == -1:
            return None
        ahora = datetime.now().isoformat()
        payload = {
            "sesion_id": sesion_id,
            "timestamp": ahora,
            "tipo_alerta": tipo_alerta,
            "tiempo_mala_postura": tiempo_mala_postura,
            "notificado_telegram": notificado_telegram,
        }
        try:
            response = requests.post(
                f"{self.url}/rest/v1/alertas",
                headers=self._headers(),
                json=payload,
                timeout=10
            )
            if response.status_code == 201:
                data = response.json()
                return data[0]["id"] if isinstance(data, list) else data.get("id")
            return None
        except Exception as e:
            logger.error(f"Excepción guardando alerta: {e}")
            return None

    def marcar_alerta_telegram(self, alerta_id: int) -> None:
        if not self.habilitado or not alerta_id:
            return
        try:
            requests.patch(
                f"{self.url}/rest/v1/alertas?id=eq.{alerta_id}",
                headers=self._headers(),
                json={"notificado_telegram": True},
                timeout=10
            )
        except Exception as e:
            logger.error(f"Error marcando alerta: {e}")

    def obtener_resumen_sesion(self, sesion_id: int) -> Dict[str, Any]:
        if not self.habilitado or sesion_id == -1:
            return {
                "total_registros": 0,
                "porcentaje_correcta": 0,
                "total_advertencias": 0,
                "total_incorrectos": 0,
                "promedio_angulo_cuello": 0,
                "promedio_angulo_espalda": 0,
                "total_alertas": 0,
            }
        try:
            response_posturas = requests.get(
                f"{self.url}/rest/v1/registros_postura?sesion_id=eq.{sesion_id}&select=*",
                headers=self._headers(),
                timeout=10
            )
            response_alertas = requests.get(
                f"{self.url}/rest/v1/alertas?sesion_id=eq.{sesion_id}&select=id",
                headers=self._headers(),
                timeout=10
            )
            if response_posturas.status_code == 200:
                posturas = response_posturas.json()
                if posturas:
                    total = len(posturas)
                    correctos = sum(1 for p in posturas if p.get("estado") == "correcto")
                    advertencias = sum(1 for p in posturas if p.get("estado") == "advertencia")
                    incorrectos = sum(1 for p in posturas if p.get("estado") == "incorrecto")
                    angulos_cuello = [p.get("angulo_cuello", 0) for p in posturas if p.get("angulo_cuello")]
                    angulos_espalda = [p.get("angulo_espalda", 0) for p in posturas if p.get("angulo_espalda")]
                    promedio_cuello = sum(angulos_cuello) / len(angulos_cuello) if angulos_cuello else 0
                    promedio_espalda = sum(angulos_espalda) / len(angulos_espalda) if angulos_espalda else 0
                else:
                    total = correctos = advertencias = incorrectos = 0
                    promedio_cuello = promedio_espalda = 0
            else:
                total = correctos = advertencias = incorrectos = 0
                promedio_cuello = promedio_espalda = 0

            total_alertas = len(response_alertas.json()) if response_alertas.status_code == 200 else 0

            return {
                "total_registros": total,
                "porcentaje_correcta": (correctos / total * 100) if total > 0 else 0,
                "total_advertencias": advertencias,
                "total_incorrectos": incorrectos,
                "promedio_angulo_cuello": promedio_cuello,
                "promedio_angulo_espalda": promedio_espalda,
                "total_alertas": total_alertas,
            }
        except Exception as e:
            logger.error(f"Error obteniendo resumen: {e}")
            return {
                "total_registros": 0,
                "porcentaje_correcta": 0,
                "total_advertencias": 0,
                "total_incorrectos": 0,
                "promedio_angulo_cuello": 0,
                "promedio_angulo_espalda": 0,
                "total_alertas": 0,
            }


supabase = SupabaseClient()
