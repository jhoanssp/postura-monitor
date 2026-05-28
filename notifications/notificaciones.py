"""
Módulo de notificaciones por Telegram.
Responsabilidad única: enviar mensajes al usuario vía Telegram Bot API.
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
    """
    Envía notificaciones de postura al usuario vía Telegram.
    Las notificaciones se envían en un hilo separado para no bloquear el bucle principal.
    """

    URL_API = "https://api.telegram.org/bot{token}/sendMessage"

    def __init__(self, config: ConfiguracionTelegram):
        # Re-leer variables de entorno (por si .env se cargó después)
        token = os.environ.get("TELEGRAM_BOT_TOKEN", config.token_bot).strip()
        chat_id = os.environ.get("TELEGRAM_CHAT_ID", config.chat_id).strip()

        # Crear config actualizada
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

    def _verificar_conexion(self) -> None:
        """Verifica que el token sea válido consultando getMe."""
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

    def enviar_prueba(self) -> bool:
        """
        Envía un mensaje de prueba SINCRÓNICO para verificar que Telegram funciona.
        Bloquea hasta recibir respuesta (máx 10s).
        """
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
        """
        Envía una alerta de postura al usuario.
        El envío se realiza en un hilo separado (non-blocking).
        """
        if not self.habilitado:
            logger.debug("Telegram no habilitado, omitiendo notificación.")
            return False

        mensaje = self._construir_mensaje_alerta(
            tipo_alerta, tiempo_mala_postura, angulo_cuello, angulo_espalda
        )

        # Enviar en hilo separado para no bloquear el análisis
        hilo = threading.Thread(
            target=self._enviar_mensaje,
            args=(mensaje,),
            daemon=True,
            name="telegram-notifier",
        )
        hilo.start()
        return True

    def enviar_alerta_sedentarismo(self, tiempo_sin_cambio_segundos: float) -> bool:
        """
        Envía una alerta de sedentarismo (30 minutos sin cambio postural significativo).
        """
        if not self.habilitado:
            return False
        minutos = int(tiempo_sin_cambio_segundos // 60)
        segundos = int(tiempo_sin_cambio_segundos % 60)
        mensaje = (
            f"🚶‍♂️ *Alerta de sedentarismo*\n\n"
            f"Has permanecido sin cambio postural significativo durante {minutos}m {segundos}s.\n"
            "Levántate, estírate y cambia de posición para evitar la fatiga física."
        )
        # Envía de forma asíncrona
        threading.Thread(target=self._enviar_mensaje, args=(mensaje,), daemon=True).start()
        return True

    def enviar_resumen_sesion(self, resumen: dict) -> bool:
        """Envía un resumen estadístico de la sesión finalizada."""
        if not self.habilitado:
            return False

        porcentaje = resumen.get("porcentaje_correcta", 0)
        emoji_resultado = "✅" if porcentaje >= 70 else "⚠️" if porcentaje >= 40 else "❌"

        mensaje = (
            f"📊 *Resumen de sesión de monitoreo*\n\n"
            f"{emoji_resultado} Postura correcta: {porcentaje:.1f}%\n"
            f"⚠️ Advertencias registradas: {resumen.get('total_advertencias', 0)}\n"
            f"🔔 Alertas generadas: {resumen.get('total_alertas', 0)}\n"
        )

        if resumen.get("promedio_angulo_cuello"):
            mensaje += f"📐 Ángulo promedio cuello: {resumen['promedio_angulo_cuello']:.1f}°\n"
        if resumen.get("promedio_angulo_espalda"):
            mensaje += f"📐 Ángulo promedio espalda: {resumen['promedio_angulo_espalda']:.1f}°\n"

        threading.Thread(target=self._enviar_mensaje, args=(mensaje,), daemon=True).start()
        return True

    def _construir_mensaje_alerta(
        self,
        tipo_alerta: str,
        tiempo_mala_postura: float,
        angulo_cuello: Optional[float],
        angulo_espalda: Optional[float],
    ) -> str:
        """Construye el texto del mensaje de alerta con formato Markdown."""
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
        """Realiza la petición HTTP en hilo separado (non-blocking)."""
        self._enviar_mensaje_sync(texto)

    def _enviar_mensaje_sync(self, texto: str) -> bool:
        """
        Realiza la petición HTTP a la API de Telegram de forma síncrona.
        Returns: True si el envío fue exitoso.
        """
        url = self.URL_API.format(token=self.config.token_bot)
        payload = {
            "chat_id": self.config.chat_id,
            "text": texto,
            "parse_mode": "Markdown",
        }

        intentos = 3
        for intento in range(1, intentos + 1):
            try:
                respuesta = requests.post(url, json=payload, timeout=10)
                respuesta.raise_for_status()
                return True

            except requests.HTTPError as error:
                logger.error(f"Error HTTP Telegram ({respuesta.status_code}): {error}")
                logger.error(f"Respuesta: {respuesta.text}")
                return False

            except requests.RequestException as error:
                logger.warning(f"Intento {intento}/{intentos} fallido: {error}")
                if intento < intentos:
                    time.sleep(2 ** intento)

        logger.error("No se pudo enviar la notificación después de todos los intentos.")
        return False


# Parche i18n — se aplica si el módulo ya existe
def _parche_i18n():
    try:
        from config.i18n import t, I18n
        import notifications.notificaciones as _self

        _orig_alerta = _self.GestorNotificacionesTelegram.enviar_alerta_postura.__wrapped__ \
            if hasattr(_self.GestorNotificacionesTelegram.enviar_alerta_postura, '__wrapped__') \
            else None

        def enviar_alerta_postura(self, tipo_alerta, tiempo_mala_postura,
                                   angulo_cuello=None, angulo_espalda=None):
            if not self.configurado: return False
            mins = int(tiempo_mala_postura // 60)
            segs = int(tiempo_mala_postura % 60)
            dur  = f"{mins} {t('notif_minutos')} {segs} {t('notif_segundos')}" \
                   if mins > 0 else f"{segs} {t('notif_segundos')}"
            msg  = f"{t('notif_alerta_titulo')}\n"
            msg += f"▸ {t('notif_tipo')}: {tipo_alerta}\n"
            msg += f"▸ {t('notif_duracion')}: {dur}\n"
            if angulo_cuello:
                msg += f"▸ {t('notif_angulo_cuello')}: {angulo_cuello:.1f}°\n"
            if angulo_espalda:
                msg += f"▸ {t('notif_angulo_espalda')}: {angulo_espalda:.1f}°\n"
            return self._enviar(msg)

        _self.GestorNotificacionesTelegram.enviar_alerta_postura = enviar_alerta_postura

        def enviar_alerta_sedentarismo(self, tiempo_segundos):
            if not self.configurado: return False
            mins = int(tiempo_segundos // 60)
            return self._enviar(t("notif_sedentarismo", t=mins))

        _self.GestorNotificacionesTelegram.enviar_alerta_sedentarismo = enviar_alerta_sedentarismo

    except Exception:
        pass

_parche_i18n()
