"""
Calibrador de postura base — v4.5.5
- Tolerante a puntos faltantes
- Logs de depuración para seguir el progreso
- Más robusto para diferentes condiciones de cámara
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
    altura_torso: float = 0.0
    ancho_hombros: float = 0.0
    distancia_oido_hombro: float = 0.0
    neck_base_deg: float = 0.0
    torso_base_deg: float = 0.0
    encorvamiento_base_deg: float = 0.0
    inclinacion_lateral_base: float = 0.0
    factor_distancia: float = 1.0
    encorvamiento_frontal_base: float = 0.90
    vista: str = "frontal"
    timestamp: float = 0.0
    frames_usados: int = 0


@dataclass
class UmbralesPersonalizados:
    encorvamiento_alerta: float = 150.0
    neck_flexion_alerta: float = 30.0
    tronco_adelante_alerta: float = 0.0
    tronco_atras_alerta: float = -0.05
    tronco_vertical_alerta: float = 20.0
    inclinacion_lateral_tronco: float = 20.0
    inclinacion_lateral_cuello: float = 15.0
    brazos_cruzados_dist: float = 0.30
    piernas_cruzadas_dist: float = 0.05
    encorvamiento_frontal_min: float = 0.68
    sedentarismo_segundos: int = 1800


class Calibrador:

    FRAMES_REQUERIDOS = 60   # 2 segundos a 30fps (menos que antes para que sea más rápida)
    ARCHIVO_PERFIL = "perfil_corporal.json"

    def __init__(self):
        from config.settings import CONFIG_DIR
        self._ruta = CONFIG_DIR / self.ARCHIVO_PERFIL
        self._frames_buffer: List[dict] = []
        self._calibrando = False
        self._inicio = 0.0

    def iniciar(self):
        self._frames_buffer = []
        self._calibrando = True
        self._inicio = time.time()
        logger.info("Calibración iniciada. Mantén postura correcta.")

    def agregar_frame(self, landmarks: dict, vista: str = "frontal") -> float:
        if not self._calibrando or not landmarks:
            return 0.0

        datos = self._extraer_medidas(landmarks, vista)
        if datos:
            self._frames_buffer.append(datos)
            logger.debug(f"Frame válido agregado. Total: {len(self._frames_buffer)}/{self.FRAMES_REQUERIDOS}")
        else:
            logger.debug("Frame inválido (puntos insuficientes)")

        return min(len(self._frames_buffer) / self.FRAMES_REQUERIDOS, 1.0)

    def finalizar(self, vista: str = "frontal") -> Optional[PerfilCorporal]:
        self._calibrando = False
        if len(self._frames_buffer) < 30:
            logger.warning(f"Pocos frames para calibrar: {len(self._frames_buffer)}. Se necesitan al menos 30.")
            return None

        perfil = self._calcular_perfil(vista)
        self._guardar(perfil)
        logger.info(f"Calibración completada. Frames usados: {perfil.frames_usados}")
        return perfil

    # ── Extracción tolerante ─────────────────────────────────────────────────

    def _xy(self, lm: dict, idx: int) -> Optional[np.ndarray]:
        p = lm.get(idx)
        if p is None:
            return None
        if hasattr(p, 'x'):
            # Es un objeto PuntoLandmark
            if getattr(p, 'visibilidad', 1.0) < 0.3:   # umbral más bajo
                return None
            return np.array([p.x, p.y])
        try:
            vis = p[3] if len(p) > 3 else 1.0
            return np.array(p[:2]) if vis > 0.3 else None
        except Exception:
            return None

    def _extraer_medidas(self, lm: dict, vista: str) -> Optional[dict]:
        """Extrae medidas, pero tolera puntos faltantes. Si faltan muchos, devuelve None."""
        try:
            h_izq = self._xy(lm, 11)
            h_der = self._xy(lm, 12)
            c_izq = self._xy(lm, 23)
            c_der = self._xy(lm, 24)
            o_izq = self._xy(lm, 7)
            o_der = self._xy(lm, 8)
            nariz = self._xy(lm, 0)

            # Necesitamos al menos un hombro y una cadera para continuar
            if (h_izq is None and h_der is None) or (c_izq is None and c_der is None):
                return None

            # Calcular puntos medios con los disponibles
            hombro_medio = None
            cadera_medio = None
            oido_medio = None

            if h_izq is not None and h_der is not None:
                hombro_medio = (h_izq + h_der) / 2
            elif h_izq is not None:
                hombro_medio = h_izq
            elif h_der is not None:
                hombro_medio = h_der

            if c_izq is not None and c_der is not None:
                cadera_medio = (c_izq + c_der) / 2
            elif c_izq is not None:
                cadera_medio = c_izq
            elif c_der is not None:
                cadera_medio = c_der

            if o_izq is not None and o_der is not None:
                oido_medio = (o_izq + o_der) / 2
            elif o_izq is not None:
                oido_medio = o_izq
            elif o_der is not None:
                oido_medio = o_der

            if hombro_medio is None or cadera_medio is None:
                return None

            # Medidas básicas
            altura_torso = float(np.linalg.norm(hombro_medio - cadera_medio))
            ancho_hombros = 0.0
            if h_izq is not None and h_der is not None:
                ancho_hombros = float(np.linalg.norm(h_izq - h_der))

            dist_oido_hombro = 0.0
            if oido_medio is not None:
                dist_oido_hombro = float(np.linalg.norm(oido_medio - hombro_medio))

            # Ángulo de encorvamiento (solo si tenemos oído)
            enc_deg = 0.0
            if oido_medio is not None:
                vec1 = cadera_medio - hombro_medio
                vec2 = oido_medio - hombro_medio
                norm1 = np.linalg.norm(vec1)
                norm2 = np.linalg.norm(vec2)
                if norm1 > 1e-6 and norm2 > 1e-6:
                    cos_ang = np.dot(vec1, vec2) / (norm1 * norm2)
                    enc_deg = float(np.degrees(np.arccos(np.clip(cos_ang, -1, 1))))

            # Ángulo cuello (vertical)
            neck_deg = 0.0
            if oido_medio is not None:
                vec_cuello = oido_medio - hombro_medio
                eje_v = np.array([0, -1])
                norm_c = np.linalg.norm(vec_cuello)
                if norm_c > 1e-6:
                    cos_n = np.dot(vec_cuello, eje_v) / norm_c
                    neck_deg = float(np.degrees(np.arccos(np.clip(cos_n, -1, 1))))

            # Ángulo torso vertical
            torso_deg = 0.0
            vec_torso = hombro_medio - cadera_medio
            norm_t = np.linalg.norm(vec_torso)
            if norm_t > 1e-6:
                cos_t = np.dot(vec_torso, np.array([0, -1])) / norm_t
                torso_deg = float(np.degrees(np.arccos(np.clip(cos_t, -1, 1))))

            # Inclinación lateral (solo si tenemos ambos hombros)
            inc_lat = 0.0
            if h_izq is not None and h_der is not None:
                dx = h_izq[0] - h_der[0]
                dy = h_izq[1] - h_der[1]
                inc_lat = abs(float(np.degrees(np.arctan2(dy, dx))))

            # Ratio encorvamiento frontal (solo si tenemos nariz)
            enc_frontal_ratio = 0.90
            if nariz is not None and ancho_hombros > 0.01 and h_izq is not None and h_der is not None:
                hombro_y_med = (h_izq[1] + h_der[1]) / 2.0
                enc_frontal_ratio = float((hombro_y_med - nariz[1]) / ancho_hombros)

            return {
                "altura_torso": altura_torso,
                "enc_frontal_ratio": enc_frontal_ratio,
                "ancho_hombros": ancho_hombros,
                "dist_oido_hombro": dist_oido_hombro,
                "enc_deg": enc_deg,
                "neck_deg": neck_deg,
                "torso_deg": torso_deg,
                "inc_lat": inc_lat,
                "vista": vista,
            }
        except Exception as e:
            logger.debug(f"Excepción en _extraer_medidas: {e}")
            return None

    # ── Cálculo del perfil ────────────────────────────────────────────────────

    def _calcular_perfil(self, vista: str) -> PerfilCorporal:
        def mediana_robusta(valores):
            arr = np.array(valores)
            if len(arr) == 0:
                return 0.0
            q1, q3 = np.percentile(arr, [25, 75])
            iqr = q3 - q1
            filtrado = arr[(arr >= q1 - 1.5*iqr) & (arr <= q3 + 1.5*iqr)]
            return float(np.mean(filtrado)) if len(filtrado) > 0 else float(np.mean(arr))

        keys = ["altura_torso","ancho_hombros","dist_oido_hombro","enc_frontal_ratio",
                "enc_deg","neck_deg","torso_deg","inc_lat"]
        vals = {k: [f[k] for f in self._frames_buffer if k in f] for k in keys}

        altura_media = mediana_robusta(vals["altura_torso"])
        REFERENCIA_TORSO = 0.35
        factor_dist = REFERENCIA_TORSO / (altura_media + 1e-6)
        enc_frontal = mediana_robusta(vals["enc_frontal_ratio"]) if vals.get("enc_frontal_ratio") else 0.90

        return PerfilCorporal(
            encorvamiento_frontal_base = enc_frontal,
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

    def calcular_umbrales(self, perfil: PerfilCorporal) -> UmbralesPersonalizados:
        u = UmbralesPersonalizados()
        f = np.clip(perfil.factor_distancia, 0.5, 2.0)
        u.encorvamiento_alerta = max(145.0, perfil.encorvamiento_base_deg - 15.0)
        u.neck_flexion_alerta = perfil.neck_base_deg + 15.0
        u.tronco_adelante_alerta =  0.03 * f
        u.tronco_atras_alerta    = -0.08 * f
        u.tronco_vertical_alerta = perfil.torso_base_deg + 15.0
        u.inclinacion_lateral_tronco = abs(perfil.inclinacion_lateral_base) + 12.0
        u.inclinacion_lateral_cuello = 15.0
        u.brazos_cruzados_dist  = perfil.ancho_hombros * 0.8
        u.piernas_cruzadas_dist = perfil.ancho_hombros * 0.15
        if hasattr(perfil, 'encorvamiento_frontal_base') and perfil.encorvamiento_frontal_base > 0:
            u.encorvamiento_frontal_min = max(0.60, perfil.encorvamiento_frontal_base - 0.18)
        logger.info(f"Umbrales calculados: torso={perfil.altura_torso:.3f}, dist={perfil.factor_distancia:.2f}")
        return u

    def _guardar(self, perfil: PerfilCorporal):
        self._ruta.parent.mkdir(parents=True, exist_ok=True)
        self._ruta.write_text(json.dumps(asdict(perfil), indent=2), encoding="utf-8")
        logger.info(f"Perfil guardado en {self._ruta}")

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
