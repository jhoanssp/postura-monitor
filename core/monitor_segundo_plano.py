"""
Monitor en segundo plano — v4.1 (soporte cámara dual)
"""

import threading
import time
import sys
from typing import Optional

from config import camara, umbrales, telegram
from core.captura_video import CapturaDualVideo
from core.deteccion_postura import DetectorPostura
from core.analisis_postura import AnalizadorPostura, ResultadoAnalisis, EstadoPostura
from database.base_datos import BaseDatosPostura
from notifications.notificaciones import GestorNotificacionesTelegram
from utils.logger import crear_logger

logger = crear_logger("monitor_segundo_plano")


class MonitorSegundoPlano:
    INTERVALO_GUARDADO_BD = 5

    def __init__(self):
        self._captura        = CapturaDualVideo(camara)
        self._detector_p     = DetectorPostura()
        self._detector_s     = DetectorPostura()
        self._analizador_p   = AnalizadorPostura(umbrales)
        self._analizador_s   = AnalizadorPostura(umbrales)
        self._base_datos     = BaseDatosPostura()
        self._notificaciones = GestorNotificacionesTelegram(telegram)
        self.activo          = False
        self.sesion_id       = None
        self._hilo           = None
        self._inicio_sesion      = 0.0
        self._ultimo_guardado_bd = 0.0

    def iniciar(self) -> bool:
        if self.activo:
            return False
        if not self._captura.iniciar():
            return False
        self.sesion_id      = self._base_datos.iniciar_sesion()
        self._inicio_sesion = time.time()
        self.activo         = True
        self._hilo = threading.Thread(
            target=self._bucle_monitoreo, name="monitor-postura", daemon=True
        )
        self._hilo.start()
        logger.info(
            f"Monitor iniciado. "
            f"Modo: {'DUAL' if self._captura.tiene_secundaria else 'SIMPLE'}"
        )
        return True

    def detener(self) -> None:
        logger.info("Deteniendo monitor...")
        self.activo = False
        if self._hilo and self._hilo.is_alive():
            self._hilo.join(timeout=5.0)
        self._finalizar_sesion()
        self._captura.liberar()
        self._detector_p.cerrar()
        self._detector_s.cerrar()
        logger.info("Monitor detenido.")

    def _bucle_monitoreo(self) -> None:
        logger.info("Bucle de monitoreo iniciado.")
        while self.activo:
            frame_p, frame_s = self._captura.leer_frames()
            if frame_p is None:
                time.sleep(0.05)
                continue

            alto, ancho = frame_p.shape[:2]
            det_p = self._detector_p.detectar(frame_p)
            res_p = self._analizador_p.analizar(det_p.landmarks, ancho, alto)

            res_s = None
            if self._captura.tiene_secundaria and frame_s is not None:
                alto_s, ancho_s = frame_s.shape[:2]
                det_s = self._detector_s.detectar(frame_s)
                res_s = self._analizador_s.analizar(det_s.landmarks, ancho_s, alto_s)

            resultado = self._fusionar(res_p, res_s)

            ahora = time.time()
            if ahora - self._ultimo_guardado_bd >= self.INTERVALO_GUARDADO_BD:
                self._base_datos.guardar_postura(
                    sesion_id=self.sesion_id,
                    estado=resultado.estado.value,
                    angulo_cuello=resultado.angulos.angulo_cuello,
                    angulo_espalda=resultado.angulos.angulo_espalda,
                    inclinacion_lateral=resultado.angulos.inclinacion_lateral,
                )
                self._ultimo_guardado_bd = ahora

            if resultado.debe_alertar and self.sesion_id:
                tipo = (resultado.alertas_activas[0].value
                        if resultado.alertas_activas else "Mala postura")
                alerta_id = self._base_datos.guardar_alerta(
                    sesion_id=self.sesion_id,
                    tipo_alerta=tipo,
                    tiempo_mala_postura=resultado.tiempo_mala_postura_segundos,
                )
                enviado = self._notificaciones.enviar_alerta_postura(
                    tipo_alerta=tipo,
                    tiempo_mala_postura=resultado.tiempo_mala_postura_segundos,
                    angulo_cuello=resultado.angulos.angulo_cuello,
                    angulo_espalda=resultado.angulos.angulo_espalda,
                )
                if enviado and alerta_id:
                    self._base_datos.marcar_alerta_telegram(alerta_id)
        #        self._beep(1000, 200)  # eliminado en v4.2

            if resultado.debe_alertar_sedentarismo and self.sesion_id:
                alerta_id = self._base_datos.guardar_alerta(
                    sesion_id=self.sesion_id,
                    tipo_alerta="Sedentarismo: 30 min sin movimiento",
                    tiempo_mala_postura=resultado.tiempo_sin_cambio_segundos,
                )
                self._notificaciones.enviar_alerta_sedentarismo(
                    resultado.tiempo_sin_cambio_segundos
                )
                if alerta_id:
                    self._base_datos.marcar_alerta_telegram(alerta_id)
        #        self._beep(1500, 500)  # eliminado en v4.2

        logger.info("Bucle de monitoreo finalizado.")

    def _fusionar(
        self,
        res_p: ResultadoAnalisis,
        res_s: Optional[ResultadoAnalisis],
    ) -> ResultadoAnalisis:
        """Combina resultados de ambas cámaras — toma el peor estado."""
        if res_s is None or res_s.estado == EstadoPostura.SIN_DETECCION:
            return res_p
        if res_p.estado == EstadoPostura.SIN_DETECCION:
            return res_s

        if EstadoPostura.INCORRECTA in (res_p.estado, res_s.estado):
            peor = EstadoPostura.INCORRECTA
        elif EstadoPostura.ADVERTENCIA in (res_p.estado, res_s.estado):
            peor = EstadoPostura.ADVERTENCIA
        else:
            peor = EstadoPostura.CORRECTA

        alertas = list({*res_p.alertas_activas, *res_s.alertas_activas})

        # Ángulos: frontal de principal, lateral de secundaria
        angulos = res_p.angulos
        if res_s.orientacion == "lateral":
            angulos.neck_inclination  = res_s.angulos.neck_inclination
            angulos.torso_inclination = res_s.angulos.torso_inclination
        elif res_p.orientacion == "lateral":
            angulos.neck_inclination  = res_p.angulos.neck_inclination
            angulos.torso_inclination = res_p.angulos.torso_inclination

        from dataclasses import replace
        return replace(
            res_p,
            estado=peor,
            angulos=angulos,
            alertas_activas=alertas,
            debe_alertar=res_p.debe_alertar or res_s.debe_alertar,
            debe_alertar_sedentarismo=(
                res_p.debe_alertar_sedentarismo or res_s.debe_alertar_sedentarismo
            ),
            tiempo_mala_postura_segundos=max(
                res_p.tiempo_mala_postura_segundos,
                res_s.tiempo_mala_postura_segundos,
            ),
        )

    def _beep(self, freq: int, dur: int) -> None:
        if not umbrales.sonido_alerta:
            return
        try:
            if sys.platform == "win32":
                import winsound
                winsound.Beep(freq, dur)
            else:
                print("\a", end="", flush=True)
        except Exception:
            pass

    def _finalizar_sesion(self) -> None:
        if not self.sesion_id:
            return
        duracion = time.time() - self._inicio_sesion
        self._base_datos.cerrar_sesion(self.sesion_id, duracion)
        resumen = self._base_datos.obtener_resumen_sesion(self.sesion_id)
        self._notificaciones.enviar_resumen_sesion(resumen)
        logger.info(f"Sesión finalizada. Duración: {duracion:.1f}s")
