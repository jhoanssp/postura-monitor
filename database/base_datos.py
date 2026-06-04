"""
Adaptador de base de datos — Supabase backend.

CAMBIOS v4.1 (Punto 4):
✓ obtener_resumen_sesion() calcula y GUARDA en DB:
  - porcentaje_buena_postura
  - postura_problematica_principal
  - resumen_json  (desglose completo por tipo)

FIX v4.1.1:
✓ Eliminado uso de self.supabase.client (sintaxis SDK, no aplica aquí).
  Ahora se usan requests directamente, igual que el resto de SupabaseClient.
"""

import json
import requests
from typing import Dict, Any, Optional
from pathlib import Path

from database.supabase_client import supabase
from utils.logger import crear_logger
from config import telegram

logger = crear_logger("base_datos")


class BaseDatosPostura:
    def __init__(self, ruta_db: Path = None):
        self.supabase = supabase
        logger.info("BaseDatosPostura inicializado (backend: Supabase)")

    # ── Sesiones ──────────────────────────────────────────────────────────────

    def iniciar_sesion(self, usuario: str = "estudiante") -> int:
        chat_id = telegram.chat_id if telegram.habilitado else None
        return self.supabase.iniciar_sesion(usuario, chat_id)

    def cerrar_sesion(self, sesion_id: int, duracion_segundos: float) -> None:
        self.supabase.cerrar_sesion(sesion_id, duracion_segundos)

    # ── Postura / Alertas ─────────────────────────────────────────────────────

    def guardar_postura(
        self,
        sesion_id: int,
        estado: str,
        angulo_cuello: Optional[float],
        angulo_espalda: Optional[float],
        inclinacion_lateral: Optional[float],
    ) -> None:
        self.supabase.guardar_postura(
            sesion_id, estado, angulo_cuello, angulo_espalda, inclinacion_lateral
        )

    def guardar_alerta(
        self,
        sesion_id: int,
        tipo_alerta: str,
        tiempo_mala_postura: float,
        notificado_telegram: bool = False,
    ) -> Optional[int]:
        return self.supabase.guardar_alerta(
            sesion_id, tipo_alerta, tiempo_mala_postura, notificado_telegram
        )

    def marcar_alerta_telegram(self, alerta_id: int) -> None:
        self.supabase.marcar_alerta_telegram(alerta_id)

    # ── Resumen de sesión (PUNTO 4) ───────────────────────────────────────────

    def obtener_resumen_sesion(self, sesion_id: int) -> Dict[str, Any]:
        """
        Calcula el resumen estadístico de la sesión usando requests directamente
        (igual que SupabaseClient), luego ACTUALIZA la fila de sesiones con los
        campos de resumen para que queden persistidos en la DB.

        Retorna el dict con todos los datos listos para enviar por Telegram.
        """
        # Sesión inválida o Supabase deshabilitado — retornar vacío sin error
        if not self.supabase.habilitado or sesion_id == -1:
            return {
                "sesion_id": sesion_id,
                "porcentaje_correcta": 0.0,
                "total_advertencias": 0,
                "total_alertas": 0,
                "promedio_angulo_cuello": None,
                "promedio_angulo_espalda": None,
                "postura_problematica_principal": None,
                "desglose_alertas": {},
            }

        url = self.supabase.url
        headers = self.supabase._headers()

        try:
            # ── 1. Obtener registros de postura ───────────────────────────
            resp_reg = requests.get(
                f"{url}/rest/v1/registros_postura"
                f"?sesion_id=eq.{sesion_id}&select=estado,angulo_cuello,angulo_espalda",
                headers=headers,
                timeout=10,
            )
            registros = resp_reg.json() if resp_reg.status_code == 200 else []

            total = len(registros)
            correctos    = sum(1 for r in registros if r.get("estado") == "correcta")
            advertencias = sum(1 for r in registros if r.get("estado") == "advertencia")
            incorrectos  = sum(1 for r in registros if r.get("estado") == "incorrecta")

            porcentaje_correcta = (correctos / total * 100) if total > 0 else 0.0

            cuellos  = [r["angulo_cuello"]  for r in registros if r.get("angulo_cuello")  is not None]
            espaldas = [r["angulo_espalda"] for r in registros if r.get("angulo_espalda") is not None]
            prom_cuello  = sum(cuellos)  / len(cuellos)  if cuellos  else None
            prom_espalda = sum(espaldas) / len(espaldas) if espaldas else None

            # ── 2. Obtener alertas ────────────────────────────────────────
            resp_ale = requests.get(
                f"{url}/rest/v1/alertas?sesion_id=eq.{sesion_id}&select=tipo_alerta",
                headers=headers,
                timeout=10,
            )
            alertas = resp_ale.json() if resp_ale.status_code == 200 else []
            total_alertas = len(alertas)

            # Postura más problemática (tipo de alerta más frecuente)
            conteo_tipos: Dict[str, int] = {}
            for a in alertas:
                t = a.get("tipo_alerta", "")
                conteo_tipos[t] = conteo_tipos.get(t, 0) + 1
            postura_principal = (
                max(conteo_tipos, key=conteo_tipos.get) if conteo_tipos else None
            )

            # ── 3. Construir resumen_json completo ────────────────────────
            resumen_json = {
                "total_frames": total,
                "correctos": correctos,
                "advertencias": advertencias,
                "incorrectos": incorrectos,
                "total_alertas": total_alertas,
                "desglose_alertas": conteo_tipos,
                "promedio_angulo_cuello":  round(prom_cuello,  2) if prom_cuello  is not None else None,
                "promedio_angulo_espalda": round(prom_espalda, 2) if prom_espalda is not None else None,
            }

            # ── 4. Guardar resumen en DB (campos v4.1) ────────────────────
            try:
                patch_payload = {
                    "porcentaje_buena_postura":       round(porcentaje_correcta, 2),
                    "postura_problematica_principal": postura_principal,
                    "resumen_json":                   json.dumps(resumen_json, ensure_ascii=False),
                }
                resp_patch = requests.patch(
                    f"{url}/rest/v1/sesiones?id=eq.{sesion_id}",
                    headers=headers,
                    json=patch_payload,
                    timeout=10,
                )
                if resp_patch.status_code == 200:
                    logger.info(f"Resumen de sesión {sesion_id} guardado en DB.")
                else:
                    logger.warning(
                        f"No se pudo guardar resumen en DB: "
                        f"{resp_patch.status_code} — {resp_patch.text[:200]}"
                    )
            except Exception as e:
                # No bloquear el flujo si el PATCH falla
                logger.warning(f"Excepción guardando resumen en DB: {e}")

            # ── 5. Retornar dict para Telegram ────────────────────────────
            return {
                "sesion_id":                      sesion_id,
                "porcentaje_correcta":            porcentaje_correcta,
                "total_advertencias":             advertencias,
                "total_alertas":                  total_alertas,
                "promedio_angulo_cuello":         prom_cuello,
                "promedio_angulo_espalda":        prom_espalda,
                "postura_problematica_principal": postura_principal,
                "desglose_alertas":               conteo_tipos,
            }

        except Exception as e:
            logger.error(f"Error obteniendo resumen de sesión {sesion_id}: {e}")
            return {
                "sesion_id":                      sesion_id,
                "porcentaje_correcta":            0.0,
                "total_advertencias":             0,
                "total_alertas":                  0,
                "promedio_angulo_cuello":         None,
                "promedio_angulo_espalda":        None,
                "postura_problematica_principal": None,
                "desglose_alertas":               {},
            }
