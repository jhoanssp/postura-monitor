"""
Calibrador de postura base — v4.6.0 FRONTAL SIMPLIFICADO
Solo requiere: hombros (11,12) y nariz (0).
Orejas (7,8) opcionales.
No usa caderas ni puntos laterales.
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
    """Medidas mínimas para calibración frontal."""
    ancho_hombros: float = 0.0           # distancia hombro_izq - hombro_der
    distancia_nariz_hombros: float = 0.0 # distancia vertical nariz - centro hombros
    neck_base_deg: float = 0.0           # ángulo cuello (si hay orejas)
    factor_distancia: float = 1.0        # distancia relativa a la cámara
    encorvamiento_frontal_ratio: float = 0.90  # ratio (hombro_y - nariz_y)/ancho_hombros
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
    FRAMES_REQUERIDOS = 45   # ~1.5 segundos a 30 fps
    ARCHIVO_PERFIL = "perfil_corporal.json"

    def __init__(self):
        from config.settings import CONFIG_DIR
        self._ruta = CONFIG_DIR / self.ARCHIVO_PERFIL
        self._frames_buffer: List[dict] = []
        self._calibrando = False

    def iniciar(self):
        self._frames_buffer = []
        self._calibrando = True
        logger.info("Calibración frontal iniciada. Mantén postura correcta mirando a la cámara.")

    def agregar_frame(self, landmarks: dict, vista: str = "frontal") -> float:
        """Agrega un frame si detecta hombros y nariz. Vista ignorada (siempre frontal)."""
        if not self._calibrando or not landmarks:
            return 0.0

        datos = self._extraer_medidas_frontales(landmarks)
        if datos:
            self._frames_buffer.append(datos)
            logger.debug(f"Frame válido: {len(self._frames_buffer)}/{self.FRAMES_REQUERIDOS}")
        else:
            logger.debug("Frame inválido: faltan hombros o nariz")

        return min(len(self._frames_buffer) / self.FRAMES_REQUERIDOS, 1.0)

    def finalizar(self, vista: str = "frontal") -> Optional[PerfilCorporal]:
        self._calibrando = False
        if len(self._frames_buffer) < 20:
            logger.warning(f"Pocos frames para calibrar: {len(self._frames_buffer)}. Mínimo 20.")
            return None

        perfil = self._calcular_perfil()
        self._guardar(perfil)
        logger.info(f"Calibración completada. Frames usados: {perfil.frames_usados}")
        return perfil

    # ── Extracción frontal simplificada ───────────────────────────────────────

    def _xy(self, lm: dict, idx: int) -> Optional[np.ndarray]:
        p = lm.get(idx)
        if p is None:
            return None
        if hasattr(p, 'x'):
            if getattr(p, 'visibilidad', 1.0) < 0.3:
                return None
            return np.array([p.x, p.y])
        try:
            vis = p[3] if len(p) > 3 else 1.0
            return np.array(p[:2]) if vis > 0.3 else None
        except Exception:
            return None

    def _extraer_medidas_frontales(self, lm: dict) -> Optional[dict]:
        """Solo requiere hombro_izq (11), hombro_der (12) y nariz (0)."""
        hi = self._xy(lm, 11)   # hombro izquierdo
        hd = self._xy(lm, 12)   # hombro derecho
        nariz = self._xy(lm, 0)

        if hi is None or hd is None or nariz is None:
            return None

        # Centro de hombros
        hombro_centro = (hi + hd) / 2.0
        ancho_hombros = float(np.linalg.norm(hi - hd))
        if ancho_hombros < 0.05:
            return None

        # Distancia vertical nariz - centro hombros
        dy = hombro_centro[1] - nariz[1]   # positivo si nariz arriba
        distancia_vertical = float(dy)

        # Ratio encorvamiento frontal = dy / ancho_hombros
        # Postura recta: ~0.85-1.0, encorvado: <0.68
        ratio = dy / ancho_hombros

        # Ángulo cuello (opcional, si hay orejas)
        oi = self._xy(lm, 7)
        od = self._xy(lm, 8)
        neck_deg = 0.0
        if oi is not None and od is not None:
            oido_centro = (oi + od) / 2.0
            vec_cuello = oido_centro - hombro_centro
            eje_v = np.array([0, -1])
            norm = np.linalg.norm(vec_cuello)
            if norm > 1e-6:
                cos = np.dot(vec_cuello, eje_v) / norm
                neck_deg = float(np.degrees(np.arccos(np.clip(cos, -1, 1))))

        # Factor de distancia basado en ancho de hombros (valor típico 0.35 a ~60cm)
        REF_ANCHO = 0.35
        factor_dist = REF_ANCHO / (ancho_hombros + 1e-6)

        return {
            "ancho_hombros": ancho_hombros,
            "distancia_vertical": distancia_vertical,
            "ratio": ratio,
            "neck_deg": neck_deg,
            "factor_distancia": factor_dist,
        }

    def _calcular_perfil(self) -> PerfilCorporal:
        """Promedia los frames eliminando outliers."""
        def mediana_robusta(vals):
            arr = np.array(vals)
            if len(arr) == 0:
                return 0.0
            q1, q3 = np.percentile(arr, [25, 75])
            iqr = q3 - q1
            filtrado = arr[(arr >= q1 - 1.5*iqr) & (arr <= q3 + 1.5*iqr)]
            return float(np.mean(filtrado)) if len(filtrado) > 0 else float(np.mean(arr))

        ancho = mediana_robusta([f["ancho_hombros"] for f in self._frames_buffer])
        ratio = mediana_robusta([f["ratio"] for f in self._frames_buffer])
        neck = mediana_robusta([f["neck_deg"] for f in self._frames_buffer])
        dist_factor = mediana_robusta([f["factor_distancia"] for f in self._frames_buffer])

        return PerfilCorporal(
            ancho_hombros=ancho,
            distancia_nariz_hombros=mediana_robusta([f["distancia_vertical"] for f in self._frames_buffer]),
            neck_base_deg=neck,
            factor_distancia=dist_factor,
            encorvamiento_frontal_ratio=ratio,
            timestamp=time.time(),
            frames_usados=len(self._frames_buffer),
        )

    def calcular_umbrales(self, perfil: PerfilCorporal) -> UmbralesPersonalizados:
        u = UmbralesPersonalizados()
        f = np.clip(perfil.factor_distancia, 0.5, 2.0)
        # Ajustar umbral de encorvamiento frontal según ratio personal
        u.encorvamiento_frontal_min = max(0.60, perfil.encorvamiento_frontal_ratio - 0.18)
        u.neck_flexion_alerta = perfil.neck_base_deg + 15.0 if perfil.neck_base_deg > 0 else 30.0
        u.tronco_adelante_alerta = 0.03 * f
        u.tronco_atras_alerta = -0.08 * f
        logger.info(f"Umbrales calculados: ratio_base={perfil.encorvamiento_frontal_ratio:.2f}, umbral={u.encorvamiento_frontal_min:.2f}")
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
