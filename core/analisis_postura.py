"""
Análisis de postura v4.2 — con clasificador Random Forest
==========================================================
CAMBIOS v4.2:
- Integración del ClasificadorRF (dataset Zenodo 14230872, 4794 muestras)
- El RF actúa como segunda capa de verificación sobre el sistema de ángulos
- Si el RF detecta tronco incorrecto con >70% de confianza, refuerza el estado
- El resultado RF se expone en ResultadoAnalisis para el HUD y la DB
- Retrocompatible: si los modelos no existen, sigue funcionando con ángulos
"""

import math
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from config.settings import UmbralesPostura
from core.deteccion_postura import PuntoLandmark, PuntoClave
from utils.logger import crear_logger

logger = crear_logger("analisis_postura")


# ---------------------------------------------------------------------------
# Enums y dataclasses (sin cambios respecto a v4.1)
# ---------------------------------------------------------------------------

class EstadoPostura(Enum):
    CORRECTA     = "correcta"
    ADVERTENCIA  = "advertencia"
    INCORRECTA   = "incorrecta"
    SIN_DETECCION = "sin_detección"


class TipoAlerta(Enum):
    CUELLO_ADELANTADO  = "Cuello inclinado hacia adelante"
    ESPALDA_ENCORVADA  = "Espalda encorvada"
    INCLINACION_TRONCO = "Tronco inclinado"
    ENCORVAMIENTO      = "Encorvamiento excesivo"
    INCLINACION_LATERAL = "Inclinación lateral de cabeza"
    PIERNAS_CRUZADAS   = "Piernas cruzadas"
    FATIGA_PROLONGADA  = "Mala postura prolongada"
    SEDENTARISMO       = "Sedentarismo: 30 min sin movimiento"


@dataclass
class AngulosPostura:
    angulo_cuello:           Optional[float] = None
    angulo_espalda:          Optional[float] = None
    angulo_encorvamiento:    Optional[float] = None
    inclinacion_tronco:      Optional[float] = None
    inclinacion_lateral:     Optional[float] = None
    neck_inclination:        Optional[float] = None
    torso_inclination:       Optional[float] = None
    piernas_cruzadas:        bool = False
    datos_validos:           bool = False
    lado_usado:              str  = "izquierdo"


@dataclass
class ResultadoAnalisis:
    estado:                       EstadoPostura = EstadoPostura.SIN_DETECCION
    angulos:                      AngulosPostura = field(default_factory=AngulosPostura)
    alertas_activas:              List[TipoAlerta] = field(default_factory=list)
    tiempo_mala_postura_segundos: float = 0.0
    tiempo_sin_cambio_segundos:   float = 0.0
    mensaje_estado:               str   = ""
    debe_alertar:                 bool  = False
    debe_alertar_sedentarismo:    bool  = False
    orientacion:                  str   = "frontal"
    alineado:                     bool  = True
    # ── Campos RF ──────────────────────────────────────────────────────────────
    rf_disponible:        bool  = False
    rf_tronco:            str   = ""   # TUP / TLF / TLB / TLL / TLR
    rf_piernas:           str   = ""   # LAP / LCL / LCR / LCS / LLL / LLR / LWA
    rf_confianza_tronco:  float = 0.0
    rf_confianza_piernas: float = 0.0
    rf_descripcion:       str   = ""   # texto para HUD


_FRAMES_CONFIRMACION_DEFAULT = 8

# ---------------------------------------------------------------------------
# Ruta de modelos: busca primero junto al ejecutable (instalado) y luego
# en la raíz del proyecto (desarrollo).
# ---------------------------------------------------------------------------
def _buscar_directorio_modelos() -> Path:
    import sys
    candidatos = []
    # Dentro del ejecutable PyInstaller
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        candidatos.append(base / "models")
        candidatos.append(base / "_internal" / "models")
    # Desarrollo: raíz del proyecto
    candidatos.append(Path(__file__).resolve().parent.parent / "models")
    for p in candidatos:
        if p.exists() and (p / "rf_upperbody.pkl").exists():
            return p
    return Path(__file__).resolve().parent.parent / "models"


# ---------------------------------------------------------------------------
# Clasificador RF (carga perezosa, singleton)
# ---------------------------------------------------------------------------

_clf_rf = None
_clf_rf_intentado = False


def _obtener_clasificador():
    global _clf_rf, _clf_rf_intentado
    if _clf_rf_intentado:
        return _clf_rf
    _clf_rf_intentado = True
    try:
        from core.clasificador_rf import ClasificadorRF
        dir_modelos = _buscar_directorio_modelos()
        _clf_rf = ClasificadorRF(dir_modelos=dir_modelos)
        if _clf_rf.disponible:
            logger.info(f"ClasificadorRF cargado desde {dir_modelos}")
        else:
            logger.warning(
                f"ClasificadorRF: modelos no encontrados en {dir_modelos}. "
                "Ejecuta: python entrenamiento_rf.py --csv data.csv --no-cv"
            )
    except Exception as e:
        logger.warning(f"ClasificadorRF no disponible: {e}")
        _clf_rf = None
    return _clf_rf


# ---------------------------------------------------------------------------
# Analizador principal
# ---------------------------------------------------------------------------

class AnalizadorPostura:

    def __init__(self, umbrales: UmbralesPostura, config_alertas=None):
        self.umbrales = umbrales
        self._inicio_mala_postura: Optional[float] = None
        self._frames_malos_consecutivos: int = 0
        self._frames_confirmacion: int = getattr(
            umbrales, "frames_confirmacion", _FRAMES_CONFIRMACION_DEFAULT
        )
        self._ultima_alerta: Dict[TipoAlerta, float] = {}
        self._ultimo_cambio_postura: float = time.time()
        self._ultima_postura_estado: str = ""
        self._orientacion_actual: str = "frontal"

        self._buffer_cuello    = deque(maxlen=10)
        self._buffer_espalda   = deque(maxlen=10)
        self._buffer_tronco    = deque(maxlen=10)
        self._buffer_lateral   = deque(maxlen=10)
        self._buffer_neck_lat  = deque(maxlen=10)
        self._buffer_torso_lat = deque(maxlen=10)

        # Pre-cargar el clasificador RF al instanciar (evita lag en primer frame)
        _obtener_clasificador()

    # ------------------------------------------------------------------
    # Método principal
    # ------------------------------------------------------------------

    def analizar(
        self,
        landmarks: Dict[int, PuntoLandmark],
        ancho_frame: int,
        alto_frame:  int,
    ) -> ResultadoAnalisis:

        if not landmarks:
            self._reiniciar_contador_mala_postura()
            return ResultadoAnalisis(
                estado=EstadoPostura.SIN_DETECCION,
                mensaje_estado="Sin detección",
                orientacion=self._orientacion_actual,
            )

        puntos_px = self._desnormalizar_landmarks(landmarks, ancho_frame, alto_frame)
        self._determinar_orientacion(puntos_px, ancho_frame, alto_frame)
        angulos = self._calcular_angulos(puntos_px, ancho_frame, alto_frame)

        if not angulos.datos_validos:
            return ResultadoAnalisis(
                estado=EstadoPostura.SIN_DETECCION,
                angulos=angulos,
                mensaje_estado="Puntos insuficientes",
                orientacion=self._orientacion_actual,
            )

        # ── Sistema angular (lógica original) ──────────────────────────────────
        estado, alertas = self._clasificar_postura(angulos)

        # ── Clasificador RF ────────────────────────────────────────────────────
        rf_disponible        = False
        rf_tronco            = ""
        rf_piernas           = ""
        rf_confianza_tronco  = 0.0
        rf_confianza_piernas = 0.0
        rf_descripcion       = ""

        clf = _obtener_clasificador()
        if clf and clf.disponible:
            try:
                res_rf = clf.clasificar(landmarks)
                rf_disponible        = True
                rf_tronco            = res_rf.postura_tronco.value
                rf_piernas           = res_rf.postura_piernas.value
                rf_confianza_tronco  = res_rf.confianza_tronco
                rf_confianza_piernas = res_rf.confianza_piernas
                rf_descripcion       = (
                    f"{res_rf.descripcion_tronco} | {res_rf.descripcion_piernas} "
                    f"({res_rf.confianza_tronco:.0%} / {res_rf.confianza_piernas:.0%})"
                )

                # Refuerzo: si RF dice tronco incorrecto con alta confianza
                # y el sistema angular aún no lo marcó, elevar estado
                tronco_incorrecto_rf = rf_tronco in ("TLF", "TLB", "TLL", "TLR")
                if (tronco_incorrecto_rf
                        and rf_confianza_tronco > 0.70
                        and estado == EstadoPostura.CORRECTA):
                    estado = EstadoPostura.ADVERTENCIA
                    alertas.append(TipoAlerta.INCLINACION_TRONCO)
                    logger.debug(
                        f"RF refuerza estado a ADVERTENCIA: {rf_tronco} "
                        f"({rf_confianza_tronco:.0%})"
                    )

                # Refuerzo: piernas cruzadas detectadas por RF
                if (rf_piernas not in ("LAP", "?", "")
                        and rf_confianza_piernas > 0.65
                        and not angulos.piernas_cruzadas):
                    if estado == EstadoPostura.CORRECTA:
                        estado = EstadoPostura.ADVERTENCIA
                    if TipoAlerta.PIERNAS_CRUZADAS not in alertas:
                        alertas.append(TipoAlerta.PIERNAS_CRUZADAS)

            except Exception as e:
                logger.debug(f"RF clasificar error: {e}")

        # ── Resto de la lógica (sin cambios) ───────────────────────────────────
        tiempo_mala        = self._actualizar_tiempo_mala_postura(estado)
        debe_alertar       = self._evaluar_emision_alerta(alertas, tiempo_mala)
        tiempo_sin_cambio  = self._actualizar_sedentarismo(estado, angulos)
        alerta_sedentarismo = self._verificar_sedentarismo(tiempo_sin_cambio)
        mensaje            = self._generar_mensaje(estado, angulos, tiempo_mala)
        alineado           = self._verificar_alineacion(puntos_px, ancho_frame)

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
            rf_disponible=rf_disponible,
            rf_tronco=rf_tronco,
            rf_piernas=rf_piernas,
            rf_confianza_tronco=rf_confianza_tronco,
            rf_confianza_piernas=rf_confianza_piernas,
            rf_descripcion=rf_descripcion,
        )

    # ------------------------------------------------------------------
    # Métodos internos (idénticos a v4.1)
    # ------------------------------------------------------------------

    def _desnormalizar_landmarks(self, landmarks, ancho, alto):
        return {
            indice: (int(p.x * ancho), int(p.y * alto))
            for indice, p in landmarks.items()
        }

    def _determinar_orientacion(self, puntos, ancho, alto):
        hombro_izq = puntos.get(PuntoClave.HOMBRO_IZQ)
        hombro_der = puntos.get(PuntoClave.HOMBRO_DER)
        cadera_izq = puntos.get(PuntoClave.CADERA_IZQ)
        cadera_der = puntos.get(PuntoClave.CADERA_DER)
        if hombro_izq and hombro_der and cadera_izq and cadera_der:
            ancho_hombros  = abs(hombro_izq[0] - hombro_der[0])
            h_centro_y     = (hombro_izq[1] + hombro_der[1]) / 2
            c_centro_y     = (cadera_izq[1]  + cadera_der[1])  / 2
            alto_torso     = abs(c_centro_y - h_centro_y)
            if alto_torso > 0:
                ratio = ancho_hombros / alto_torso
                if   ratio < self.umbrales.hombros_dist_lateral_max:
                    self._orientacion_actual = "lateral"
                elif ratio > self.umbrales.hombros_dist_frontal_min:
                    self._orientacion_actual = "frontal"

    def _calcular_angulos(self, puntos, ancho, alto) -> AngulosPostura:
        if self._orientacion_actual == "lateral":
            return self._calcular_angulos_lateral(puntos)
        return self._calcular_angulos_frontal(puntos, ancho, alto)

    def _suavizar(self, buffer: deque, valor: Optional[float]) -> Optional[float]:
        if valor is None:
            return None
        buffer.append(valor)
        return sum(buffer) / len(buffer)

    def _calcular_angulos_lateral(self, puntos) -> AngulosPostura:
        angulos = AngulosPostura()
        hombro_izq = puntos.get(PuntoClave.HOMBRO_IZQ)
        hombro_der = puntos.get(PuntoClave.HOMBRO_DER)
        if hombro_izq and hombro_der:
            centro_x = (hombro_izq[0] + hombro_der[0]) / 2
            lado = "izquierdo" if abs(hombro_izq[0]-centro_x) > abs(hombro_der[0]-centro_x) else "derecho"
        elif hombro_izq:
            lado = "izquierdo"
        elif hombro_der:
            lado = "derecho"
        else:
            return angulos
        angulos.lado_usado = lado
        if lado == "izquierdo":
            hombro = puntos.get(PuntoClave.HOMBRO_IZQ)
            oreja  = puntos.get(PuntoClave.OREJA_IZQ)
            cadera = puntos.get(PuntoClave.CADERA_IZQ)
        else:
            hombro = puntos.get(PuntoClave.HOMBRO_DER)
            oreja  = puntos.get(PuntoClave.OREJA_DER)
            cadera = puntos.get(PuntoClave.CADERA_DER)
        if hombro and oreja:
            dx, dy = oreja[0]-hombro[0], oreja[1]-hombro[1]
            if dy != 0:
                angulos.neck_inclination = self._suavizar(
                    self._buffer_neck_lat, math.degrees(math.atan2(abs(dx), abs(dy)))
                )
        if cadera and hombro:
            dx, dy = hombro[0]-cadera[0], hombro[1]-cadera[1]
            if dy != 0:
                angulos.torso_inclination = self._suavizar(
                    self._buffer_torso_lat, math.degrees(math.atan2(abs(dx), abs(dy)))
                )
        angulos.datos_validos = (
            angulos.neck_inclination is not None or angulos.torso_inclination is not None
        )
        return angulos

    def _calcular_angulos_frontal(self, puntos, ancho, alto) -> AngulosPostura:
        angulos = AngulosPostura()
        nariz       = puntos.get(PuntoClave.NARIZ)
        oreja_izq   = puntos.get(PuntoClave.OREJA_IZQ)
        oreja_der   = puntos.get(PuntoClave.OREJA_DER)
        hombro_izq  = puntos.get(PuntoClave.HOMBRO_IZQ)
        hombro_der  = puntos.get(PuntoClave.HOMBRO_DER)
        cadera_izq  = puntos.get(PuntoClave.CADERA_IZQ)
        cadera_der  = puntos.get(PuntoClave.CADERA_DER)
        rodilla_izq = puntos.get(PuntoClave.RODILLA_IZQ)
        rodilla_der = puntos.get(PuntoClave.RODILLA_DER)

        factor = self._calcular_factor_escala(hombro_izq, hombro_der, cadera_izq, cadera_der)

        if oreja_der and hombro_der:
            dx, dy = (oreja_der[0]-hombro_der[0])*factor, (oreja_der[1]-hombro_der[1])*factor
            if dy != 0:
                angulos.angulo_cuello = self._suavizar(
                    self._buffer_cuello, math.degrees(math.atan2(abs(dx), abs(dy)))
                )
        elif oreja_izq and hombro_izq:
            dx, dy = (oreja_izq[0]-hombro_izq[0])*factor, (oreja_izq[1]-hombro_izq[1])*factor
            if dy != 0:
                angulos.angulo_cuello = self._suavizar(
                    self._buffer_cuello, math.degrees(math.atan2(abs(dx), abs(dy)))
                )

        hombro_centro = self._punto_medio(hombro_izq, hombro_der)
        cadera_centro = self._punto_medio(cadera_izq, cadera_der)
        cuello_punto  = nariz if nariz else self._punto_medio(oreja_izq, oreja_der)

        if hombro_centro and cadera_centro and cuello_punto:
            v1 = (hombro_centro[0]-cadera_centro[0], (hombro_centro[1]-cadera_centro[1])*factor)
            v2 = (cuello_punto[0]-cadera_centro[0],  (cuello_punto[1]-cadera_centro[1])*factor)
            angulos.angulo_espalda = self._suavizar(self._buffer_espalda, self._angulo_entre_vectores(v1, v2))

        if hombro_centro and cadera_centro:
            dx, dy = (hombro_centro[0]-cadera_centro[0])*factor, (hombro_centro[1]-cadera_centro[1])*factor
            if dy != 0:
                angulos.inclinacion_tronco = self._suavizar(
                    self._buffer_tronco, math.degrees(math.atan2(abs(dx), abs(dy)))
                )

        rodilla_centro = self._punto_medio(rodilla_izq, rodilla_der)
        if hombro_centro and cadera_centro and rodilla_centro:
            v1 = (hombro_centro[0]-cadera_centro[0], (hombro_centro[1]-cadera_centro[1])*factor)
            v2 = (rodilla_centro[0]-cadera_centro[0], (rodilla_centro[1]-cadera_centro[1])*factor)
            angulos.angulo_encorvamiento = self._angulo_entre_vectores(v1, v2)

        if hombro_izq and hombro_der:
            diff_y = abs(hombro_izq[1]-hombro_der[1])
            diff_x = abs(hombro_izq[0]-hombro_der[0])
            if diff_x > 0:
                angulos.inclinacion_lateral = self._suavizar(
                    self._buffer_lateral, math.degrees(math.atan2(diff_y, diff_x))
                )

        if rodilla_izq and rodilla_der and hombro_izq and hombro_der:
            dist_rodillas = abs(rodilla_izq[0]-rodilla_der[0])
            dist_hombros  = abs(hombro_izq[0]-hombro_der[0])
            if dist_hombros > 0 and dist_rodillas < dist_hombros * 0.3:
                angulos.piernas_cruzadas = True

        angulos.datos_validos = (
            angulos.angulo_cuello is not None or angulos.angulo_espalda is not None
        )
        return angulos

    def _calcular_factor_escala(self, h_izq, h_der, c_izq, c_der) -> float:
        if h_izq and h_der and c_izq and c_der:
            h_y = (h_izq[1]+h_der[1]) / 2
            c_y = (c_izq[1]+c_der[1]) / 2
            alto = abs(c_y - h_y)
            if alto > 0:
                return 150.0 / alto
        return 1.0

    def _punto_medio(self, p1, p2):
        if p1 and p2:
            return ((p1[0]+p2[0])//2, (p1[1]+p2[1])//2)
        return p1 if p1 else p2

    def _angulo_entre_vectores(self, v1: Tuple, v2: Tuple) -> float:
        dot   = v1[0]*v2[0] + v1[1]*v2[1]
        norm1 = math.hypot(v1[0], v1[1])
        norm2 = math.hypot(v2[0], v2[1])
        if norm1 == 0 or norm2 == 0:
            return 180.0
        return math.degrees(math.acos(max(-1.0, min(1.0, dot/(norm1*norm2)))))

    def _clasificar_postura(self, angulos: AngulosPostura) -> Tuple[EstadoPostura, List[TipoAlerta]]:
        alertas = []
        estado  = EstadoPostura.CORRECTA

        if self._orientacion_actual == "lateral":
            if angulos.neck_inclination is not None:
                if   angulos.neck_inclination > self.umbrales.lateral_neck_advertencia:
                    alertas.append(TipoAlerta.CUELLO_ADELANTADO); estado = EstadoPostura.INCORRECTA
                elif angulos.neck_inclination > self.umbrales.lateral_neck_correcto_max:
                    estado = EstadoPostura.ADVERTENCIA
            if angulos.torso_inclination is not None:
                if   angulos.torso_inclination > self.umbrales.lateral_torso_advertencia:
                    alertas.append(TipoAlerta.INCLINACION_TRONCO); estado = EstadoPostura.INCORRECTA
                elif angulos.torso_inclination > self.umbrales.lateral_torso_correcto_max:
                    if estado != EstadoPostura.INCORRECTA: estado = EstadoPostura.ADVERTENCIA
        else:
            if angulos.angulo_cuello is not None:
                if   angulos.angulo_cuello > self.umbrales.frontal_cuello_advertencia:
                    alertas.append(TipoAlerta.CUELLO_ADELANTADO); estado = EstadoPostura.INCORRECTA
                elif angulos.angulo_cuello > self.umbrales.frontal_cuello_correcto_max:
                    if estado != EstadoPostura.INCORRECTA: estado = EstadoPostura.ADVERTENCIA
            if angulos.angulo_espalda is not None:
                if   angulos.angulo_espalda > self.umbrales.frontal_espalda_advertencia:
                    alertas.append(TipoAlerta.ESPALDA_ENCORVADA); estado = EstadoPostura.INCORRECTA
                elif angulos.angulo_espalda > self.umbrales.frontal_espalda_correcto_max:
                    if estado != EstadoPostura.INCORRECTA: estado = EstadoPostura.ADVERTENCIA
            if angulos.inclinacion_tronco is not None:
                if   angulos.inclinacion_tronco > self.umbrales.frontal_tronco_advertencia:
                    alertas.append(TipoAlerta.INCLINACION_TRONCO); estado = EstadoPostura.INCORRECTA
                elif angulos.inclinacion_tronco > self.umbrales.frontal_tronco_correcto_max:
                    if estado != EstadoPostura.INCORRECTA: estado = EstadoPostura.ADVERTENCIA
            if angulos.angulo_encorvamiento is not None:
                if   angulos.angulo_encorvamiento < self.umbrales.frontal_encorvamiento_advertencia_min:
                    alertas.append(TipoAlerta.ENCORVAMIENTO); estado = EstadoPostura.INCORRECTA
                elif angulos.angulo_encorvamiento < self.umbrales.frontal_encorvamiento_correcto_min:
                    if estado != EstadoPostura.INCORRECTA: estado = EstadoPostura.ADVERTENCIA
            if angulos.inclinacion_lateral is not None:
                if   angulos.inclinacion_lateral > self.umbrales.frontal_inclinacion_lateral_advertencia:
                    alertas.append(TipoAlerta.INCLINACION_LATERAL)
                    if estado != EstadoPostura.INCORRECTA: estado = EstadoPostura.ADVERTENCIA
                elif angulos.inclinacion_lateral > self.umbrales.frontal_inclinacion_lateral_correcto_max:
                    if estado == EstadoPostura.CORRECTA: estado = EstadoPostura.ADVERTENCIA
            if angulos.piernas_cruzadas:
                alertas.append(TipoAlerta.PIERNAS_CRUZADAS)
                if estado != EstadoPostura.INCORRECTA: estado = EstadoPostura.ADVERTENCIA

        return estado, alertas

    def _verificar_alineacion(self, puntos, ancho_frame) -> bool:
        if self._orientacion_actual != "lateral":
            return True
        h_i = puntos.get(PuntoClave.HOMBRO_IZQ)
        h_d = puntos.get(PuntoClave.HOMBRO_DER)
        if h_i and h_d:
            return abs(h_i[0]-h_d[0]) < ancho_frame * 0.3
        return True

    def _actualizar_tiempo_mala_postura(self, estado: EstadoPostura) -> float:
        es_mala = estado in (EstadoPostura.INCORRECTA, EstadoPostura.ADVERTENCIA)
        if not es_mala:
            if self._frames_malos_consecutivos > 0:
                logger.debug("Postura corregida, reset timer.")
            self._frames_malos_consecutivos = 0
            self._inicio_mala_postura = None
            return 0.0
        self._frames_malos_consecutivos += 1
        if self._frames_malos_consecutivos < self._frames_confirmacion:
            return 0.0
        ahora = time.time()
        if self._inicio_mala_postura is None:
            logger.debug(
                f"Inicio mala postura confirmada tras {self._frames_malos_consecutivos} frames: "
                f"{estado.value}"
            )
            self._inicio_mala_postura = ahora
        return ahora - self._inicio_mala_postura

    def _reiniciar_contador_mala_postura(self):
        self._inicio_mala_postura = None
        self._frames_malos_consecutivos = 0

    def _actualizar_sedentarismo(self, estado, angulos) -> float:
        if self._ultima_postura_estado != estado.value:
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
            if ahora - self._ultima_alerta.get(tipo, 0) >= self.umbrales.cooldown_alerta_segundos:
                self._ultima_alerta[tipo] = ahora
                logger.info(f"Alerta activada: {tipo.value}")
                return True
        return False

    def _generar_mensaje(self, estado: EstadoPostura, angulos: AngulosPostura, tiempo_mala: float) -> str:
        if estado == EstadoPostura.CORRECTA:     return "Postura correcta"
        if estado == EstadoPostura.SIN_DETECCION: return "Sin detección"
        partes = []
        if self._orientacion_actual == "lateral":
            if angulos.neck_inclination  and angulos.neck_inclination  > self.umbrales.lateral_neck_correcto_max:
                partes.append(f"Cuello: {angulos.neck_inclination:.1f}")
            if angulos.torso_inclination and angulos.torso_inclination > self.umbrales.lateral_torso_correcto_max:
                partes.append(f"Torso: {angulos.torso_inclination:.1f}")
        else:
            if angulos.angulo_cuello   and angulos.angulo_cuello   > self.umbrales.frontal_cuello_correcto_max:
                partes.append(f"Cuello: {angulos.angulo_cuello:.1f}")
            if angulos.angulo_espalda  and angulos.angulo_espalda  > self.umbrales.frontal_espalda_correcto_max:
                partes.append(f"Espalda: {angulos.angulo_espalda:.1f}")
            if angulos.inclinacion_tronco and angulos.inclinacion_tronco > self.umbrales.frontal_tronco_correcto_max:
                partes.append(f"Inclinacion: {angulos.inclinacion_tronco:.1f}")
        base     = "Advertencia" if estado == EstadoPostura.ADVERTENCIA else "Mala postura"
        detalles = " | ".join(partes) if partes else ""
        if tiempo_mala > 0:
            detalles += f" | {tiempo_mala:.0f}s"
        return f"{base}: {detalles}" if detalles else base
