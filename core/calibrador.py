"""
Calibrador de postura base — v4.4
Captura la postura correcta del usuario y calcula factores de escala
personalizados para distancia y tamaño corporal.
"""

import json
import time
import numpy as np
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional, List

from utils.logger import crear_logger
logger = crear_logger("calibrador")


@dataclass
class PerfilCorporal:
    """Medidas corporales del usuario capturadas en calibración."""
    # Escala corporal (distancias normalizadas en el frame)
    altura_torso: float = 0.0        # distancia hombro-cadera
    ancho_hombros: float = 0.0       # distancia hombro_izq - hombro_der
    distancia_oido_hombro: float = 0.0  # longitud cuello

    # Ángulos base (postura correcta del usuario)
    neck_base_deg: float = 0.0       # ángulo cuello en postura correcta
    torso_base_deg: float = 0.0      # ángulo torso en postura correcta
    encorvamiento_base_deg: float = 0.0
    inclinacion_lateral_base: float = 0.0

    # Distancia estimada a la cámara (relativa)
    factor_distancia: float = 1.0    # >1 lejos, <1 cerca

    # Metadatos
    vista: str = "frontal"           # frontal | lateral
    timestamp: float = 0.0
    frames_usados: int = 0


@dataclass
class UmbralesPersonalizados:
    """Umbrales calculados a partir del perfil corporal del usuario."""
    # Posturas 1-4 (lateral)
    encorvamiento_alerta: float = 150.0
    neck_flexion_alerta: float = 30.0
    tronco_adelante_alerta: float = 0.0
    tronco_atras_alerta: float = -0.05

    # Posturas 5-7 (frontal/lateral)
    tronco_vertical_alerta: float = 20.0
    inclinacion_lateral_tronco: float = 12.0
    inclinacion_lateral_cuello: float = 15.0

    # Posturas 8-9 (frontal)
    brazos_cruzados_dist: float = 0.30
    piernas_cruzadas_dist: float = 0.05

    # Postura 10
    sedentarismo_segundos: int = 1800  # 30 min


class Calibrador:
    """
    Captura N frames de postura correcta y genera un perfil corporal
    con umbrales relativos personalizados.
    """

    FRAMES_REQUERIDOS = 90   # ~3 segundos a 30 FPS
    ARCHIVO_PERFIL = "perfil_corporal.json"

    def __init__(self):
        from config.settings import CONFIG_DIR
        self._ruta = CONFIG_DIR / self.ARCHIVO_PERFIL
        self._frames_buffer: List[dict] = []
        self._calibrando = False
        self._inicio = 0.0

    # ── Calibración ───────────────────────────────────────────────────────────

    def iniciar(self):
        self._frames_buffer = []
        self._calibrando = True
        self._inicio = time.time()
        logger.info("Calibración iniciada. Mantén postura correcta.")

    def agregar_frame(self, landmarks: dict, vista: str = "frontal") -> float:
        """
        Agrega un frame al buffer. Devuelve progreso 0.0-1.0.
        landmarks: dict con índices MediaPipe → (x, y, z, visibility)
        """
        if not self._calibrando or not landmarks:
            return 0.0

        datos = self._extraer_medidas(landmarks, vista)
        if datos:
            self._frames_buffer.append(datos)

        return min(len(self._frames_buffer) / self.FRAMES_REQUERIDOS, 1.0)

    def finalizar(self, vista: str = "frontal") -> Optional[PerfilCorporal]:
        """Procesa el buffer y genera el perfil corporal."""
        self._calibrando = False
        if len(self._frames_buffer) < 30:
            logger.warning("Pocos frames para calibrar.")
            return None

        perfil = self._calcular_perfil(vista)
        self._guardar(perfil)
        logger.info(f"Calibración completada. Frames: {perfil.frames_usados}")
        return perfil

    # ── Extracción de medidas por frame ──────────────────────────────────────

    def _extraer_medidas(self, lm: dict, vista: str) -> Optional[dict]:
        """Extrae medidas biomecánicas de un frame."""
        try:
            # Landmarks clave
            h_izq  = np.array(lm.get(11, [0,0,0])[:2])  # hombro izq
            h_der  = np.array(lm.get(12, [0,0,0])[:2])  # hombro der
            c_izq  = np.array(lm.get(23, [0,0,0])[:2])  # cadera izq
            c_der  = np.array(lm.get(24, [0,0,0])[:2])  # cadera der
            o_izq  = np.array(lm.get(7,  [0,0,0])[:2])  # oído izq
            o_der  = np.array(lm.get(8,  [0,0,0])[:2])  # oído der
            nariz  = np.array(lm.get(0,  [0,0,0])[:2])  # nariz

            # Verificar visibilidad mínima
            if any(np.all(p == 0) for p in [h_izq, h_der, c_izq, c_der]):
                return None

            hombro_medio = (h_izq + h_der) / 2
            cadera_medio = (c_izq + c_der) / 2
            oido_medio   = (o_izq + o_der) / 2

            # Medidas de escala corporal
            altura_torso       = float(np.linalg.norm(hombro_medio - cadera_medio))
            ancho_hombros      = float(np.linalg.norm(h_izq - h_der))
            dist_oido_hombro   = float(np.linalg.norm(oido_medio - hombro_medio))

            # Ángulo de encorvamiento (postura 1)
            vec_ab = hombro_medio - cadera_medio
            vec_bc = oido_medio - hombro_medio
            cos_ang = np.dot(vec_ab, vec_bc) / (
                np.linalg.norm(vec_ab) * np.linalg.norm(vec_bc) + 1e-6
            )
            enc_deg = float(np.degrees(np.arccos(np.clip(cos_ang, -1, 1))))

            # Ángulo cuello (postura 2) — vector oído-hombro vs eje vertical
            vec_cuello = oido_medio - hombro_medio
            eje_v = np.array([0, -1])
            cos_n = np.dot(vec_cuello, eje_v) / (np.linalg.norm(vec_cuello) + 1e-6)
            neck_deg = float(np.degrees(np.arccos(np.clip(cos_n, -1, 1))))

            # Ángulo torso vs vertical (postura 5)
            vec_torso = hombro_medio - cadera_medio
            cos_t = np.dot(vec_torso, eje_v) / (np.linalg.norm(vec_torso) + 1e-6)
            torso_deg = float(np.degrees(np.arccos(np.clip(cos_t, -1, 1))))

            # Inclinación lateral (postura 6)
            inc_lat = float(np.degrees(np.arctan2(
                h_der[1] - h_izq[1], h_der[0] - h_izq[0]
            )))

            return {
                "altura_torso": altura_torso,
                "ancho_hombros": ancho_hombros,
                "dist_oido_hombro": dist_oido_hombro,
                "enc_deg": enc_deg,
                "neck_deg": neck_deg,
                "torso_deg": torso_deg,
                "inc_lat": inc_lat,
                "vista": vista,
            }
        except Exception as e:
            logger.debug(f"Frame inválido: {e}")
            return None

    # ── Cálculo del perfil ────────────────────────────────────────────────────

    def _calcular_perfil(self, vista: str) -> PerfilCorporal:
        """Promedia los frames del buffer eliminando outliers (IQR)."""
        def mediana_robusta(valores):
            arr = np.array(valores)
            q1, q3 = np.percentile(arr, [25, 75])
            iqr = q3 - q1
            filtrado = arr[(arr >= q1 - 1.5*iqr) & (arr <= q3 + 1.5*iqr)]
            return float(np.mean(filtrado)) if len(filtrado) > 0 else float(np.mean(arr))

        keys = ["altura_torso","ancho_hombros","dist_oido_hombro",
                "enc_deg","neck_deg","torso_deg","inc_lat"]
        vals = {k: [f[k] for f in self._frames_buffer if k in f] for k in keys}

        # Factor de distancia: relación entre altura torso del usuario
        # y una referencia estándar (0.35 = usuario a ~60cm de cámara típica)
        REFERENCIA_TORSO = 0.35
        altura_media = mediana_robusta(vals["altura_torso"])
        factor_dist  = REFERENCIA_TORSO / (altura_media + 1e-6)

        return PerfilCorporal(
            altura_torso           = altura_media,
            ancho_hombros          = mediana_robusta(vals["ancho_hombros"]),
            distancia_oido_hombro  = mediana_robusta(vals["dist_oido_hombro"]),
            encorvamiento_base_deg = mediana_robusta(vals["enc_deg"]),
            neck_base_deg          = mediana_robusta(vals["neck_deg"]),
            torso_base_deg         = mediana_robusta(vals["torso_deg"]),
            inclinacion_lateral_base = mediana_robusta(vals["inc_lat"]),
            factor_distancia       = factor_dist,
            vista                  = vista,
            timestamp              = time.time(),
            frames_usados          = len(self._frames_buffer),
        )

    # ── Umbrales personalizados ───────────────────────────────────────────────

    def calcular_umbrales(self, perfil: PerfilCorporal) -> UmbralesPersonalizados:
        """
        Genera umbrales relativos al perfil corporal del usuario.
        Los márgenes están basados en la bibliografía citada.
        """
        u = UmbralesPersonalizados()

        # Escalar umbrales por factor de distancia
        f = np.clip(perfil.factor_distancia, 0.5, 2.0)

        # Postura 1: encorvamiento — umbral relativo a su ángulo base
        u.encorvamiento_alerta = max(
            130.0, perfil.encorvamiento_base_deg - 20.0
        )

        # Postura 2: flexión cervical — margen de 15° sobre su base
        u.neck_flexion_alerta = perfil.neck_base_deg + 15.0

        # Posturas 3/4: tronco adelante/atrás — escalar por distancia
        u.tronco_adelante_alerta =  0.03 * f
        u.tronco_atras_alerta    = -0.08 * f

        # Postura 5: tronco > 20° — relativo a su base
        u.tronco_vertical_alerta = perfil.torso_base_deg + 15.0

        # Postura 6/7: inclinación lateral — margen sobre su base
        u.inclinacion_lateral_tronco = abs(perfil.inclinacion_lateral_base) + 12.0
        u.inclinacion_lateral_cuello = 15.0

        # Posturas 8/9: escalar por ancho corporal del usuario
        u.brazos_cruzados_dist  = perfil.ancho_hombros * 0.8
        u.piernas_cruzadas_dist = perfil.ancho_hombros * 0.15

        logger.info(
            f"Umbrales calculados para usuario "
            f"(torso={perfil.altura_torso:.3f}, dist_factor={perfil.factor_distancia:.2f})"
        )
        return u

    # ── Persistencia ──────────────────────────────────────────────────────────

    def _guardar(self, perfil: PerfilCorporal):
        self._ruta.parent.mkdir(parents=True, exist_ok=True)
        self._ruta.write_text(
            json.dumps(asdict(perfil), indent=2), encoding="utf-8"
        )
        logger.info(f"Perfil guardado: {self._ruta}")

    def cargar(self) -> Optional[PerfilCorporal]:
        if not self._ruta.exists():
            return None
        try:
            data = json.loads(self._ruta.read_text("utf-8"))
            return PerfilCorporal(**data)
        except Exception as e:
            logger.error(f"Error cargando perfil: {e}")
            return None

    def tiene_perfil(self) -> bool:
        return self._ruta.exists()

    def eliminar_perfil(self):
        if self._ruta.exists():
            self._ruta.unlink()
            logger.info("Perfil eliminado.")
