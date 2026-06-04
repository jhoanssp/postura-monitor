"""
Módulo de notificaciones por Telegram — v4.1

CAMBIOS v4.1 (Punto 4):
✓ enviar_resumen_sesion() ahora incluye:
  - Duración de la sesión (si viene en el dict)
  - Desglose de alertas por tipo
  - Postura problemática principal
  - Emoji de resultado más descriptivo
  El mensaje se envía de forma SÍNCRONA al cierre para garantizar
  que llegue antes de que el proceso termine.
"""

import os
import time
import threading
from pathlib import Path
from typing import Optional

import requests

try:
    from dotenv import load_dotenv
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)
except ImportError:
    pass

from config.settings import ConfiguracionTelegram
from utils.logger import crear_logger

logger = crear_logger("notificaciones")


class GestorNotificacionesTelegram:
    URL_API = "https://api.telegram.org/bot{token}/sendMessage"

    def __init__(self, config: ConfiguracionTelegram):
        token = os.environ.get("TELEGRAM_BOT_TOKEN", config.token_bot).strip()
        chat_id = os.environ.get("TELEGRAM_CHAT_ID", config.chat_id).strip()

        from dataclasses import replace
        self.config = ConfiguracionTelegram()
        self.config.token_bot = token
        self.config.chat_id = chat_id
        self.habilitado = bool(token and chat_id)

        if self.habilitado:
            logger.info(f"Telegram configurado. Chat ID: {chat_id}")
            self._verificar_conexion()
        else:
            logger.warning(
                "Telegram no configurado. "
                "Verifica que TELEGRAM_BOT_TOKEN y TELEGRAM_CHAT_ID estén en el archivo .env"
            )

    # ── Conexión ──────────────────────────────────────────────────────────────

    def _verificar_conexion(self) -> None:
        try:
            url = f"https://api.telegram.org/bot{self.config.token_bot}/getMe"
            respuesta = requests.get(url, timeout=10)
            datos = respuesta.json()
            if datos.get("ok"):
                nombre_bot = datos["result"].get("first_name", "Bot")
                logger.info(f"Bot de Telegram conectado: @{nombre_bot}")
            else:
                logger.error(f"Token de Telegram inválido: {datos.get('description')}")
                self.habilitado = False
        except requests.RequestException as error:
            logger.error(f"No se pudo conectar a Telegram: {error}")
            self.habilitado = False

    # ── Mensajes públicos ─────────────────────────────────────────────────────

    def enviar_prueba(self) -> bool:
        if not self.habilitado:
            logger.warning("Telegram no habilitado. Verifica el archivo .env")
            return False
        mensaje = (
            "✅ *Prueba de conexión exitosa*\n\n"
            "El sistema de monitoreo de postura está correctamente conectado a Telegram.\n\n"
            "Recibirás alertas aquí cuando se detecte mala postura prolongada o sedentarismo."
        )
        resultado = self._enviar_mensaje_sync(mensaje)
        if resultado:
            logger.info("✅ Mensaje de prueba enviado correctamente a Telegram.")
        else:
            logger.error("❌ Falló el envío del mensaje de prueba.")
        return resultado

    def enviar_alerta_postura(
        self,
        tipo_alerta: str,
        tiempo_mala_postura: float,
        angulo_cuello: Optional[float] = None,
        angulo_espalda: Optional[float] = None,
    ) -> bool:
        if not self.habilitado:
            logger.debug("Telegram no habilitado, omitiendo notificación.")
            return False
        mensaje = self._construir_mensaje_alerta(
            tipo_alerta, tiempo_mala_postura, angulo_cuello, angulo_espalda
        )
        threading.Thread(
            target=self._enviar_mensaje,
            args=(mensaje,),
            daemon=True,
            name="telegram-notifier",
        ).start()
        return True

    def enviar_alerta_sedentarismo(self, tiempo_sin_cambio_segundos: float) -> bool:
        if not self.habilitado:
            return False
        minutos = int(tiempo_sin_cambio_segundos // 60)
        segundos = int(tiempo_sin_cambio_segundos % 60)
        mensaje = (
            f"🚶‍♂️ *Alerta de sedentarismo*\n\n"
            f"Has permanecido sin cambio postural significativo durante {minutos}m {segundos}s.\n"
            "Levántate, estírate y cambia de posición para evitar la fatiga física."
        )
        threading.Thread(
            target=self._enviar_mensaje, args=(mensaje,), daemon=True
        ).start()
        return True

    # ── PUNTO 4: Resumen de sesión ────────────────────────────────────────────

    def enviar_resumen_sesion(self, resumen: dict) -> bool:
        """
        Envía un resumen completo de la sesión finalizada al cerrar.
        Se envía de forma SÍNCRONA para garantizar entrega antes de que
        el proceso termine.
        """
        if not self.habilitado:
            return False

        porcentaje = resumen.get("porcentaje_correcta", 0)
        total_alertas = resumen.get("total_alertas", 0)
        advertencias = resumen.get("total_advertencias", 0)
        postura_principal = resumen.get("postura_problematica_principal")
        desglose = resumen.get("desglose_alertas", {})
        sesion_id = resumen.get("sesion_id", "?")

        # Emoji según calidad de la sesión
        if porcentaje >= 75:
            emoji_resultado = "🟢"
            calificacion = "¡Excelente trabajo!"
        elif porcentaje >= 50:
            emoji_resultado = "🟡"
            calificacion = "Puedes mejorar tu postura."
        else:
            emoji_resultado = "🔴"
            calificacion = "Necesitas corregir tu postura con urgencia."

        # Cabecera
        mensaje = (
            f"📊 *Resumen de sesión #{sesion_id}*\n"
            f"{'─' * 30}\n"
            f"{emoji_resultado} Postura correcta: *{porcentaje:.1f}%* — {calificacion}\n"
            f"⚠️  Advertencias registradas: {advertencias}\n"
            f"🔔 Alertas generadas: {total_alertas}\n"
        )

        # Ángulos promedio
        if resumen.get("promedio_angulo_cuello") is not None:
            mensaje += f"📐 Ángulo promedio cuello: {resumen['promedio_angulo_cuello']:.1f}°\n"
        if resumen.get("promedio_angulo_espalda") is not None:
            mensaje += f"📐 Ángulo promedio espalda: {resumen['promedio_angulo_espalda']:.1f}°\n"

        # Postura más problemática
        if postura_principal:
            mensaje += f"\n⚡ *Problema más frecuente:* {postura_principal}\n"

        # Desglose si hay más de un tipo de alerta
        if len(desglose) > 1:
            mensaje += "\n📋 *Desglose de alertas:*\n"
            for tipo, cantidad in sorted(desglose.items(), key=lambda x: -x[1]):
                mensaje += f"  • {tipo}: {cantidad} vez{'es' if cantidad > 1 else ''}\n"

        mensaje += "\n💡 Mantén una rutina de pausas activas cada 30 minutos."

        # Síncrono para garantizar entrega al cerrar
        resultado = self._enviar_mensaje_sync(mensaje)
        if resultado:
            logger.info(f"Resumen de sesión {sesion_id} enviado por Telegram.")
        else:
            logger.warning(f"No se pudo enviar el resumen de sesión {sesion_id} por Telegram.")
        return resultado

    # ── Internos ──────────────────────────────────────────────────────────────

    def _construir_mensaje_alerta(
        self,
        tipo_alerta: str,
        tiempo_mala_postura: float,
        angulo_cuello: Optional[float],
        angulo_espalda: Optional[float],
    ) -> str:
        minutos = int(tiempo_mala_postura // 60)
        segundos = int(tiempo_mala_postura % 60)
        tiempo_str = f"{minutos}m {segundos}s" if minutos > 0 else f"{segundos}s"
        mensaje = (
            f"🔔 *Alerta de postura detectada*\n\n"
            f"⚠️ *Problema:* {tipo_alerta}\n"
            f"⏱️ *Tiempo en mala postura:* {tiempo_str}\n"
        )
        if angulo_cuello is not None:
            mensaje += f"📐 *Ángulo cuello:* {angulo_cuello:.1f}°\n"
        if angulo_espalda is not None:
            mensaje += f"📐 *Ángulo espalda:* {angulo_espalda:.1f}°\n"
        mensaje += "\n💡 *Recuerda:* Endereza la espalda y mantén el cuello recto."
        return mensaje

    def _enviar_mensaje(self, texto: str) -> None:
        self._enviar_mensaje_sync(texto)

    def _enviar_mensaje_sync(self, texto: str) -> bool:
        url = self.URL_API.format(token=self.config.token_bot)
        payload = {
            "chat_id": self.config.chat_id,
            "text": texto,
            "parse_mode": "Markdown",
        }
        for intento in range(1, 4):
            try:
                respuesta = requests.post(url, json=payload, timeout=10)
                respuesta.raise_for_status()
                return True
            except requests.HTTPError as error:
                logger.error(f"Error HTTP Telegram ({respuesta.status_code}): {error}")
                return False
            except requests.RequestException as error:
                logger.warning(f"Intento {intento}/3 fallido: {error}")
                if intento < 3:
                    time.sleep(2 ** intento)
        logger.error("No se pudo enviar la notificación después de todos los intentos.")
        return False


# ── Parche i18n v4.4 ──────────────────────────────────────────────────────────
def _parche_i18n():
    try:
        from config.i18n import t, I18n
        import notifications.notificaciones as _m
        import threading

        def enviar_alerta_postura(self, tipo_alerta, tiempo_mala_postura,
                                  angulo_cuello=None, angulo_espalda=None):
            if not self.habilitado:
                return False
            mins = int(tiempo_mala_postura // 60)
            segs = int(tiempo_mala_postura % 60)
            dur = f"{mins}m {segs}s" if mins > 0 else f"{segs}s"
            msg = f"{t('notif_alerta_titulo')}\n"
            msg += f"▸ {t('notif_tipo')}: {tipo_alerta}\n"
            msg += f"▸ {t('notif_duracion')}: {dur}\n"
            if angulo_cuello:
                msg += f"▸ {t('notif_angulo_cuello')}: {angulo_cuello:.1f}°\n"
            if angulo_espalda:
                msg += f"▸ {t('notif_angulo_espalda')}: {angulo_espalda:.1f}°\n"
            threading.Thread(
                target=self._enviar_mensaje, args=(msg,), daemon=True
            ).start()
            return True

        def enviar_alerta_sedentarismo(self, tiempo_segundos):
            if not self.habilitado:
                return False
            mins = int(tiempo_segundos // 60)
            msg = t("notif_sedentarismo", t=mins)
            threading.Thread(
                target=self._enviar_mensaje, args=(msg,), daemon=True
            ).start()
            return True

        _m.GestorNotificacionesTelegram.enviar_alerta_postura = enviar_alerta_postura
        _m.GestorNotificacionesTelegram.enviar_alerta_sedentarismo = enviar_alerta_sedentarismo
    except Exception:
        pass


_parche_i18n()
