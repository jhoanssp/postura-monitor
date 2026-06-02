"""
SISTEMA DE MONITOREO DE POSTURA — v4.5
Punto de entrada principal.
Añadido: --calibrar y tecla [C] para calibración frontal.
"""

import argparse, sys, time, signal, os
from pathlib import Path
import cv2
import numpy as np

# Suprimir advertencias de fuentes de cv2/Qt antes de importar cv2
os.environ.setdefault("QT_LOGGING_RULES", "qt.qpa.fonts=false")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import camara, umbrales, telegram, visualizacion, modo
from config.i18n import I18n
from core.captura_video import detectar_camaras_disponibles
from core.deteccion_postura import DetectorPostura
from core.analizador_posturas import AnalizadorPosturas, NivelAlerta, ResultadoAnalisis10
from core.detector_ausencia import DetectorAusencia, EstadoPresencia
from core.gestor_alertas import GestorAlertas
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


# ── Función de calibración frontal reutilizable ───────────────────────────────

def ejecutar_calibracion_frontal(indice_camara: int = 0) -> bool:
    """
    Calibración frontal: pide al usuario mantener postura correcta 5 segundos.
    Devuelve True si exitosa, False si falla o se cancela.
    """
    print("\n=== CALIBRACIÓN DE POSTURA FRONTAL ===")
    print("Siéntate recto, mira al frente y mantén la posición.")
    print("La cámara capturará tus medidas durante 5 segundos.")
    print("Presiona ESC para cancelar.\n")

    cap = cv2.VideoCapture(indice_camara)
    if not cap.isOpened():
        print("❌ No se pudo abrir la cámara.")
        return False

    detector = DetectorPostura()
    calibrador = Calibrador()
    calibrador.iniciar()

    frames_necesarios = calibrador.FRAMES_REQUERIDOS
    frames_actuales = 0
    inicio_tiempo = time.time()

    cv2.namedWindow("Calibración - Mantén postura correcta", cv2.WINDOW_NORMAL)
    cv2.resizeWindow("Calibración - Mantén postura correcta", 640, 480)

    while frames_actuales < frames_necesarios:
        ret, frame = cap.read()
        if not ret:
            continue

        resultado = detector.detectar(frame)
        if resultado.pose_detectada:
            # Dibujar esqueleto
            detector.dibujar_esqueleto(frame, resultado.landmarks_raw)

            # Agregar frame a calibración
            progreso = calibrador.agregar_frame(resultado.landmarks, vista="frontal")
            frames_actuales = int(progreso * frames_necesarios)

            # Mostrar barra de progreso
            h, w = frame.shape[:2]
            cv2.rectangle(frame, (0, h-20), (int(w * progreso), h), (52,199,89), -1)
            cv2.putText(frame, f"Progreso: {int(progreso*100)}%", (10, h-30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255,255,255), 2)

        cv2.imshow("Calibración - Mantén postura correcta", frame)
        if cv2.waitKey(1) & 0xFF == 27:  # ESC cancelar
            break

    cap.release()
    cv2.destroyAllWindows()

    perfil = calibrador.finalizar("frontal")
    if perfil:
        print("\n✅ Calibración completada.")
        print(f"   Altura torso: {perfil.altura_torso:.3f}")
        print(f"   Ángulo cuello base: {perfil.neck_base_deg:.1f}°")
        print(f"   Factor distancia: {perfil.factor_distancia:.2f}")
        return True
    else:
        print("\n❌ Calibración fallida. Intenta de nuevo.")
        return False


# ── HUD para debug ────────────────────────────────────────────────────────────

def _dibujar_hud(frame: np.ndarray, resultado: ResultadoAnalisis10,
                 vista: str, modo_cam: str,
                 tiempo_mala: float = 0.0) -> np.ndarray:
    if frame is None or frame.size == 0:
        return frame

    COLORES = {
        NivelAlerta.CORRECTO:    (0, 200, 0),
        NivelAlerta.ADVERTENCIA: (0, 165, 255),
        NivelAlerta.INCORRECTO:  (0, 0, 220),
    }
    h, w = frame.shape[:2]
    color = COLORES.get(resultado.nivel_global, (128, 128, 128))

    if not resultado.usuario_presente:
        cv2.putText(frame, "USUARIO AUSENTE", (w//2 - 120, h//2),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.0, (128, 128, 128), 2)
        return frame

    if getattr(resultado, 'usuario_distraido', False):
        cv2.putText(frame, "USUARIO DISTRAIDO", (w//2 - 140, h//2),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 165, 255), 2)
        return frame

    # Panel superior
    overlay = frame.copy()
    cv2.rectangle(overlay, (0, 0), (min(460, w), 95), (15, 15, 15), -1)
    cv2.addWeighted(overlay, 0.75, frame, 0.25, 0, frame)
    cv2.rectangle(frame, (0, 0), (5, 95), color, -1)

    nivel_txt = resultado.nivel_global.value.upper()
    cv2.putText(frame, f"POSTURA: {nivel_txt}", (12, 28),
                cv2.FONT_HERSHEY_SIMPLEX, 0.65, color, 2, cv2.LINE_AA)

    if tiempo_mala > 0:
        cv2.putText(frame, f"Tiempo mala postura: {tiempo_mala:.0f}s",
                    (12, 52), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (200, 200, 200), 1)

    info_txt = f"Vista: {vista.upper()}  Cam: {modo_cam}"
    cv2.putText(frame, info_txt, (12, 72),
                cv2.FONT_HERSHEY_SIMPLEX, 0.40, (160, 160, 160), 1)

    if resultado.alertas_activas:
        cv2.putText(frame, f"! {resultado.alertas_activas[0][:40]}",
                    (12, 88), cv2.FONT_HERSHEY_SIMPLEX, 0.38,
                    (80, 80, 255), 1, cv2.LINE_AA)

    # Panel derecho — posturas detectadas
    panel_x = max(w - 310, 0)
    n_post   = min(len(resultado.posturas), 10)
    panel_h  = n_post * 22 + 32
    ov2 = frame.copy()
    cv2.rectangle(ov2, (panel_x - 5, 0), (w, panel_h), (15, 15, 15), -1)
    cv2.addWeighted(ov2, 0.70, frame, 0.30, 0, frame)

    cv2.putText(frame, "POSTURAS", (panel_x, 18),
                cv2.FONT_HERSHEY_SIMPLEX, 0.42, (160, 160, 160), 1)

    for i, p in enumerate(resultado.posturas[:10]):
        c = COLORES.get(p.nivel, (128, 128, 128))
        txt = f"{p.nombre[:24]}: {p.valor_medido:.1f}"
        cv2.putText(frame, txt, (panel_x, 34 + i * 22),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.36, c, 1, cv2.LINE_AA)

    # Borde rojo parpadeante
    if resultado.nivel_global == NivelAlerta.INCORRECTO:
        alpha = 0.8 if (int(time.time() * 2) % 2 == 0) else 0.2
        ov3 = frame.copy()
        cv2.rectangle(ov3, (0, 0), (w - 1, h - 1), (0, 0, 220), 4)
        cv2.addWeighted(ov3, alpha, frame, 1 - alpha, 0, frame)

    cv2.putText(frame, "[Q]Salir [S]Esqueleto [A]HUD [T]Test [C]Calibrar",
                (8, h - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.38,
                (120, 120, 120), 1)
    return frame


# ── Modo DEBUG — captura directa (más confiable en binario) ──────────────────

def ejecutar_modo_debug(indice_secundario=None) -> None:
    logger.info("MODO DEBUG v4.5")
    ANALIZAR_CADA = 3  # analiza 1 de cada 3 frames → ~10 análisis/s, muestra 30fps

    disponibles = detectar_camaras_disponibles()
    if not disponibles:
        logger.error("No se detectó ninguna cámara."); return

    idx_p = camara.indice_camara if camara.indice_camara in disponibles else disponibles[0]
    idx_s = None
    if indice_secundario is not None and indice_secundario in disponibles and indice_secundario != idx_p:
        idx_s = indice_secundario
    elif len(disponibles) > 1:
        for d in disponibles:
            if d != idx_p:
                idx_s = d; break

    # Captura DIRECTA — sin hilos, más estable en binario
    cap_p = cv2.VideoCapture(idx_p)
    cap_p.set(cv2.CAP_PROP_FRAME_WIDTH,  1280)
    cap_p.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
    cap_p.set(cv2.CAP_PROP_FPS, 30)
    if not cap_p.isOpened():
        logger.error(f"No se pudo abrir cámara {idx_p}."); return

    cap_s = None
    if idx_s is not None:
        cap_s = cv2.VideoCapture(idx_s)
        if not cap_s.isOpened():
            logger.warning(f"Cámara secundaria {idx_s} no disponible.")
            cap_s = None; idx_s = None

    modo_cam = f"DUAL(0={idx_p},1={idx_s})" if cap_s else f"SIMPLE({idx_p})"
    logger.info(f"Modo cámara: {modo_cam}")

    # Cargar calibración
    calibrador = Calibrador()
    perfil = calibrador.cargar()
    umbrales_custom = calibrador.calcular_umbrales(perfil) if perfil else None
    logger.info(f"Calibración: {'Sí' if perfil else 'No (umbrales estándar)'}")

    detector_p   = DetectorPostura()
    detector_s   = DetectorPostura() if cap_s else None
    analizador_p = AnalizadorPosturas(umbrales_custom)
    analizador_s = AnalizadorPosturas(umbrales_custom) if cap_s else None
    ausencia_p   = DetectorAusencia()
    ausencia_s   = DetectorAusencia() if cap_s else None
    ultimo_resultado = ResultadoAnalisis10(usuario_presente=True)
    gestor_alertas = GestorAlertas(
        segundos_antes_alerta=10,
        cooldown_segundos=120,
    )
    base_datos     = BaseDatosPostura()
    notificaciones = GestorNotificacionesTelegram(telegram)

    sesion_id   = base_datos.iniciar_sesion()
    inicio      = tiempo_bd = time.time()
    mostrar_hud = True
    mostrar_esq = True

    # Crear ventana con tamaño fijo
    win_p = "Monitor de Postura v4.5 — DEBUG [Q=Salir, C=Calibrar]"
    cv2.namedWindow(win_p, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(win_p, 960, 540)

    if cap_s:
        win_s = "Cámara Secundaria"
        cv2.namedWindow(win_s, cv2.WINDOW_NORMAL)
        cv2.resizeWindow(win_s, 640, 360)

    try:
        while True:
            # ── Leer frames directamente ──────────────────────────────────
            ok_p, fp = cap_p.read()
            if not ok_p or fp is None:
                time.sleep(0.02); continue

            fs_raw = None
            if cap_s:
                ok_s, fs_raw = cap_s.read()
                fs = cv2.flip(fs_raw, 1) if (ok_s and fs_raw is not None) else None

            # ── Análisis principal ────────────────────────────────────────
            det_p   = detector_p.detectar(fp)
            pres_p  = ausencia_p.actualizar(det_p.landmarks)
            vista_p = "auto"

            if mostrar_esq and det_p.pose_detectada:
                detector_p.dibujar_esqueleto(fp, det_p.landmarks_raw)

            res_p = analizador_p.analizar(det_p.landmarks, vista_p) \
                    if pres_p == EstadoPresencia.PRESENTE \
                    else ResultadoAnalisis10(usuario_presente=False)

            # ── Análisis secundario ───────────────────────────────────────
            res_s = None
            if cap_s and fs is not None and detector_s:
                det_s   = detector_s.detectar(fs)
                pres_s  = ausencia_s.actualizar(det_s.landmarks)
                vista_s = "auto"
                if mostrar_esq and det_s.pose_detectada:
                    detector_s.dibujar_esqueleto(fs, det_s.landmarks_raw)
                res_s = analizador_s.analizar(det_s.landmarks, vista_s) \
                        if pres_s == EstadoPresencia.PRESENTE \
                        else ResultadoAnalisis10(usuario_presente=False)

            # ── Fusionar ──────────────────────────────────────────────────
            mon = MonitorSegundoPlano.__new__(MonitorSegundoPlano)
            resultado = mon._fusionar(res_p, res_s) if res_s else res_p

            ultimo_resultado = resultado

            # ── Saltar análisis si distraído ─────────────────────────────
            if getattr(resultado, 'usuario_distraido', False):
                gestor_alertas.reset()

            # ── Gestor de alertas (cooldown + tiempo mínimo) ──────────────
            tipo_alerta = resultado.alertas_activas[0] if resultado.alertas_activas else "Mala postura"
            debe_alertar, tiempo_mala = gestor_alertas.actualizar(
                resultado.nivel_global, tipo_alerta
            )
            tiempo_acum = gestor_alertas.tiempo_mala_postura()

            # ── HUD ───────────────────────────────────────────────────────
            if mostrar_hud:
                vista_label = resultado.vista_detectada if hasattr(resultado, 'vista_detectada') else "auto"
                fp = _dibujar_hud(fp, resultado, vista_label, modo_cam, tiempo_acum)

            cv2.imshow(win_p, fp)

            if cap_s and fs is not None:
                if mostrar_hud and res_s:
                    fs = _dibujar_hud(fs, res_s,
                                      "auto",
                                      "SEC")
                cv2.imshow(win_s, fs)

            # ── BD cada 5s ────────────────────────────────────────────────
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

            # ── Alertas con cooldown ──────────────────────────────────────
            if debe_alertar and resultado.usuario_presente:
                aid = base_datos.guardar_alerta(sesion_id, tipo_alerta, tiempo_mala)
                notificaciones.enviar_alerta_postura(
                    tipo_alerta, tiempo_mala,
                    resultado.angulo_cuello, resultado.angulo_espalda,
                )
                if aid: base_datos.marcar_alerta_telegram(aid)

            # Sedentarismo
            for det in [d for d in [ausencia_p, ausencia_s] if d]:
                if det.debe_alertar_sedentarismo:
                    t_s = det.tiempo_inmovil_segundos
                    aid = base_datos.guardar_alerta(sesion_id, "Sedentarismo", t_s)
                    notificaciones.enviar_alerta_sedentarismo(t_s)
                    if aid: base_datos.marcar_alerta_telegram(aid)

            # ── Teclas ────────────────────────────────────────────────────
            tecla = cv2.waitKey(1) & 0xFF
            if tecla in (ord("q"), ord("Q"), 27):
                break
            elif tecla in (ord("s"), ord("S")):
                mostrar_esq = not mostrar_esq
            elif tecla in (ord("a"), ord("A")):
                mostrar_hud = not mostrar_hud
            elif tecla in (ord("t"), ord("T")):
                notificaciones.enviar_prueba()
            elif tecla in (ord("c"), ord("C")):
                # Calibración frontal desde debug
                ejecutar_calibracion_frontal(idx_p)

    except KeyboardInterrupt:
        logger.info("Debug interrumpido por usuario.")
    finally:
        dur = time.time() - inicio
        try:
            base_datos.cerrar_sesion(sesion_id, dur)
            notificaciones.enviar_resumen_sesion(
                base_datos.obtener_resumen_sesion(sesion_id))
        except Exception:
            pass
        cap_p.release()
        if cap_s: cap_s.release()
        detector_p.cerrar()
        if detector_s: detector_s.cerrar()
        cv2.destroyAllWindows()
        logger.info(f"Debug finalizado. Duración: {dur:.1f}s")


# ── Modo PRODUCCIÓN ───────────────────────────────────────────────────────────

def ejecutar_modo_produccion(indice_secundario=None) -> None:
    logger.info("MODO PRODUCCIÓN v4.5")

    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QTimer
    from core.bandeja import BandejaSistema

    app = QApplication.instance() or QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    monitor = MonitorSegundoPlano()
    bandeja = BandejaSistema()
    _pausado = [False]

    def toggle_pausa():
        _pausado[0] = not _pausado[0]
        if _pausado[0]:
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

    timer = QTimer()
    timer.timeout.connect(
        lambda: bandeja.actualizar_estado(
            getattr(monitor, "_ultimo_estado", "correcto")
        ) if not _pausado[0] else None
    )
    timer.start(3000)

    signal.signal(signal.SIGINT,  lambda s, f: salir_app())
    signal.signal(signal.SIGTERM, lambda s, f: salir_app())

    if not monitor.iniciar():
        bandeja.actualizar_estado("sin_camara")
    else:
        bandeja.notificar("Monitor de Postura",
                          "Monitoreando tu postura en segundo plano.")

    try:
        app.exec()
    except KeyboardInterrupt:
        salir_app()


# ── Argumentos ────────────────────────────────────────────────────────────────

def parsear_argumentos():
    p = argparse.ArgumentParser(description="Monitor de Postura v4.5")
    p.add_argument("--modo",     choices=["debug", "produccion"], default="produccion")
    p.add_argument("--camara",   type=int, default=0)
    p.add_argument("--camara2",  type=int, default=None)
    p.add_argument("--skip-onboarding", action="store_true")
    p.add_argument("--configurar", action="store_true")
    p.add_argument("--calibrar", action="store_true", help="Ejecuta calibración frontal y sale")
    return p.parse_args()


if __name__ == "__main__":
    args = parsear_argumentos()
    I18n.cargar()
    camara.indice_camara = args.camara

    # Modo calibración directa
    if args.calibrar:
        exito = ejecutar_calibracion_frontal(args.camara)
        sys.exit(0 if exito else 1)

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
