"""
SISTEMA DE MONITOREO DE POSTURA — v4.4
Punto de entrada principal.
"""

import argparse, sys, time, signal, os
from pathlib import Path
import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import camara, umbrales, telegram, visualizacion, modo
from config.i18n import I18n
from core.captura_video import CapturaDualVideo, detectar_camaras_disponibles
from core.deteccion_postura import DetectorPostura
from core.analizador_posturas import AnalizadorPosturas, NivelAlerta, ResultadoAnalisis10
from core.detector_ausencia import DetectorAusencia, EstadoPresencia
from core.calibrador import Calibrador
from core.monitor_segundo_plano import MonitorSegundoPlano
from database.base_datos import BaseDatosPostura
from notifications.notificaciones import GestorNotificacionesTelegram
from utils.logger import crear_logger

logger = crear_logger("main")


def verificar_onboarding() -> bool:
    try:
        from onboarding.wizard import mostrar_onboarding_si_necesario
        return mostrar_onboarding_si_necesario()
    except ImportError as e:
        logger.error(f"onboarding: {e}"); return True


# ── HUD simple para modo debug (compatible con ResultadoAnalisis10) ──────────

def _dibujar_hud(frame: np.ndarray, resultado: ResultadoAnalisis10,
                 vista: str, modo_cam: str) -> np.ndarray:
    """HUD minimalista para debug — funciona con el nuevo sistema de 10 posturas."""
    COLORES = {
        NivelAlerta.CORRECTO:    (0, 200, 0),
        NivelAlerta.ADVERTENCIA: (0, 165, 255),
        NivelAlerta.INCORRECTO:  (0, 0, 220),
    }
    color = COLORES.get(resultado.nivel_global, (128, 128, 128))
    h, w = frame.shape[:2]

    # Panel superior izquierdo
    overlay = frame.copy()
    cv2.rectangle(overlay, (0, 0), (420, 90), (20, 20, 20), -1)
    cv2.addWeighted(overlay, 0.7, frame, 0.3, 0, frame)
    cv2.rectangle(frame, (0, 0), (6, 90), color, -1)

    nivel_txt = resultado.nivel_global.value.upper()
    if not resultado.usuario_presente:
        nivel_txt = "USUARIO AUSENTE"
        color = (128, 128, 128)

    cv2.putText(frame, f"Postura: {nivel_txt}", (14, 28),
                cv2.FONT_HERSHEY_SIMPLEX, 0.65, color, 2, cv2.LINE_AA)
    cv2.putText(frame, f"Vista: {vista.upper()}  |  Cam: {modo_cam}", (14, 55),
                cv2.FONT_HERSHEY_SIMPLEX, 0.48, (180, 180, 180), 1, cv2.LINE_AA)

    # Alertas activas
    if resultado.alertas_activas:
        alerta_txt = resultado.alertas_activas[0]
        cv2.putText(frame, f"! {alerta_txt}", (14, 78),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 220), 1, cv2.LINE_AA)

    # Panel derecho — ángulos de posturas detectadas
    x_panel = w - 300
    overlay2 = frame.copy()
    cv2.rectangle(overlay2, (x_panel - 10, 0), (w, min(len(resultado.posturas)*22 + 30, h)),
                  (20, 20, 20), -1)
    cv2.addWeighted(overlay2, 0.65, frame, 0.35, 0, frame)

    cv2.putText(frame, "POSTURAS DETECTADAS", (x_panel, 18),
                cv2.FONT_HERSHEY_SIMPLEX, 0.4, (180, 180, 180), 1)

    for i, p in enumerate(resultado.posturas[:10]):
        col_p = COLORES.get(p.nivel, (128, 128, 128))
        txt = f"{p.nombre[:22]}: {p.valor_medido:.1f}"
        cv2.putText(frame, txt, (x_panel, 36 + i*20),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.38, col_p, 1, cv2.LINE_AA)

    # Borde de color según estado
    if resultado.nivel_global == NivelAlerta.INCORRECTO:
        alpha = 0.8 if (int(time.time() * 2) % 2 == 0) else 0.3
        ov3 = frame.copy()
        cv2.rectangle(ov3, (0, 0), (w-1, h-1), (0, 0, 220), 4)
        cv2.addWeighted(ov3, alpha, frame, 1-alpha, 0, frame)

    # Teclas
    teclas = "[Q] Salir  [S] Esqueleto  [A] Info  [T] Test Telegram"
    cv2.putText(frame, teclas, (8, h - 10),
                cv2.FONT_HERSHEY_SIMPLEX, 0.4, (150, 150, 150), 1, cv2.LINE_AA)

    return frame


# ── Modo DEBUG ────────────────────────────────────────────────────────────────

def ejecutar_modo_debug(indice_secundario=None) -> None:
    logger.info("MODO DEBUG v4.4 — sistema de 10 posturas")

    captura = CapturaDualVideo(camara, indice_secundario=indice_secundario)
    if not captura.iniciar():
        logger.error("No se pudo iniciar ninguna cámara."); sys.exit(1)

    # Cargar calibración si existe
    calibrador = Calibrador()
    perfil = calibrador.cargar()
    umbrales_custom = calibrador.calcular_umbrales(perfil) if perfil else None
    if perfil:
        logger.info(f"Calibración cargada: torso={perfil.altura_torso:.3f}, "
                    f"factor_dist={perfil.factor_distancia:.2f}")
    else:
        logger.info("Sin calibración — usando umbrales estándar bibliográficos")

    detector_p   = DetectorPostura()
    detector_s   = DetectorPostura()
    analizador_p = AnalizadorPosturas(umbrales_custom)
    analizador_s = AnalizadorPosturas(umbrales_custom)
    ausencia_p   = DetectorAusencia()
    ausencia_s   = DetectorAusencia()
    base_datos   = BaseDatosPostura()
    notificaciones = GestorNotificacionesTelegram(telegram)

    sesion_id = base_datos.iniciar_sesion()
    inicio    = tiempo_bd = time.time()
    mostrar_esqueleto = True
    mostrar_info      = True
    modo_cam = "DUAL" if captura.tiene_secundaria else "SIMPLE"
    logger.info(f"Modo cámara: {modo_cam} | Calibración: {'Sí' if perfil else 'No'}")

    def _detectar_vista(lm):
        if not lm: return "frontal"
        hi = lm.get(11); hd = lm.get(12)
        if hi is None or hd is None: return "frontal"
        hix = hi.x if hasattr(hi, 'x') else hi[0]
        hdx = hd.x if hasattr(hd, 'x') else hd[0]
        return "lateral" if abs(hix - hdx) < 0.25 else "frontal"

    try:
        while True:
            fp, fs = captura.leer_frames()
            if fp is None: time.sleep(0.05); continue

            # ── Análisis cámara principal ─────────────────────────────────────
            det_p  = detector_p.detectar(fp)
            pres_p = ausencia_p.actualizar(det_p.landmarks)
            vista_p = _detectar_vista(det_p.landmarks)

            if mostrar_esqueleto and det_p.pose_detectada:
                detector_p.dibujar_esqueleto(fp, det_p.landmarks_raw)

            if pres_p == EstadoPresencia.PRESENTE:
                res_p = analizador_p.analizar(det_p.landmarks, vista_p)
            else:
                res_p = ResultadoAnalisis10(usuario_presente=False)

            # ── Análisis cámara secundaria ────────────────────────────────────
            res_s = None
            if captura.tiene_secundaria and fs is not None:
                det_s  = detector_s.detectar(fs)
                pres_s = ausencia_s.actualizar(det_s.landmarks)
                vista_s = _detectar_vista(det_s.landmarks)
                if mostrar_esqueleto and det_s.pose_detectada:
                    detector_s.dibujar_esqueleto(fs, det_s.landmarks_raw)
                res_s = analizador_s.analizar(det_s.landmarks, vista_s) \
                        if pres_s == EstadoPresencia.PRESENTE \
                        else ResultadoAnalisis10(usuario_presente=False)

            # ── Fusionar resultados ───────────────────────────────────────────
            mon = MonitorSegundoPlano.__new__(MonitorSegundoPlano)
            resultado = mon._fusionar(res_p, res_s) if res_s else res_p

            # ── HUD ───────────────────────────────────────────────────────────
            if mostrar_info:
                fp = _dibujar_hud(fp, resultado, vista_p, modo_cam)

            cv2.imshow("Monitor de Postura v4.4 — DEBUG [Q=Salir]", fp)

            if captura.tiene_secundaria and fs is not None:
                if res_s and mostrar_info:
                    fs = _dibujar_hud(fs, res_s,
                                      _detectar_vista(det_s.landmarks if det_s else None),
                                      "SEC")
                cv2.imshow("Cámara Secundaria", fs)

            # ── Guardar BD cada 5 segundos ────────────────────────────────────
            ahora = time.time()
            if ahora - tiempo_bd >= 5 and resultado.usuario_presente:
                base_datos.guardar_postura(
                    sesion_id=sesion_id,
                    estado=resultado.nivel_global.value,
                    angulo_cuello=resultado.angulo_cuello,
                    angulo_espalda=resultado.angulo_espalda,
                    inclinacion_lateral=resultado.inclinacion_lateral,
                )
                tiempo_bd = ahora

            # ── Alertas ───────────────────────────────────────────────────────
            if resultado.debe_alertar and resultado.usuario_presente:
                tipo = resultado.alertas_activas[0] if resultado.alertas_activas else "Mala postura"
                aid  = base_datos.guardar_alerta(sesion_id, tipo, 0)
                env  = notificaciones.enviar_alerta_postura(
                    tipo, 0, resultado.angulo_cuello, resultado.angulo_espalda)
                if env and aid: base_datos.marcar_alerta_telegram(aid)

            # Sedentarismo
            for det in [ausencia_p, ausencia_s]:
                if det.debe_alertar_sedentarismo:
                    t_s = det.tiempo_inmovil_segundos
                    aid = base_datos.guardar_alerta(sesion_id, "Sedentarismo", t_s)
                    notificaciones.enviar_alerta_sedentarismo(t_s)
                    if aid: base_datos.marcar_alerta_telegram(aid)

            # ── Teclas ────────────────────────────────────────────────────────
            tecla = cv2.waitKey(1) & 0xFF
            if tecla in (ord("q"), ord("Q"), 27): break
            elif tecla in (ord("s"), ord("S")): mostrar_esqueleto = not mostrar_esqueleto
            elif tecla in (ord("a"), ord("A")): mostrar_info      = not mostrar_info
            elif tecla in (ord("t"), ord("T")): notificaciones.enviar_prueba()

    finally:
        dur = time.time() - inicio
        base_datos.cerrar_sesion(sesion_id, dur)
        notificaciones.enviar_resumen_sesion(base_datos.obtener_resumen_sesion(sesion_id))
        captura.liberar()
        detector_p.cerrar(); detector_s.cerrar()
        cv2.destroyAllWindows()
        logger.info(f"Sesión debug finalizada. Duración: {dur:.1f}s")


# ── Modo PRODUCCIÓN ───────────────────────────────────────────────────────────

def ejecutar_modo_produccion(indice_secundario=None) -> None:
    logger.info("MODO PRODUCCIÓN v4.4")

    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QTimer
    from core.bandeja import BandejaSistema

    app = QApplication.instance() or QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    monitor = MonitorSegundoPlano()
    bandeja = BandejaSistema()

    _pausado_ref = [False]

    def toggle_pausa():
        _pausado_ref[0] = not _pausado_ref[0]
        if _pausado_ref[0]:
            monitor.detener(); bandeja.actualizar_estado("pausado")
        else:
            monitor.iniciar(); bandeja.actualizar_estado("correcto")

    def abrir_config():
        from onboarding.wizard import mostrar_configuracion
        mostrar_configuracion()

    def salir_app():
        monitor.detener(); bandeja.ocultar(); app.quit()

    bandeja.pausar_reanudar.connect(toggle_pausa)
    bandeja.abrir_config.connect(abrir_config)
    bandeja.salir.connect(salir_app)

    def _tick():
        if not _pausado_ref[0]:
            bandeja.actualizar_estado(getattr(monitor, "_ultimo_estado", "correcto"))

    timer = QTimer(); timer.timeout.connect(_tick); timer.start(3000)

    signal.signal(signal.SIGINT,  lambda s, f: salir_app())
    signal.signal(signal.SIGTERM, lambda s, f: salir_app())

    if not monitor.iniciar():
        bandeja.actualizar_estado("sin_camara")
    else:
        bandeja.notificar("Monitor de Postura",
                          "Monitoreando tu postura en segundo plano.")

    app.exec()


# ── Argumentos ────────────────────────────────────────────────────────────────

def parsear_argumentos():
    disponibles = detectar_camaras_disponibles()
    p = argparse.ArgumentParser(
        description="Monitor de Postura v4.4",
        epilog=f"Cámaras detectadas: {disponibles}",
    )
    p.add_argument("--modo",     choices=["debug", "produccion"], default="produccion")
    p.add_argument("--camara",   type=int, default=0)
    p.add_argument("--camara2",  type=int, default=None)
    p.add_argument("--skip-onboarding", action="store_true")
    p.add_argument("--configurar", action="store_true",
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
