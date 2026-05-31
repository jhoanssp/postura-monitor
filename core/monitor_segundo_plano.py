"""
Monitor en segundo plano — v4.4
"""

import threading, time, sys
from typing import Optional

from config import camara, umbrales, telegram
from core.captura_video import CapturaDualVideo
from core.deteccion_postura import DetectorPostura
from core.analizador_posturas import AnalizadorPosturas, NivelAlerta, ResultadoAnalisis10
from core.detector_ausencia import DetectorAusencia, EstadoPresencia
from core.calibrador import Calibrador
from database.base_datos import BaseDatosPostura
from notifications.notificaciones import GestorNotificacionesTelegram
from notifications.local import GestorNotificacionesLocal
from core.gestor_alertas import GestorAlertas
from utils.logger import crear_logger

logger = crear_logger("monitor_segundo_plano")


def _get_x(punto) -> float:
    """Extrae coordenada X de PuntoLandmark o lista/tupla."""
    if punto is None: return 0.0
    return punto.x if hasattr(punto, 'x') else float(punto[0])


class MonitorSegundoPlano:
    INTERVALO_BD = 5

    def __init__(self):
        self._captura        = CapturaDualVideo(camara)
        self._detector_p     = DetectorPostura()
        self._detector_s     = DetectorPostura()

        calibrador = Calibrador()
        perfil = calibrador.cargar()
        umbrales_custom = calibrador.calcular_umbrales(perfil) if perfil else None

        self._analizador_p   = AnalizadorPosturas(umbrales_custom)
        self._analizador_s   = AnalizadorPosturas(umbrales_custom)
        self._ausencia_p     = DetectorAusencia()
        self._ausencia_s     = DetectorAusencia()
        self._base_datos     = BaseDatosPostura()
        self._telegram       = GestorNotificacionesTelegram(telegram)
        self._local          = GestorNotificacionesLocal()
        self._gestor_alertas = GestorAlertas(
            segundos_antes_alerta=10,
            cooldown_segundos=120,
        )

        self.activo          = False
        self.sesion_id       = None
        self._hilo           = None
        self._inicio_sesion  = 0.0
        self._ultimo_bd      = 0.0
        self._ultimo_estado  = "correcto"

    def iniciar(self) -> bool:
        if self.activo: return False
        if not self._captura.iniciar(): return False
        self.sesion_id      = self._base_datos.iniciar_sesion()
        self._inicio_sesion = time.time()
        self.activo         = True
        self._hilo = threading.Thread(target=self._bucle, name="monitor-postura", daemon=True)
        self._hilo.start()
        self._local.inicio_monitor()
        logger.info(f"Monitor iniciado. Modo: {'DUAL' if self._captura.tiene_secundaria else 'SIMPLE'}")
        return True

    def detener(self):
        self.activo = False
        if self._hilo and self._hilo.is_alive():
            self._hilo.join(timeout=5.0)
        self._finalizar_sesion()
        self._captura.liberar()
        self._detector_p.cerrar()
        self._detector_s.cerrar()

    def _bucle(self):
        while self.activo:
            fp, fs = self._captura.leer_frames()
            if fp is None: time.sleep(0.05); continue

            h, w = fp.shape[:2]
            det_p  = self._detector_p.detectar(fp)
            pres_p = self._ausencia_p.actualizar(det_p.landmarks)
            res_p   = self._analizador_p.analizar(det_p.landmarks, "auto") \
                      if pres_p == EstadoPresencia.PRESENTE else ResultadoAnalisis10(usuario_presente=False)

            res_s = None
            if self._captura.tiene_secundaria and fs is not None:
                det_s  = self._detector_s.detectar(fs)
                pres_s = self._ausencia_s.actualizar(det_s.landmarks)
                res_s   = self._analizador_s.analizar(det_s.landmarks, "auto") \
                          if pres_s == EstadoPresencia.PRESENTE else ResultadoAnalisis10(usuario_presente=False)

            resultado = self._fusionar(res_p, res_s)

            self._ultimo_estado = {
                NivelAlerta.CORRECTO:    "correcto",
                NivelAlerta.ADVERTENCIA: "advertencia",
                NivelAlerta.INCORRECTO:  "incorrecto",
            }.get(resultado.nivel_global, "correcto")

            ahora = time.time()

            if ahora - self._ultimo_bd >= self.INTERVALO_BD and resultado.usuario_presente:
                self._base_datos.guardar_postura(
                    sesion_id=self.sesion_id,
                    estado=resultado.nivel_global.value,
                    angulo_cuello=resultado.angulo_cuello,
                    angulo_espalda=resultado.angulo_espalda,
                    inclinacion_lateral=resultado.inclinacion_lateral,
                )
                self._ultimo_bd = ahora

            # No alertar si usuario está distraído
            if getattr(resultado, 'usuario_distraido', False):
                self._gestor_alertas.reset()
                continue

            tipo_a = resultado.alertas_activas[0] if resultado.alertas_activas else "Mala postura"
            debe_alertar, tiempo_mala = self._gestor_alertas.actualizar(
                resultado.nivel_global, tipo_a
            )
            if debe_alertar and resultado.usuario_presente:
                aid = self._base_datos.guardar_alerta(
                    sesion_id=self.sesion_id, tipo_alerta=tipo_a,
                    tiempo_mala_postura=tiempo_mala)
                self._local.alerta_postura(tipo_a, tiempo_mala, resultado.angulo_cuello)
                env = self._telegram.enviar_alerta_postura(
                    tipo_alerta=tipo_a, tiempo_mala_postura=tiempo_mala,
                    angulo_cuello=resultado.angulo_cuello,
                    angulo_espalda=resultado.angulo_espalda,
                )
                if env and aid: self._base_datos.marcar_alerta_telegram(aid)

            for detector in [self._ausencia_p, self._ausencia_s]:
                if detector.debe_alertar_sedentarismo:
                    t_seg = detector.tiempo_inmovil_segundos
                    aid   = self._base_datos.guardar_alerta(
                        sesion_id=self.sesion_id, tipo_alerta="Sedentarismo",
                        tiempo_mala_postura=t_seg)
                    self._local.alerta_sedentarismo(t_seg)
                    self._telegram.enviar_alerta_sedentarismo(t_seg)
                    if aid: self._base_datos.marcar_alerta_telegram(aid)

    def _fusionar(self, rp: ResultadoAnalisis10,
                  rs: Optional[ResultadoAnalisis10]) -> ResultadoAnalisis10:
        if rs is None or not rs.usuario_presente: return rp
        if not rp.usuario_presente: return rs
        peor = (NivelAlerta.INCORRECTO
                if NivelAlerta.INCORRECTO in (rp.nivel_global, rs.nivel_global)
                else NivelAlerta.ADVERTENCIA
                if NivelAlerta.ADVERTENCIA in (rp.nivel_global, rs.nivel_global)
                else NivelAlerta.CORRECTO)
        from dataclasses import replace
        return replace(rp,
            posturas        = rp.posturas + rs.posturas,
            nivel_global    = peor,
            alertas_activas = list({*rp.alertas_activas, *rs.alertas_activas}),
            debe_alertar    = rp.debe_alertar or rs.debe_alertar,
            angulo_cuello   = rp.angulo_cuello or rs.angulo_cuello,
            angulo_espalda  = rp.angulo_espalda or rs.angulo_espalda,
        )

    def _finalizar_sesion(self):
        if not self.sesion_id: return
        dur = time.time() - self._inicio_sesion
        self._base_datos.cerrar_sesion(self.sesion_id, dur)
        resumen = self._base_datos.obtener_resumen_sesion(self.sesion_id)
        self._telegram.enviar_resumen_sesion(resumen)
