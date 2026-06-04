"""
SISTEMA DE MONITOREO DE POSTURA - v4.1
Punto de entrada principal. Compatible con ejecución directa y .deb instalado.

CAMBIOS v4.1:
✓ Fix punto 6: suprime los 5 warnings repetidos de QFontDatabase que
  OpenCV/Qt lanza al no encontrar el directorio de fuentes en el paquete
  instalado. Se establece QT_LOGGING_RULES antes de cualquier import de
  cv2 para que Qt los filtre desde el inicio.
"""

import os

# ── FIX PUNTO 6: silenciar QFontDatabase warnings de Qt/OpenCV ──────────────
# Qt imprime "Cannot find font directory /.../cv2/qt/fonts" 5 veces por sesión.
# Estas reglas filtran exactamente esa categoría sin afectar otros logs de Qt.
os.environ.setdefault("QT_LOGGING_RULES", "qt.qpa.fonts=false")
# Alternativa complementaria para entornos XCB:
os.environ.setdefault("QT_QPA_PLATFORM", os.environ.get("QT_QPA_PLATFORM", "xcb"))
# ─────────────────────────────────────────────────────────────────────────────

import argparse
import sys
import time
import signal
from pathlib import Path
import cv2

# Asegurar que el paquete raíz esté en el path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import camara, umbrales, telegram, visualizacion, modo
from core.captura_video import CapturaVideo
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


def ejecutar_modo_debug() -> None:
    logger.info("=" * 60)
    logger.info(" MODO DEBUG - v4.1")
    logger.info("=" * 60)
    logger.info("Controles: [Q/ESC] Salir | [S] Esqueleto | [A] Ángulos | [T] Test Telegram")

    captura = CapturaVideo(camara)
    if not captura.iniciar():
        logger.error("No se pudo iniciar la cámara.")
        sys.exit(1)

    detector = DetectorPostura()
    analizador = AnalizadorPostura(umbrales)
    base_datos = BaseDatosPostura()
    notificaciones = GestorNotificacionesTelegram(telegram)
    hud = HUDPostura(visualizacion, umbrales)

    sesion_id = base_datos.iniciar_sesion()
    inicio_sesion = time.time()
    ultimo_guardado_bd = time.time()
    INTERVALO_BD = 5

    logger.info(f"Sesión iniciada. ID: {sesion_id}")

    mostrar_esqueleto = True
    mostrar_angulos_flag = True

    try:
        while True:
            exito, frame = captura.leer_frame()
            if not exito:
                time.sleep(0.05)
                continue

            alto, ancho = frame.shape[:2]
            resultado_deteccion = detector.detectar(frame)

            if mostrar_esqueleto and resultado_deteccion.pose_detectada:
                detector.dibujar_esqueleto(frame, resultado_deteccion.landmarks_raw)

            resultado_analisis = analizador.analizar(
                resultado_deteccion.landmarks, ancho, alto
            )

            if resultado_analisis.estado != EstadoPostura.SIN_DETECCION:
                ang = resultado_analisis.angulos
                logger.debug(
                    f"Estado: {resultado_analisis.estado.value:12s} | "
                    f"Cuello: {ang.angulo_cuello or ang.neck_inclination or 0:5.1f}° | "
                    f"Espalda: {ang.angulo_espalda or 0:5.1f}° | "
                    f"Tiempo mala: {resultado_analisis.tiempo_mala_postura_segundos:.1f}s"
                )

            frame = hud.renderizar(
                frame, resultado_analisis, mostrar_angulos=mostrar_angulos_flag
            )

            ahora = time.time()
            if ahora - ultimo_guardado_bd >= INTERVALO_BD:
                base_datos.guardar_postura(
                    sesion_id=sesion_id,
                    estado=resultado_analisis.estado.value,
                    angulo_cuello=resultado_analisis.angulos.angulo_cuello,
                    angulo_espalda=resultado_analisis.angulos.angulo_espalda,
                    inclinacion_lateral=resultado_analisis.angulos.inclinacion_lateral,
                )
                ultimo_guardado_bd = ahora

            if resultado_analisis.debe_alertar:
                tipo_texto = (
                    resultado_analisis.alertas_activas[0].value
                    if resultado_analisis.alertas_activas
                    else "Mala postura"
                )
                alerta_id = base_datos.guardar_alerta(
                    sesion_id=sesion_id,
                    tipo_alerta=tipo_texto,
                    tiempo_mala_postura=resultado_analisis.tiempo_mala_postura_segundos,
                )
                enviado = notificaciones.enviar_alerta_postura(
                    tipo_alerta=tipo_texto,
                    tiempo_mala_postura=resultado_analisis.tiempo_mala_postura_segundos,
                    angulo_cuello=resultado_analisis.angulos.angulo_cuello,
                    angulo_espalda=resultado_analisis.angulos.angulo_espalda,
                )
                if enviado and alerta_id:
                    base_datos.marcar_alerta_telegram(alerta_id)

                if umbrales.sonido_alerta:
                    try:
                        if sys.platform == "win32":
                            import winsound
                            winsound.Beep(1000, 200)
                        else:
                            print("\a", end="", flush=True)
                    except Exception:
                        pass

            if resultado_analisis.debe_alertar_sedentarismo:
                alerta_id = base_datos.guardar_alerta(
                    sesion_id=sesion_id,
                    tipo_alerta="Sedentarismo: 30 min sin movimiento",
                    tiempo_mala_postura=resultado_analisis.tiempo_sin_cambio_segundos,
                )
                notificaciones.enviar_alerta_sedentarismo(
                    resultado_analisis.tiempo_sin_cambio_segundos
                )
                if alerta_id:
                    base_datos.marcar_alerta_telegram(alerta_id)

            cv2.imshow("Monitor de Postura v4.1 [Q=Salir]", frame)
            tecla = cv2.waitKey(1) & 0xFF
            if tecla in (ord("q"), ord("Q"), 27):
                break
            elif tecla in (ord("s"), ord("S")):
                mostrar_esqueleto = not mostrar_esqueleto
            elif tecla in (ord("a"), ord("A")):
                mostrar_angulos_flag = not mostrar_angulos_flag
            elif tecla in (ord("t"), ord("T")):
                logger.info("Enviando mensaje de prueba a Telegram...")
                notificaciones.enviar_prueba()

    finally:
        duracion = time.time() - inicio_sesion
        base_datos.cerrar_sesion(sesion_id, duracion)
        # ── PUNTO 4: obtener resumen → guarda en DB → envía por Telegram ──
        resumen = base_datos.obtener_resumen_sesion(sesion_id)
        notificaciones.enviar_resumen_sesion(resumen)
        # ──────────────────────────────────────────────────────────────────
        captura.liberar()
        detector.cerrar()
        cv2.destroyAllWindows()
        logger.info(f"Debug finalizado. Duración: {duracion:.1f}s")


def ejecutar_modo_produccion() -> None:
    logger.info("MODO PRODUCCIÓN - v4.1")
    monitor = MonitorSegundoPlano()

    def manejar_senial(sig, frame):
        monitor.detener()
        sys.exit(0)

    signal.signal(signal.SIGINT, manejar_senial)
    signal.signal(signal.SIGTERM, manejar_senial)

    if not monitor.iniciar():
        sys.exit(1)

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        monitor.detener()


def parsear_argumentos():
    parser = argparse.ArgumentParser(description="Monitor de Postura v4.1")
    parser.add_argument("--modo", choices=["debug", "produccion"], default="produccion")
    parser.add_argument("--camara", type=int, default=0)
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
        ejecutar_modo_produccion()
    else:
        modo.debug = True
        ejecutar_modo_debug()
