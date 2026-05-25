"""
Módulo de visualización HUD - v4
Adaptado a los nuevos nombres de umbrales y orientación.
"""

import time
import cv2
import numpy as np

from config.settings import ConfiguracionVisualizacion, UmbralesPostura
from core.analisis_postura import ResultadoAnalisis, EstadoPostura, AngulosPostura
from utils.logger import crear_logger

logger = crear_logger("visualizacion")


class HUDPostura:
    def __init__(self, config_vis: ConfiguracionVisualizacion, umbrales: UmbralesPostura):
        self.config = config_vis
        self.umbrales = umbrales
        self._tiempo_ultimo_frame = time.time()
        self._fps_actual = 0.0
        self._historial_fps = []
        self._contador_frames = 0

    def renderizar(self, frame: np.ndarray, resultado: ResultadoAnalisis, mostrar_angulos: bool = True) -> np.ndarray:
        self._actualizar_fps()
        self._contador_frames += 1
        frame = self._dibujar_panel_estado(frame, resultado)
        if mostrar_angulos:
            frame = self._dibujar_angulos(frame, resultado.angulos, resultado.orientacion)
        frame = self._dibujar_barra_tiempo(frame, resultado.tiempo_mala_postura_segundos)
        if resultado.alertas_activas:
            frame = self._dibujar_alertas(frame, resultado.alertas_activas)
        if self.config.mostrar_fps:
            frame = self._dibujar_fps(frame)
        frame = self._dibujar_leyenda_teclas(frame, mostrar_angulos)
        frame = self._dibujar_orientacion(frame, resultado.orientacion, getattr(resultado, 'alineado', True),
                                          getattr(resultado.angulos, 'lado_usado', None))
        return frame

    def _dibujar_panel_estado(self, frame: np.ndarray, resultado: ResultadoAnalisis) -> np.ndarray:
        alto, ancho = frame.shape[:2]
        color = self._color_para_estado(resultado.estado)
        overlay = frame.copy()
        cv2.rectangle(overlay, (0, 0), (420, 80), self.config.color_fondo_hud, -1)
        cv2.addWeighted(overlay, 0.7, frame, 0.3, 0, frame)
        cv2.rectangle(frame, (0, 0), (8, 80), color, -1)
        cv2.putText(frame, resultado.mensaje_estado, (18, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.65, color, 2, cv2.LINE_AA)
        cv2.putText(frame, f"Estado: {resultado.estado.value.upper()}", (18, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                    self.config.color_texto, 1, cv2.LINE_AA)
        return frame

    def _dibujar_angulos(self, frame: np.ndarray, angulos: AngulosPostura, orientacion: str) -> np.ndarray:
        if not angulos.datos_validos:
            return frame
        alto, ancho = frame.shape[:2]
        x = ancho - 220
        y = 20
        overlay = frame.copy()
        cv2.rectangle(overlay, (x - 10, 0), (ancho, 150), self.config.color_fondo_hud, -1)
        cv2.addWeighted(overlay, 0.7, frame, 0.3, 0, frame)
        cv2.putText(frame, "ANGULOS", (x, y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (180, 180, 180), 1, cv2.LINE_AA)
        y += 30

        if orientacion == "lateral":
            # Mostrar ángulos laterales
            if angulos.neck_inclination is not None:
                color = self._color_para_angulo_neck_lateral(angulos.neck_inclination)
                cv2.putText(frame, f"Cuello:  {angulos.neck_inclination:5.1f} deg", (x, y), cv2.FONT_HERSHEY_SIMPLEX, 0.55,
                            color, 1, cv2.LINE_AA)
                y += 28
            if angulos.torso_inclination is not None:
                color = self._color_para_angulo_torso_lateral(angulos.torso_inclination)
                cv2.putText(frame, f"Torso:   {angulos.torso_inclination:5.1f} deg", (x, y), cv2.FONT_HERSHEY_SIMPLEX, 0.55,
                            color, 1, cv2.LINE_AA)
                y += 28
        else:
            # Mostrar ángulos frontales
            if angulos.angulo_cuello is not None:
                color = self._color_para_angulo_cuello_frontal(angulos.angulo_cuello)
                cv2.putText(frame, f"Cuello:  {angulos.angulo_cuello:5.1f} deg", (x, y), cv2.FONT_HERSHEY_SIMPLEX, 0.55,
                            color, 1, cv2.LINE_AA)
                y += 28
            if angulos.angulo_espalda is not None:
                color = self._color_para_angulo_espalda_frontal(angulos.angulo_espalda)
                cv2.putText(frame, f"Espalda: {angulos.angulo_espalda:5.1f} deg", (x, y), cv2.FONT_HERSHEY_SIMPLEX, 0.55,
                            color, 1, cv2.LINE_AA)
                y += 28
            if angulos.inclinacion_tronco is not None:
                # Usar mismo criterio que espalda
                color = self._color_para_angulo_espalda_frontal(angulos.inclinacion_tronco)
                cv2.putText(frame, f"Tronco:  {angulos.inclinacion_tronco:5.1f} deg", (x, y), cv2.FONT_HERSHEY_SIMPLEX, 0.55,
                            color, 1, cv2.LINE_AA)
                y += 28
            if angulos.inclinacion_lateral is not None:
                color = self._color_para_inclinacion_lateral(angulos.inclinacion_lateral)
                cv2.putText(frame, f"Lateral: {angulos.inclinacion_lateral:5.1f} deg", (x, y), cv2.FONT_HERSHEY_SIMPLEX,
                            0.55, color, 1, cv2.LINE_AA)
                y += 28

        return frame

    def _dibujar_barra_tiempo(self, frame: np.ndarray, tiempo_mala: float) -> np.ndarray:
        if tiempo_mala <= 0:
            return frame
        max_tiempo = self.umbrales.segundos_antes_alerta
        alto, ancho = frame.shape[:2]
        y = alto - 25
        progreso = min(tiempo_mala / max_tiempo, 1.0)
        cv2.rectangle(frame, (10, y), (ancho - 10, y + 15), (40, 40, 40), -1)
        color = self.config.color_correcto if progreso < 0.5 else self.config.color_advertencia if progreso < 0.85 else self.config.color_incorrecto
        cv2.rectangle(frame, (10, y), (10 + int((ancho - 20) * progreso), y + 15), color, -1)
        cv2.putText(frame, f"Tiempo mala postura: {tiempo_mala:.0f}s / {max_tiempo}s", (10, y - 5),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (200, 200, 200), 1, cv2.LINE_AA)
        return frame

    def _dibujar_alertas(self, frame: np.ndarray, alertas: list) -> np.ndarray:
        alto, ancho = frame.shape[:2]
        alpha = 0.85 if (self._contador_frames // 15) % 2 == 0 else 0.4
        overlay = frame.copy()
        cv2.rectangle(overlay, (0, 0), (ancho - 1, alto - 1), self.config.color_incorrecto, 4)
        cv2.addWeighted(overlay, alpha, frame, 1 - alpha, 0, frame)
        y_base = alto - 60
        for i, alerta in enumerate(alertas[:3]):
            cv2.putText(frame, f"! {alerta.value}", (ancho // 2 - 150, y_base - i * 22), cv2.FONT_HERSHEY_SIMPLEX,
                        0.6, self.config.color_incorrecto, 2, cv2.LINE_AA)
        return frame

    def _dibujar_fps(self, frame: np.ndarray) -> np.ndarray:
        alto, ancho = frame.shape[:2]
        cv2.putText(frame, f"FPS: {self._fps_actual:.1f}", (ancho - 100, alto - 35), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                    (150, 150, 150), 1, cv2.LINE_AA)
        return frame

    def _dibujar_leyenda_teclas(self, frame: np.ndarray, angulos_on: bool) -> np.ndarray:
        alto, ancho = frame.shape[:2]
        teclas = [f"[Q] Salir", f"[S] Esqueleto", f"[A] Angulos: {'ON' if angulos_on else 'OFF'}", f"[T] Test Telegram"]
        overlay = frame.copy()
        cv2.rectangle(overlay, (0, alto - 22 * len(teclas) - 8), (190, alto), (20, 20, 20), -1)
        cv2.addWeighted(overlay, 0.6, frame, 0.4, 0, frame)
        for i, texto in enumerate(teclas):
            cv2.putText(frame, texto, (6, alto - 22 * (len(teclas) - i - 1) - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.42,
                        (180, 180, 180), 1, cv2.LINE_AA)
        return frame

    def _dibujar_orientacion(self, frame: np.ndarray, orientacion: str, alineado: bool = True, lado_usado: str = None) -> np.ndarray:
        alto, ancho = frame.shape[:2]
        texto = f"Modo: {orientacion.upper()}"
        if orientacion == "frontal":
            color = (0, 255, 0)
        elif orientacion == "lateral":
            color = (255, 165, 0)
        else:
            color = (255, 255, 0)
        cv2.putText(frame, texto, (ancho - 200, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)

        if orientacion == "lateral" and lado_usado:
            texto_lado = f"Lado: {lado_usado.upper()}"
            cv2.putText(frame, texto_lado, (ancho - 200, 55), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (200, 200, 200), 1)

        if orientacion == "lateral":
            if not alineado:
                ayuda = "Ajusta: hombros deben verse alineados"
                cv2.putText(frame, ayuda, (ancho - 400, 80), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 255), 1)
            else:
                ayuda = "Cámara alineada - Vista lateral correcta"
                cv2.putText(frame, ayuda, (ancho - 380, 80), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 0), 1)
        return frame

    def _actualizar_fps(self):
        ahora = time.time()
        delta = ahora - self._tiempo_ultimo_frame
        self._tiempo_ultimo_frame = ahora
        if delta > 0:
            fps = 1.0 / delta
            self._historial_fps.append(fps)
            if len(self._historial_fps) > 30:
                self._historial_fps.pop(0)
            self._fps_actual = sum(self._historial_fps) / len(self._historial_fps)

    def _color_para_estado(self, estado: EstadoPostura) -> tuple:
        return {EstadoPostura.CORRECTA: self.config.color_correcto,
                EstadoPostura.ADVERTENCIA: self.config.color_advertencia,
                EstadoPostura.INCORRECTA: self.config.color_incorrecto,
                EstadoPostura.SIN_DETECCION: (150, 150, 150)}.get(estado, self.config.color_texto)

    # -------------- Colores para ángulos frontales --------------
    def _color_para_angulo_cuello_frontal(self, angulo: float) -> tuple:
        if angulo <= self.umbrales.frontal_cuello_correcto_max:
            return self.config.color_correcto
        if angulo <= self.umbrales.frontal_cuello_advertencia:
            return self.config.color_advertencia
        return self.config.color_incorrecto

    def _color_para_angulo_espalda_frontal(self, angulo: float) -> tuple:
        # Para espalda, valores bajos son malos, pero usamos el mismo rango (0-15 verde, 15-25 amarillo, >25 rojo)
        if angulo <= self.umbrales.frontal_espalda_correcto_max:
            return self.config.color_correcto
        if angulo <= self.umbrales.frontal_espalda_advertencia:
            return self.config.color_advertencia
        return self.config.color_incorrecto

    def _color_para_inclinacion_lateral(self, angulo: float) -> tuple:
        if angulo <= self.umbrales.frontal_inclinacion_lateral_correcto_max:
            return self.config.color_correcto
        if angulo <= self.umbrales.frontal_inclinacion_lateral_advertencia:
            return self.config.color_advertencia
        return self.config.color_incorrecto

    # -------------- Colores para ángulos laterales --------------
    def _color_para_angulo_neck_lateral(self, angulo: float) -> tuple:
        if angulo <= self.umbrales.lateral_neck_correcto_max:
            return self.config.color_correcto
        if angulo <= self.umbrales.lateral_neck_advertencia:
            return self.config.color_advertencia
        return self.config.color_incorrecto

    def _color_para_angulo_torso_lateral(self, angulo: float) -> tuple:
        if angulo <= self.umbrales.lateral_torso_correcto_max:
            return self.config.color_correcto
        if angulo <= self.umbrales.lateral_torso_advertencia:
            return self.config.color_advertencia
        return self.config.color_incorrecto
