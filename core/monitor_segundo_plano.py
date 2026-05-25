"""
Monitor en segundo plano para la Fase 2 (producción) - v4
"""

import threading
import time
import sys

from config import camara, umbrales, telegram
from core.captura_video import CapturaVideo
from core.deteccion_postura import DetectorPostura
from core.analisis_postura import AnalizadorPostura
from database.base_datos import BaseDatosPostura
from notifications.notificaciones import GestorNotificacionesTelegram
from utils.logger import crear_logger

logger = crear_logger("monitor_segundo_plano")


class MonitorSegundoPlano:
    INTERVALO_GUARDADO_BD_SEGUNDOS = 5

    def __init__(self):
        self._captura = CapturaVideo(camara)
        self._detector = DetectorPostura()
        self._analizador = AnalizadorPostura(umbrales)  # Solo umbrales
        self._base_datos = BaseDatosPostura()
        self._notificaciones = GestorNotificacionesTelegram(telegram)
        self.activo = False
        self.sesion_id = None
        self._hilo = None
        self._inicio_sesion = 0.0
        self._ultimo_guardado_bd = 0.0

    def iniciar(self) -> bool:
        if self.activo:
            return False
        if not self._captura.iniciar():
            return False
        self.sesion_id = self._base_datos.iniciar_sesion()
        self._inicio_sesion = time.time()
        self.activo = True
        self._hilo = threading.Thread(target=self._bucle_monitoreo, name="monitor-postura", daemon=True)
        self._hilo.start()
        logger.info("Monitor iniciado en segundo plano.")
        return True

    def detener(self) -> None:
        logger.info("Deteniendo monitor...")
        self.activo = False
        if self._hilo and self._hilo.is_alive():
            self._hilo.join(timeout=5.0)
        self._finalizar_sesion()
        self._captura.liberar()
        self._detector.cerrar()
        logger.info("Monitor detenido.")

    def _bucle_monitoreo(self) -> None:
        logger.info("Bucle de monitoreo iniciado (producción).")
        while self.activo:
            exito, frame = self._captura.leer_frame()
            if not exito:
                time.sleep(0.1)
                continue

            alto, ancho = frame.shape[:2]
            resultado_deteccion = self._detector.detectar(frame)
            resultado_analisis = self._analizador.analizar(resultado_deteccion.landmarks, ancho, alto)

            ahora = time.time()
            if ahora - self._ultimo_guardado_bd >= self.INTERVALO_GUARDADO_BD_SEGUNDOS:
                self._base_datos.guardar_postura(
                    sesion_id=self.sesion_id,
                    estado=resultado_analisis.estado.value,
                    angulo_cuello=resultado_analisis.angulos.angulo_cuello,
                    angulo_espalda=resultado_analisis.angulos.angulo_espalda,
                    inclinacion_lateral=resultado_analisis.angulos.inclinacion_lateral,
                )
                self._ultimo_guardado_bd = ahora

            if resultado_analisis.debe_alertar and self.sesion_id:
                tipo_texto = resultado_analisis.alertas_activas[0].value if resultado_analisis.alertas_activas else "Mala postura"
                alerta_id = self._base_datos.guardar_alerta(
                    sesion_id=self.sesion_id,
                    tipo_alerta=tipo_texto,
                    tiempo_mala_postura=resultado_analisis.tiempo_mala_postura_segundos,
                )
                enviado = self._notificaciones.enviar_alerta_postura(
                    tipo_alerta=tipo_texto,
                    tiempo_mala_postura=resultado_analisis.tiempo_mala_postura_segundos,
                    angulo_cuello=resultado_analisis.angulos.angulo_cuello,
                    angulo_espalda=resultado_analisis.angulos.angulo_espalda,
                )
                if enviado and alerta_id:
                    self._base_datos.marcar_alerta_telegram(alerta_id)

                if umbrales.sonido_alerta:
                    try:
                        if sys.platform == "win32":
                            import winsound
                            winsound.Beep(1000, 200)
                        else:
                            print('\a', end='', flush=True)
                    except:
                        pass

            if resultado_analisis.debe_alertar_sedentarismo and self.sesion_id:
                alerta_id = self._base_datos.guardar_alerta(
                    sesion_id=self.sesion_id,
                    tipo_alerta="Sedentarismo: 30 min sin movimiento",
                    tiempo_mala_postura=resultado_analisis.tiempo_sin_cambio_segundos,
                )
                self._notificaciones.enviar_alerta_sedentarismo(resultado_analisis.tiempo_sin_cambio_segundos)
                if alerta_id:
                    self._base_datos.marcar_alerta_telegram(alerta_id)
                if umbrales.sonido_alerta:
                    try:
                        if sys.platform == "win32":
                            winsound.Beep(1500, 500)
                        else:
                            print('\a\a', end='', flush=True)
                    except:
                        pass

        logger.info("Bucle de monitoreo finalizado.")

    def _finalizar_sesion(self) -> None:
        if not self.sesion_id:
            return
        duracion = time.time() - self._inicio_sesion
        self._base_datos.cerrar_sesion(self.sesion_id, duracion)
        resumen = self._base_datos.obtener_resumen_sesion(self.sesion_id)
        self._notificaciones.enviar_resumen_sesion(resumen)
        logger.info(f"Sesión finalizada. Duración: {duracion:.1f}s. Resumen: {resumen}")
