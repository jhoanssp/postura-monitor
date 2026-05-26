"""
SISTEMA DE MONITOREO DE POSTURA - v4.1
Punto de entrada principal. Soporte para cámara simple y dual.
"""

import argparse
import sys
import time
import signal
import os
from pathlib import Path

import cv2

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import camara, umbrales, telegram, visualizacion, modo
from core.captura_video import CapturaDualVideo, detectar_camaras_disponibles
from core.deteccion_postura import DetectorPostura
from core.analisis_postura import AnalizadorPostura, EstadoPostura
from core.monitor_segundo_plano import MonitorSegundoPlano
from database.base_datos import BaseDatosPostura
from notifications.notificaciones import GestorNotificacionesTelegram
from utils.visualizacion_hud import HUDPostura
from utils.logger import crear_logger

logger = crear_logger("main")


def verificar_onboarding() -> bool:
    try:
        from onboarding.wizard import mostrar_onboarding_si_necesario
        return mostrar_onboarding_si_necesario()
    except ImportError as e:
        logger.error(f"No se pudo importar onboarding: {e}")
        return True


# ── Modo DEBUG ────────────────────────────────────────────────────────────────

def ejecutar_modo_debug(indice_secundario=None) -> None:
    logger.info("=" * 60)
    logger.info("  MODO DEBUG v4.1 — cámara dual habilitada")
    logger.info("=" * 60)
    logger.info("Controles: [Q/ESC] Salir | [S] Esqueleto | [A] Ángulos | [T] Test Telegram")

    captura = CapturaDualVideo(camara, indice_secundario=indice_secundario)
    if not captura.iniciar():
        logger.error("No se pudo iniciar ninguna cámara.")
        sys.exit(1)

    detector_p   = DetectorPostura()
    detector_s   = DetectorPostura()
    analizador_p = AnalizadorPostura(umbrales)
    analizador_s = AnalizadorPostura(umbrales)
    base_datos   = BaseDatosPostura()
    notificaciones = GestorNotificacionesTelegram(telegram)
    hud          = HUDPostura(visualizacion, umbrales)

    sesion_id          = base_datos.iniciar_sesion()
    inicio_sesion      = time.time()
    ultimo_guardado_bd = time.time()
    INTERVALO_BD       = 5

    mostrar_esqueleto    = True
    mostrar_angulos_flag = True

    modo_texto = "DUAL" if captura.tiene_secundaria else "SIMPLE"
    logger.info(f"Modo de cámara: {modo_texto}")

    try:
        while True:
            frame_p, frame_s = captura.leer_frames()

            if frame_p is None:
                time.sleep(0.05)
                continue

            alto, ancho = frame_p.shape[:2]

            # ── Análisis principal ────────────────────────────────────────────
            det_p = detector_p.detectar(frame_p)
            if mostrar_esqueleto and det_p.pose_detectada:
                detector_p.dibujar_esqueleto(frame_p, det_p.landmarks_raw)
            res_p = analizador_p.analizar(det_p.landmarks, ancho, alto)

            # ── Análisis secundario ───────────────────────────────────────────
            res_s = None
            if captura.tiene_secundaria and frame_s is not None:
                alto_s, ancho_s = frame_s.shape[:2]
                det_s = detector_s.detectar(frame_s)
                if mostrar_esqueleto and det_s.pose_detectada:
                    detector_s.dibujar_esqueleto(frame_s, det_s.landmarks_raw)
                res_s = analizador_s.analizar(det_s.landmarks, ancho_s, alto_s)

            # ── Fusionar ──────────────────────────────────────────────────────
            from core.monitor_segundo_plano import MonitorSegundoPlano
            _mon = MonitorSegundoPlano.__new__(MonitorSegundoPlano)
            resultado = _mon._fusionar(res_p, res_s) if res_s else res_p

            # ── HUD en ventana principal ──────────────────────────────────────
            frame_p = hud.renderizar(frame_p, resultado, mostrar_angulos=mostrar_angulos_flag)

            # ── Etiqueta modo cámara ──────────────────────────────────────────
            cv2.putText(
                frame_p,
                f"CAM: {modo_texto} | Principal={camara.indice_camara}"
                + (f" Sec={captura.indice_secundario}" if captura.tiene_secundaria else ""),
                (10, frame_p.shape[0] - 10),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (180, 180, 180), 1,
            )

            cv2.imshow("Monitor de Postura v4.1 — Principal [Q=Salir]", frame_p)

            # ── Ventana secundaria ────────────────────────────────────────────
            if captura.tiene_secundaria and frame_s is not None:
                # HUD simplificado para la secundaria
                estado_color = {
                    EstadoPostura.CORRECTA:    (0, 200, 0),
                    EstadoPostura.ADVERTENCIA: (0, 165, 255),
                    EstadoPostura.INCORRECTA:  (0, 0, 220),
                    EstadoPostura.SIN_DETECCION: (128, 128, 128),
                }.get(res_s.estado if res_s else EstadoPostura.SIN_DETECCION, (128, 128, 128))

                etiqueta = f"Sec ({res_s.orientacion if res_s else '-'}): " + \
                           (res_s.mensaje_estado if res_s else "Sin detección")
                cv2.putText(
                    frame_s, etiqueta, (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, estado_color, 2,
                )
                cv2.imshow("Monitor de Postura v4.1 — Secundaria", frame_s)

            # ── BD ────────────────────────────────────────────────────────────
            ahora = time.time()
            if ahora - ultimo_guardado_bd >= INTERVALO_BD:
                base_datos.guardar_postura(
                    sesion_id=sesion_id,
                    estado=resultado.estado.value,
                    angulo_cuello=resultado.angulos.angulo_cuello,
                    angulo_espalda=resultado.angulos.angulo_espalda,
                    inclinacion_lateral=resultado.angulos.inclinacion_lateral,
                )
                ultimo_guardado_bd = ahora

            # ── Alertas ───────────────────────────────────────────────────────
            if resultado.debe_alertar:
                tipo = (resultado.alertas_activas[0].value
                        if resultado.alertas_activas else "Mala postura")
                alerta_id = base_datos.guardar_alerta(
                    sesion_id=sesion_id,
                    tipo_alerta=tipo,
                    tiempo_mala_postura=resultado.tiempo_mala_postura_segundos,
                )
                enviado = notificaciones.enviar_alerta_postura(
                    tipo_alerta=tipo,
                    tiempo_mala_postura=resultado.tiempo_mala_postura_segundos,
                    angulo_cuello=resultado.angulos.angulo_cuello,
                    angulo_espalda=resultado.angulos.angulo_espalda,
                )
                if enviado and alerta_id:
                    base_datos.marcar_alerta_telegram(alerta_id)

            if resultado.debe_alertar_sedentarismo:
                alerta_id = base_datos.guardar_alerta(
                    sesion_id=sesion_id,
                    tipo_alerta="Sedentarismo",
                    tiempo_mala_postura=resultado.tiempo_sin_cambio_segundos,
                )
                notificaciones.enviar_alerta_sedentarismo(resultado.tiempo_sin_cambio_segundos)
                if alerta_id:
                    base_datos.marcar_alerta_telegram(alerta_id)

            # ── Teclas ────────────────────────────────────────────────────────
            tecla = cv2.waitKey(1) & 0xFF
            if tecla in (ord("q"), ord("Q"), 27):
                break
            elif tecla in (ord("s"), ord("S")):
                mostrar_esqueleto = not mostrar_esqueleto
            elif tecla in (ord("a"), ord("A")):
                mostrar_angulos_flag = not mostrar_angulos_flag
            elif tecla in (ord("t"), ord("T")):
                notificaciones.enviar_prueba()

    finally:
        duracion = time.time() - inicio_sesion
        base_datos.cerrar_sesion(sesion_id, duracion)
        resumen = base_datos.obtener_resumen_sesion(sesion_id)
        notificaciones.enviar_resumen_sesion(resumen)
        captura.liberar()
        detector_p.cerrar()
        detector_s.cerrar()
        cv2.destroyAllWindows()
        logger.info("Sistema finalizado.")


# ── Modo PRODUCCIÓN ───────────────────────────────────────────────────────────

def ejecutar_modo_produccion(indice_secundario=None) -> None:
    logger.info("MODO PRODUCCIÓN v4.1")
    monitor = MonitorSegundoPlano()

    def manejar_senial(sig, frame):
        monitor.detener()
        sys.exit(0)

    signal.signal(signal.SIGINT,  manejar_senial)
    signal.signal(signal.SIGTERM, manejar_senial)

    if not monitor.iniciar():
        sys.exit(1)

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        monitor.detener()


# ── Argumentos ────────────────────────────────────────────────────────────────

def parsear_argumentos():
    # Mostrar cámaras disponibles al iniciar
    disponibles = detectar_camaras_disponibles()

    parser = argparse.ArgumentParser(
        description="Monitor de Postura v4.1 — soporte cámara dual",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"Cámaras detectadas en este sistema: {disponibles}",
    )
    parser.add_argument("--modo",     choices=["debug", "produccion"], default="produccion")
    parser.add_argument("--camara",   type=int, default=0,
                        help="Índice de la cámara principal (default: 0)")
    parser.add_argument("--camara2",  type=int, default=None,
                        help="Índice de la cámara secundaria (auto-detecta si no se indica)")
    parser.add_argument("--skip-onboarding", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    args = parsear_argumentos()
    camara.indice_camara = args.camara

    if not args.skip_onboarding:
        if not verificar_onboarding():
            print("Configuración cancelada.")
            sys.exit(0)

    if args.modo == "produccion":
        modo.debug = False
        ejecutar_modo_produccion(indice_secundario=args.camara2)
    else:
        modo.debug = True
        ejecutar_modo_debug(indice_secundario=args.camara2)

