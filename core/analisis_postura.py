"""
Análisis de postura v4.0 - MEJORADO
Detección frontal y lateral con biomecánica correcta.

CAMBIOS PRINCIPALES v4:
✓ Cálculos de ángulos más precisos usando vectores
✓ Normalización robusta por distancia (cámara-independiente)
✓ Umbrales basados en ergonomía biomecánica (ISO 11228)
✓ Mejor detección de orientación (frontal vs lateral)
✓ Suavizado con media móvil (10 frames)
✓ Manejo robusto de puntos perdidos
"""

import math
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Optional, Tuple, List

from config.settings import UmbralesPostura, ConfiguracionTelegram, camara as camara_config
from core.deteccion_postura import PuntoLandmark, PuntoClave
from utils.logger import crear_logger

logger = crear_logger("analisis_postura")


class EstadoPostura(Enum):
    CORRECTA = "correcta"
    ADVERTENCIA = "advertencia"
    INCORRECTA = "incorrecta"
    SIN_DETECCION = "sin_detección"


class TipoAlerta(Enum):
    CUELLO_ADELANTADO = "Cuello inclinado hacia adelante"
    ESPALDA_ENCORVADA = "Espalda encorvada"
    INCLINACION_TRONCO = "Tronco inclinado"
    ENCORVAMIENTO = "Encorvamiento excesivo"
    INCLINACION_LATERAL = "Inclinación lateral de cabeza"
    PIERNAS_CRUZADAS = "Piernas cruzadas"
    FATIGA_PROLONGADA = "Mala postura prolongada"
    SEDENTARISMO = "Sedentarismo: 30 min sin movimiento"


@dataclass
class AngulosPostura:
    # Frontal
    angulo_cuello: Optional[float] = None           # 0-30°
    angulo_espalda: Optional[float] = None          # 0-35°
    angulo_encorvamiento: Optional[float] = None    # 140-180°
    inclinacion_tronco: Optional[float] = None      # 0-35°
    inclinacion_lateral: Optional[float] = None     # 0-20°
    # Lateral
    neck_inclination: Optional[float] = None        # 0-40°
    torso_inclination: Optional[float] = None       # 0-45°
    piernas_cruzadas: bool = False
    datos_validos: bool = False
    lado_usado: str = "izquierdo"


@dataclass
class ResultadoAnalisis:
    estado: EstadoPostura = EstadoPostura.SIN_DETECCION
    angulos: AngulosPostura = field(default_factory=AngulosPostura)
    alertas_activas: List[TipoAlerta] = field(default_factory=list)
    tiempo_mala_postura_segundos: float = 0.0
    tiempo_sin_cambio_segundos: float = 0.0
    mensaje_estado: str = ""
    debe_alertar: bool = False
    debe_alertar_sedentarismo: bool = False
    orientacion: str = "frontal"
    alineado: bool = True


class AnalizadorPostura:
    def __init__(self, umbrales: UmbralesPostura, config_alertas=None):
        self.umbrales = umbrales
        # config_alertas se usa para tiempos, pero los incluimos en umbrales
        self._inicio_mala_postura: Optional[float] = None
        self._frames_incorrectos_consecutivos: int = 0
        self._ultima_alerta: Dict[TipoAlerta, float] = {}
        self._ultimo_cambio_postura: float = time.time()
        self._ultima_postura_estado: str = ""
        self._orientacion_actual: str = "frontal"
        
        # Filtros de media móvil (suavizado)
        self._buffer_cuello = deque(maxlen=10)
        self._buffer_espalda = deque(maxlen=10)
        self._buffer_tronco = deque(maxlen=10)
        self._buffer_lateral = deque(maxlen=10)
        self._buffer_neck_lat = deque(maxlen=10)
        self._buffer_torso_lat = deque(maxlen=10)

    def _suavizar(self, buffer: deque, valor: Optional[float]) -> Optional[float]:
        if valor is None:
            return None
        buffer.append(valor)
        return sum(buffer) / len(buffer)

    def analizar(
        self,
        landmarks: Dict[int, PuntoLandmark],
        ancho_frame: int,
        alto_frame: int,
    ) -> ResultadoAnalisis:
        if not landmarks:
            self._reiniciar_contador_mala_postura()
            return ResultadoAnalisis(
                estado=EstadoPostura.SIN_DETECCION,
                mensaje_estado="Sin detección",
                orientacion=self._orientacion_actual,
            )

        puntos_px = self._desnormalizar_landmarks(landmarks, ancho_frame, alto_frame)
        
        # Determinar orientación inmediatamente
        self._determinar_orientacion(puntos_px, ancho_frame, alto_frame)
        
        # Calcular ángulos según orientación
        angulos = self._calcular_angulos(puntos_px, ancho_frame, alto_frame)
        
        if not angulos.datos_validos:
            return ResultadoAnalisis(
                estado=EstadoPostura.SIN_DETECCION,
                angulos=angulos,
                mensaje_estado="Puntos insuficientes",
                orientacion=self._orientacion_actual,
            )

        # Clasificar postura
        estado, alertas = self._clasificar_postura(angulos)
        tiempo_mala = self._actualizar_tiempo_mala_postura(estado)
        debe_alertar = self._evaluar_emision_alerta(alertas, tiempo_mala)
        tiempo_sin_cambio = self._actualizar_sedentarismo(estado, angulos)
        alerta_sedentarismo = self._verificar_sedentarismo(tiempo_sin_cambio)
        mensaje = self._generar_mensaje(estado, angulos, tiempo_mala)
        alineado = self._verificar_alineacion(puntos_px, ancho_frame)

        return ResultadoAnalisis(
            estado=estado,
            angulos=angulos,
            alertas_activas=alertas,
            tiempo_mala_postura_segundos=tiempo_mala,
            tiempo_sin_cambio_segundos=tiempo_sin_cambio,
            mensaje_estado=mensaje,
            debe_alertar=debe_alertar,
            debe_alertar_sedentarismo=alerta_sedentarismo,
            orientacion=self._orientacion_actual,
            alineado=alineado,
        )

    def _desnormalizar_landmarks(self, landmarks, ancho, alto):
        return {indice: (int(p.x * ancho), int(p.y * alto)) for indice, p in landmarks.items()}

    def _determinar_orientacion(self, puntos, ancho, alto):
        """Determina si es frontal o lateral basado en relación ancho hombros / alto torso."""
        hombro_izq = puntos.get(PuntoClave.HOMBRO_IZQ)
        hombro_der = puntos.get(PuntoClave.HOMBRO_DER)
        cadera_izq = puntos.get(PuntoClave.CADERA_IZQ)
        cadera_der = puntos.get(PuntoClave.CADERA_DER)

        if hombro_izq and hombro_der and cadera_izq and cadera_der:
            ancho_hombros = abs(hombro_izq[0] - hombro_der[0])
            hombro_centro_y = (hombro_izq[1] + hombro_der[1]) / 2
            cadera_centro_y = (cadera_izq[1] + cadera_der[1]) / 2
            alto_torso = abs(cadera_centro_y - hombro_centro_y)
            if alto_torso > 0:
                ratio = ancho_hombros / alto_torso
                if ratio < self.umbrales.hombros_dist_lateral_max:
                    self._orientacion_actual = "lateral"
                elif ratio > self.umbrales.hombros_dist_frontal_min:
                    self._orientacion_actual = "frontal"
                # Si está en zona intermedia, mantener la anterior

    def _calcular_angulos(self, puntos, ancho, alto) -> AngulosPostura:
        if self._orientacion_actual == "lateral":
            return self._calcular_angulos_lateral(puntos)
        else:
            return self._calcular_angulos_frontal(puntos, ancho, alto)

    # ---------- LATERAL ----------
    def _calcular_angulos_lateral(self, puntos) -> AngulosPostura:
        angulos = AngulosPostura()
        
        # Seleccionar el lado más visible
        hombro_izq = puntos.get(PuntoClave.HOMBRO_IZQ)
        hombro_der = puntos.get(PuntoClave.HOMBRO_DER)
        
        if hombro_izq and hombro_der:
            # Elegir el hombro más cerca del borde (más visible)
            centro_x = (hombro_izq[0] + hombro_der[0]) / 2
            dist_izq = abs(hombro_izq[0] - centro_x)
            dist_der = abs(hombro_der[0] - centro_x)
            lado = "izquierdo" if dist_izq > dist_der else "derecho"
        elif hombro_izq:
            lado = "izquierdo"
        elif hombro_der:
            lado = "derecho"
        else:
            angulos.datos_validos = False
            return angulos

        angulos.lado_usado = lado
        if lado == "izquierdo":
            hombro = puntos.get(PuntoClave.HOMBRO_IZQ)
            oreja = puntos.get(PuntoClave.OREJA_IZQ)
            cadera = puntos.get(PuntoClave.CADERA_IZQ)
        else:
            hombro = puntos.get(PuntoClave.HOMBRO_DER)
            oreja = puntos.get(PuntoClave.OREJA_DER)
            cadera = puntos.get(PuntoClave.CADERA_DER)

        # Inclinación del cuello (ángulo entre hombro-oreja y vertical)
        if hombro and oreja:
            dx = oreja[0] - hombro[0]
            dy = oreja[1] - hombro[1]
            if dy != 0:
                raw_neck = math.degrees(math.atan2(abs(dx), abs(dy)))
                angulos.neck_inclination = self._suavizar(self._buffer_neck_lat, raw_neck)

        # Inclinación del torso (ángulo entre cadera-hombro y vertical)
        if cadera and hombro:
            dx = hombro[0] - cadera[0]
            dy = hombro[1] - cadera[1]
            if dy != 0:
                raw_torso = math.degrees(math.atan2(abs(dx), abs(dy)))
                angulos.torso_inclination = self._suavizar(self._buffer_torso_lat, raw_torso)

        angulos.datos_validos = angulos.neck_inclination is not None or angulos.torso_inclination is not None
        return angulos

    # ---------- FRONTAL (con normalización por distancia) ----------
    def _calcular_angulos_frontal(self, puntos, ancho, alto) -> AngulosPostura:
        angulos = AngulosPostura()
        
        # Puntos necesarios
        nariz = puntos.get(PuntoClave.NARIZ)
        oreja_izq = puntos.get(PuntoClave.OREJA_IZQ)
        oreja_der = puntos.get(PuntoClave.OREJA_DER)
        hombro_izq = puntos.get(PuntoClave.HOMBRO_IZQ)
        hombro_der = puntos.get(PuntoClave.HOMBRO_DER)
        cadera_izq = puntos.get(PuntoClave.CADERA_IZQ)
        cadera_der = puntos.get(PuntoClave.CADERA_DER)
        rodilla_izq = puntos.get(PuntoClave.RODILLA_IZQ)
        rodilla_der = puntos.get(PuntoClave.RODILLA_DER)

        # Factor de escala: normaliza la altura del torso a 150 píxeles (cámara-independiente)
        factor_escala = self._calcular_factor_escala(hombro_izq, hombro_der, cadera_izq, cadera_der)

        # ---- Cuello ----
        if oreja_der and hombro_der:
            dx = (oreja_der[0] - hombro_der[0]) * factor_escala
            dy = (oreja_der[1] - hombro_der[1]) * factor_escala
            if dy != 0:
                raw = math.degrees(math.atan2(abs(dx), abs(dy)))
                angulos.angulo_cuello = self._suavizar(self._buffer_cuello, raw)
        elif oreja_izq and hombro_izq:
            dx = (oreja_izq[0] - hombro_izq[0]) * factor_escala
            dy = (oreja_izq[1] - hombro_izq[1]) * factor_escala
            if dy != 0:
                raw = math.degrees(math.atan2(abs(dx), abs(dy)))
                angulos.angulo_cuello = self._suavizar(self._buffer_cuello, raw)

        # Puntos medios
        hombro_centro = self._punto_medio(hombro_izq, hombro_der)
        cadera_centro = self._punto_medio(cadera_izq, cadera_der)
        cuello_punto = nariz if nariz else self._punto_medio(oreja_izq, oreja_der)

        # ---- Espalda (ángulo entre vectores hombro-cadera y cuello-cadera) ----
        if hombro_centro and cadera_centro and cuello_punto:
            v1 = (
                hombro_centro[0] - cadera_centro[0],
                (hombro_centro[1] - cadera_centro[1]) * factor_escala,
            )
            v2 = (
                cuello_punto[0] - cadera_centro[0],
                (cuello_punto[1] - cadera_centro[1]) * factor_escala,
            )
            raw = self._angulo_entre_vectores(v1, v2)
            angulos.angulo_espalda = self._suavizar(self._buffer_espalda, raw)

        # ---- Tronco (inclinación vertical del eje hombro-cadera) ----
        if hombro_centro and cadera_centro:
            dx = (hombro_centro[0] - cadera_centro[0]) * factor_escala
            dy = (hombro_centro[1] - cadera_centro[1]) * factor_escala
            if dy != 0:
                raw = math.degrees(math.atan2(abs(dx), abs(dy)))
                angulos.inclinacion_tronco = self._suavizar(self._buffer_tronco, raw)

        # ---- Encorvamiento (ángulo hombro-cadera-rodilla) ----
        rodilla_centro = self._punto_medio(rodilla_izq, rodilla_der)
        if hombro_centro and cadera_centro and rodilla_centro:
            v1 = (
                hombro_centro[0] - cadera_centro[0],
                (hombro_centro[1] - cadera_centro[1]) * factor_escala,
            )
            v2 = (
                rodilla_centro[0] - cadera_centro[0],
                (rodilla_centro[1] - cadera_centro[1]) * factor_escala,
            )
            angulos.angulo_encorvamiento = self._angulo_entre_vectores(v1, v2)

        # ---- Inclinación lateral (diferencia de altura entre hombros) ----
        if hombro_izq and hombro_der:
            diff_y = abs(hombro_izq[1] - hombro_der[1])
            diff_x = abs(hombro_izq[0] - hombro_der[0])
            if diff_x > 0:
                raw = math.degrees(math.atan2(diff_y, diff_x))
                angulos.inclinacion_lateral = self._suavizar(self._buffer_lateral, raw)

        # ---- Piernas cruzadas (heurística) ----
        if rodilla_izq and rodilla_der and hombro_izq and hombro_der:
            dist_rodillas = abs(rodilla_izq[0] - rodilla_der[0])
            dist_hombros = abs(hombro_izq[0] - hombro_der[0])
            if dist_hombros > 0 and dist_rodillas < dist_hombros * 0.3:
                angulos.piernas_cruzadas = True

        angulos.datos_validos = angulos.angulo_cuello is not None or angulos.angulo_espalda is not None
        return angulos

    def _calcular_factor_escala(self, h_izq, h_der, c_izq, c_der) -> float:
        """Normaliza la altura del torso a 150 píxeles (independiente de distancia)."""
        if h_izq and h_der and c_izq and c_der:
            h_centro_y = (h_izq[1] + h_der[1]) / 2
            c_centro_y = (c_izq[1] + c_der[1]) / 2
            alto_torso = abs(c_centro_y - h_centro_y)
            if alto_torso > 0:
                return 150.0 / alto_torso
        return 1.0

    def _punto_medio(self, p1, p2):
        if p1 and p2:
            return ((p1[0] + p2[0]) // 2, (p1[1] + p2[1]) // 2)
        return p1 if p1 else p2

    def _angulo_entre_vectores(self, v1: Tuple[float, float], v2: Tuple[float, float]) -> float:
        """Calcula ángulo entre vectores usando producto escalar (resultado en grados)."""
        dot = v1[0] * v2[0] + v1[1] * v2[1]
        norm1 = math.hypot(v1[0], v1[1])
        norm2 = math.hypot(v2[0], v2[1])
        if norm1 == 0 or norm2 == 0:
            return 180.0
        cos_ang = dot / (norm1 * norm2)
        cos_ang = max(-1.0, min(1.0, cos_ang))
        return math.degrees(math.acos(cos_ang))

    def _clasificar_postura(self, angulos: AngulosPostura) -> Tuple[EstadoPostura, List[TipoAlerta]]:
        alertas = []
        estado = EstadoPostura.CORRECTA

        if self._orientacion_actual == "lateral":
            # ----- LATERAL -----
            # Cuello
            if angulos.neck_inclination is not None:
                if angulos.neck_inclination > self.umbrales.lateral_neck_advertencia:
                    alertas.append(TipoAlerta.CUELLO_ADELANTADO)
                    estado = EstadoPostura.INCORRECTA
                elif angulos.neck_inclination > self.umbrales.lateral_neck_correcto_max:
                    estado = EstadoPostura.ADVERTENCIA
            # Torso
            if angulos.torso_inclination is not None:
                if angulos.torso_inclination > self.umbrales.lateral_torso_advertencia:
                    alertas.append(TipoAlerta.INCLINACION_TRONCO)
                    estado = EstadoPostura.INCORRECTA
                elif angulos.torso_inclination > self.umbrales.lateral_torso_correcto_max:
                    if estado != EstadoPostura.INCORRECTA:
                        estado = EstadoPostura.ADVERTENCIA
        else:
            # ----- FRONTAL (umbrales biomecánicos) -----
            # Cuello
            if angulos.angulo_cuello is not None:
                if angulos.angulo_cuello > self.umbrales.frontal_cuello_advertencia:
                    alertas.append(TipoAlerta.CUELLO_ADELANTADO)
                    estado = EstadoPostura.INCORRECTA
                elif angulos.angulo_cuello > self.umbrales.frontal_cuello_correcto_max:
                    if estado != EstadoPostura.INCORRECTA:
                        estado = EstadoPostura.ADVERTENCIA
            # Espalda
            if angulos.angulo_espalda is not None:
                if angulos.angulo_espalda > self.umbrales.frontal_espalda_advertencia:
                    alertas.append(TipoAlerta.ESPALDA_ENCORVADA)
                    estado = EstadoPostura.INCORRECTA
                elif angulos.angulo_espalda > self.umbrales.frontal_espalda_correcto_max:
                    if estado != EstadoPostura.INCORRECTA:
                        estado = EstadoPostura.ADVERTENCIA
            # Tronco (similar a espalda)
            if angulos.inclinacion_tronco is not None:
                if angulos.inclinacion_tronco > self.umbrales.frontal_tronco_advertencia:
                    alertas.append(TipoAlerta.INCLINACION_TRONCO)
                    estado = EstadoPostura.INCORRECTA
                elif angulos.inclinacion_tronco > self.umbrales.frontal_tronco_correcto_max:
                    if estado != EstadoPostura.INCORRECTA:
                        estado = EstadoPostura.ADVERTENCIA
            # Encorvamiento
            if angulos.angulo_encorvamiento is not None:
                if angulos.angulo_encorvamiento < self.umbrales.frontal_encorvamiento_advertencia_min:
                    alertas.append(TipoAlerta.ENCORVAMIENTO)
                    estado = EstadoPostura.INCORRECTA
                elif angulos.angulo_encorvamiento < self.umbrales.frontal_encorvamiento_correcto_min:
                    if estado != EstadoPostura.INCORRECTA:
                        estado = EstadoPostura.ADVERTENCIA
            # Inclinación lateral
            if angulos.inclinacion_lateral is not None:
                if angulos.inclinacion_lateral > self.umbrales.frontal_inclinacion_lateral_advertencia:
                    alertas.append(TipoAlerta.INCLINACION_LATERAL)
                    if estado != EstadoPostura.INCORRECTA:
                        estado = EstadoPostura.ADVERTENCIA
                elif angulos.inclinacion_lateral > self.umbrales.frontal_inclinacion_lateral_correcto_max:
                    if estado == EstadoPostura.CORRECTA:
                        estado = EstadoPostura.ADVERTENCIA
            # Piernas cruzadas
            if angulos.piernas_cruzadas:
                alertas.append(TipoAlerta.PIERNAS_CRUZADAS)
                if estado != EstadoPostura.INCORRECTA:
                    estado = EstadoPostura.ADVERTENCIA

        return estado, alertas

    def _verificar_alineacion(self, puntos, ancho_frame) -> bool:
        """Para vista lateral, verifica que los hombros estén bien alineados."""
        if self._orientacion_actual != "lateral":
            return True
        hombro_izq = puntos.get(PuntoClave.HOMBRO_IZQ)
        hombro_der = puntos.get(PuntoClave.HOMBRO_DER)
        if hombro_izq and hombro_der:
            ancho_hombros = abs(hombro_izq[0] - hombro_der[0])
            return ancho_hombros < ancho_frame * 0.3
        return True

    def _actualizar_tiempo_mala_postura(self, estado: EstadoPostura) -> float:
        es_mala = estado in (EstadoPostura.INCORRECTA, EstadoPostura.ADVERTENCIA)
        if es_mala:
            self._frames_incorrectos_consecutivos += 1
        else:
            self._frames_incorrectos_consecutivos = 0
            self._inicio_mala_postura = None
            return 0.0

        if self._frames_incorrectos_consecutivos < self.umbrales.frames_confirmacion:
            return 0.0

        ahora = time.time()
        if self._inicio_mala_postura is None:
            self._inicio_mala_postura = ahora
        return ahora - self._inicio_mala_postura

    def _reiniciar_contador_mala_postura(self):
        self._inicio_mala_postura = None
        self._frames_incorrectos_consecutivos = 0

    def _actualizar_sedentarismo(self, estado, angulos) -> float:
        cambio = self._ultima_postura_estado != estado.value
        if cambio:
            self._ultimo_cambio_postura = time.time()
            self._ultima_postura_estado = estado.value
        return time.time() - self._ultimo_cambio_postura

    def _verificar_sedentarismo(self, tiempo_sin_cambio: float) -> bool:
        return tiempo_sin_cambio > self.umbrales.tiempo_sedentarismo_minutos * 60

    def _evaluar_emision_alerta(self, alertas: List[TipoAlerta], tiempo_mala: float) -> bool:
        if not alertas or tiempo_mala < self.umbrales.segundos_antes_alerta:
            return False
        ahora = time.time()
        for tipo in alertas:
            ultima = self._ultima_alerta.get(tipo, 0)
            if ahora - ultima >= self.umbrales.cooldown_alerta_segundos:
                self._ultima_alerta[tipo] = ahora
                logger.info(f"Alerta activada: {tipo.value}")
                return True
        return False

    def _generar_mensaje(self, estado: EstadoPostura, angulos: AngulosPostura, tiempo_mala: float) -> str:
        if estado == EstadoPostura.CORRECTA:
            return "✓ Postura correcta"
        if estado == EstadoPostura.SIN_DETECCION:
            return "Sin detección"

        partes = []
        if self._orientacion_actual == "lateral":
            if angulos.neck_inclination and angulos.neck_inclination > self.umbrales.lateral_neck_correcto_max:
                partes.append(f"Cuello: {angulos.neck_inclination:.1f}°")
            if angulos.torso_inclination and angulos.torso_inclination > self.umbrales.lateral_torso_correcto_max:
                partes.append(f"Torso: {angulos.torso_inclination:.1f}°")
        else:
            if angulos.angulo_cuello and angulos.angulo_cuello > self.umbrales.frontal_cuello_correcto_max:
                partes.append(f"Cuello: {angulos.angulo_cuello:.1f}°")
            if angulos.angulo_espalda and angulos.angulo_espalda > self.umbrales.frontal_espalda_correcto_max:
                partes.append(f"Espalda: {angulos.angulo_espalda:.1f}°")
            if angulos.inclinacion_tronco and angulos.inclinacion_tronco > self.umbrales.frontal_tronco_correcto_max:
                partes.append(f"Inclinación: {angulos.inclinacion_tronco:.1f}°")

        base = "⚠ Advertencia" if estado == EstadoPostura.ADVERTENCIA else "✗ Mala postura"
        detalles = " | ".join(partes) if partes else ""
        if tiempo_mala > 0:
            detalles += f" | {tiempo_mala:.0f}s"
        return f"{base}: {detalles}" if detalles else base
