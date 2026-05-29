"""
SISTEMA DE MONITOREO DE POSTURA — v4.3
Punto de entrada principal.
"""

import argparse, sys, time, signal, os
from pathlib import Path
import cv2

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import camara, umbrales, telegram, visualizacion, modo
from config.i18n import I18n, t
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
        logger.error(f"onboarding: {e}"); return True


# ── Modo DEBUG ────────────────────────────────────────────────────────────────

def ejecutar_modo_debug(indice_secundario=None) -> None:
    logger.info("MODO DEBUG v4.3")
    captura = CapturaDualVideo(camara, indice_secundario=indice_secundario)
    if not captura.iniciar():
        logger.error("No se pudo iniciar ninguna cámara."); sys.exit(1)

    detector_p   = DetectorPostura(); detector_s = DetectorPostura()
    analizador_p = AnalizadorPostura(umbrales); analizador_s = AnalizadorPostura(umbrales)
    base_datos   = BaseDatosPostura()
    notificaciones = GestorNotificacionesTelegram(telegram)
    hud          = HUDPostura(visualizacion, umbrales)

    sesion_id = base_datos.iniciar_sesion()
    inicio    = tiempo_bd = time.time()
    mostrar_esqueleto = mostrar_angulos = True

    try:
        while True:
            fp, fs = captura.leer_frames()
            if fp is None: time.sleep(0.05); continue

            h, w = fp.shape[:2]
            det_p = detector_p.detectar(fp)
            if mostrar_esqueleto and det_p.pose_detectada:
                detector_p.dibujar_esqueleto(fp, det_p.landmarks_raw)
            res_p = analizador_p.analizar(det_p.landmarks, w, h)

            res_s = None
            if captura.tiene_secundaria and fs is not None:
                hs, ws = fs.shape[:2]
                det_s = detector_s.detectar(fs)
                if mostrar_esqueleto and det_s.pose_detectada:
                    detector_s.dibujar_esqueleto(fs, det_s.landmarks_raw)
                res_s = analizador_s.analizar(det_s.landmarks, ws, hs)

            mon = MonitorSegundoPlano.__new__(MonitorSegundoPlano)
            resultado = mon._fusionar(res_p, res_s) if res_s else res_p

            fp = hud.renderizar(fp, resultado, mostrar_angulos=mostrar_angulos)
            modo_txt = "DUAL" if captura.tiene_secundaria else "SIMPLE"
            cv2.putText(fp, f"CAM:{modo_txt}", (10, fp.shape[0]-10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.4, (180,180,180), 1)
            cv2.imshow("Monitor de Postura v4.3 [Q=Salir]", fp)

            if captura.tiene_secundaria and fs is not None and res_s:
                color = {EstadoPostura.CORRECTA:(0,200,0),
                         EstadoPostura.ADVERTENCIA:(0,165,255),
                         EstadoPostura.INCORRECTA:(0,0,220)}.get(res_s.estado,(128,128,128))
                cv2.putText(fs, res_s.mensaje_estado if hasattr(res_s,'mensaje_estado') else "",
                            (10,30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
                cv2.imshow("Secundaria", fs)

            ahora = time.time()
            if ahora - tiempo_bd >= 5:
                base_datos.guardar_postura(sesion_id, resultado.estado.value,
                    resultado.angulos.angulo_cuello, resultado.angulos.angulo_espalda,
                    resultado.angulos.inclinacion_lateral)
                tiempo_bd = ahora

            if resultado.debe_alertar:
                tipo = resultado.alertas_activas[0].value if resultado.alertas_activas else "Mala postura"
                aid  = base_datos.guardar_alerta(sesion_id, tipo, resultado.tiempo_mala_postura_segundos)
                env  = notificaciones.enviar_alerta_postura(tipo, resultado.tiempo_mala_postura_segundos,
                          resultado.angulos.angulo_cuello, resultado.angulos.angulo_espalda)
                if env and aid: base_datos.marcar_alerta_telegram(aid)

            tecla = cv2.waitKey(1) & 0xFF
            if tecla in (ord("q"), ord("Q"), 27): break
            elif tecla in (ord("s"), ord("S")): mostrar_esqueleto = not mostrar_esqueleto
            elif tecla in (ord("a"), ord("A")): mostrar_angulos   = not mostrar_angulos
            elif tecla in (ord("t"), ord("T")): notificaciones.enviar_prueba()

    finally:
        base_datos.cerrar_sesion(sesion_id, time.time()-inicio)
        notificaciones.enviar_resumen_sesion(base_datos.obtener_resumen_sesion(sesion_id))
        captura.liberar(); detector_p.cerrar(); detector_s.cerrar()
        cv2.destroyAllWindows()


# ── Modo PRODUCCIÓN con bandeja ───────────────────────────────────────────────

def ejecutar_modo_produccion(indice_secundario=None) -> None:
    logger.info("MODO PRODUCCIÓN v4.3")

    # Qt app es necesaria para la bandeja del sistema
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QTimer
    from core.bandeja import BandejaSistema

    app = QApplication.instance() or QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)   # No cerrar al cerrar ventanas

    monitor = MonitorSegundoPlano()
    bandeja = BandejaSistema()

    # ── Conectar señales de la bandeja ────────────────────────────────────────
    _pausado_ref = [False]

    def toggle_pausa():
        _pausado_ref[0] = not _pausado_ref[0]
        if _pausado_ref[0]:
            monitor.detener()
            bandeja.actualizar_estado("pausado")
            logger.info("Monitor pausado.")
        else:
            monitor.iniciar()
            bandeja.actualizar_estado("correcto")
            logger.info("Monitor reanudado.")

    def abrir_config():
        from onboarding.wizard import mostrar_configuracion
        mostrar_configuracion()

    def salir_app():
        monitor.detener()
        bandeja.ocultar()
        app.quit()

    bandeja.pausar_reanudar.connect(toggle_pausa)
    bandeja.abrir_config.connect(abrir_config)
    bandeja.salir.connect(salir_app)

    # ── Actualizar ícono según estado del monitor ─────────────────────────────
    def _tick():
        if _pausado_ref[0]:
            return
        try:
            estado_actual = getattr(monitor, "_ultimo_estado", "correcto")
            bandeja.actualizar_estado(estado_actual)
        except Exception:
            pass

    timer = QTimer(); timer.timeout.connect(_tick); timer.start(3000)

    # Señales del sistema para cierre limpio
    def _salir(sig, frame):
        salir_app()

    signal.signal(signal.SIGINT,  _salir)
    signal.signal(signal.SIGTERM, _salir)

    if not monitor.iniciar():
        bandeja.actualizar_estado("sin_camara")
        logger.error("No se pudo iniciar la cámara.")
    else:
        bandeja.notificar(
            "Monitor de Postura",
            "Monitoreando tu postura en segundo plano." if I18n.idioma()=="es"
            else "Monitoring your posture in the background.",
        )

    app.exec()


# ── Argumentos ────────────────────────────────────────────────────────────────

def parsear_argumentos():
    disponibles = detectar_camaras_disponibles()
    p = argparse.ArgumentParser(
        description="Monitor de Postura v4.3",
        epilog=f"Cámaras detectadas: {disponibles}",
    )
    p.add_argument("--modo",     choices=["debug","produccion"], default="produccion")
    p.add_argument("--camara",   type=int, default=0)
    p.add_argument("--camara2",  type=int, default=None)
    p.add_argument("--skip-onboarding", action="store_true")
    p.add_argument("--configurar",      action="store_true",
                   help="Abrir configuración y preferencias")
    return p.parse_args()


if __name__ == "__main__":
    args = parsear_argumentos()
    I18n.cargar()
    camara.indice_camara = args.camara

    if args.configurar:
        from onboarding.wizard import mostrar_configuracion
        mostrar_configuracion(); sys.exit(0)

    if not args.skip_onboarding:
        if not verificar_onboarding():
            print("Configuración cancelada."); sys.exit(0)

    if args.modo == "produccion":
        modo.debug = False
        ejecutar_modo_produccion(indice_secundario=args.camara2)
    else:
        modo.debug = True
        ejecutar_modo_debug(indice_secundario=args.camara2)
