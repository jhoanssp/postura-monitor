"""
Analizador de 10 posturas biomecánicas — v4.4.8
Fuentes: Vaibhav 2025, Trygub 2023, Patel 2024, Pawitra 2025/2026, Sahoo 2026
"""

import numpy as np
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional
from utils.logger import crear_logger

logger = crear_logger("analizador_posturas")


class NivelAlerta(Enum):
    CORRECTO    = "correcto"
    ADVERTENCIA = "advertencia"
    INCORRECTO  = "incorrecto"


@dataclass
class ResultadoPostura:
    nombre: str
    nivel: NivelAlerta
    valor_medido: float
    umbral: float
    descripcion: str
    vista: str


@dataclass
class ResultadoAnalisis10:
    posturas: List[ResultadoPostura] = field(default_factory=list)
    nivel_global: NivelAlerta = NivelAlerta.CORRECTO
    vista_detectada: str = "frontal"
    usuario_presente: bool = True
    debe_alertar: bool = False
    alertas_activas: List[str] = field(default_factory=list)
    angulo_cuello: Optional[float] = None
    angulo_espalda: Optional[float] = None
    inclinacion_lateral: Optional[float] = None


def _angulo_vectores(v1: np.ndarray, v2: np.ndarray) -> float:
    n1 = np.linalg.norm(v1); n2 = np.linalg.norm(v2)
    if n1 < 1e-8 or n2 < 1e-8: return 0.0
    cos = np.dot(v1, v2) / (n1 * n2)
    return float(np.degrees(np.arccos(np.clip(cos, -1, 1))))


def _punto(lm: dict, idx: int) -> Optional[np.ndarray]:
    """Extrae (x, y) de PuntoLandmark o lista — compatible con ambos formatos."""
    p = lm.get(idx)
    if p is None: return None
    if hasattr(p, 'x'):
        if getattr(p, 'visibilidad', 1.0) < 0.4: return None
        return np.array([p.x, p.y])
    try:
        vis = p[3] if len(p) > 3 else 1.0
        return np.array(p[:2]) if vis > 0.4 else None
    except Exception: return None


def _medio(a, b):
    if a is None or b is None: return None
    return (a + b) / 2


EJE_V = np.array([0.0, -1.0])  # vertical hacia arriba (y decrece hacia arriba)


from core.calibrador import UmbralesPersonalizados


class AnalizadorPosturas:

    def __init__(self, umbrales: Optional[UmbralesPersonalizados] = None):
        self._u = umbrales or UmbralesPersonalizados()

    def actualizar_umbrales(self, u: UmbralesPersonalizados):
        self._u = u

    def analizar(self, landmarks: dict, vista: str = "frontal") -> ResultadoAnalisis10:
        if not landmarks:
            return ResultadoAnalisis10(usuario_presente=False)

        posturas: List[ResultadoPostura] = []

        # Posturas laterales (cuello, tronco sagital)
        if vista in ("lateral", "auto"):
            posturas += self._p1_encorvamiento(landmarks)
            posturas += self._p2_flexion_cervical(landmarks)
            posturas += self._p3_tronco_adelante(landmarks)
            posturas += self._p4_tronco_atras(landmarks)

        # Posturas frontales (asimetría)
        if vista in ("frontal", "auto"):
            posturas += self._p6_inclinacion_lateral_tronco(landmarks)
            posturas += self._p7_inclinacion_lateral_cuello(landmarks)
            posturas += self._p8_brazos_cruzados(landmarks)
            posturas += self._p9_piernas_cruzadas(landmarks)

        # Postura 5: funciona en ambas vistas
        posturas += self._p5_tronco_vertical(landmarks)

        niveles = [p.nivel for p in posturas]
        if NivelAlerta.INCORRECTO in niveles:
            global_ = NivelAlerta.INCORRECTO
        elif NivelAlerta.ADVERTENCIA in niveles:
            global_ = NivelAlerta.ADVERTENCIA
        else:
            global_ = NivelAlerta.CORRECTO

        alertas = [p.nombre for p in posturas if p.nivel == NivelAlerta.INCORRECTO]

        ang_cuello  = next((p.valor_medido for p in posturas if "Cervical" in p.nombre), None)
        ang_espalda = next((p.valor_medido for p in posturas if "Encorvamiento" in p.nombre), None)
        inc_lat     = next((p.valor_medido for p in posturas if "Lateral Tronco" in p.nombre), None)

        return ResultadoAnalisis10(
            posturas=posturas, nivel_global=global_,
            vista_detectada=vista, usuario_presente=True,
            debe_alertar=(global_ == NivelAlerta.INCORRECTO),
            alertas_activas=alertas,
            angulo_cuello=ang_cuello, angulo_espalda=ang_espalda,
            inclinacion_lateral=inc_lat,
        )

    # ── Postura 1: Encorvamiento ──────────────────────────────────────────────
    # Ángulo EN el hombro entre vector→cadera y vector→oído
    # ~170° recto, <150° encorvado
    # Ref: Vaibhav et al. 2025

    def _p1_encorvamiento(self, lm: dict) -> List[ResultadoPostura]:
        h = _medio(_punto(lm, 11), _punto(lm, 12))
        c = _medio(_punto(lm, 23), _punto(lm, 24))
        o = _medio(_punto(lm, 7),  _punto(lm, 8))
        if any(p is None for p in [h, c, o]): return []

        # CORRECCIÓN: ángulo en el vértice hombro entre (hombro→cadera) y (hombro→oído)
        # Cuando recto: ~170°. Cuando encorvado: <150°
        ang = _angulo_vectores(c - h, o - h)
        umbral = self._u.encorvamiento_alerta  # 150°

        nivel = (NivelAlerta.INCORRECTO if ang < umbral
                 else NivelAlerta.ADVERTENCIA if ang < umbral + 12
                 else NivelAlerta.CORRECTO)
        return [ResultadoPostura(
            nombre="Encorvamiento (Slouching)", nivel=nivel,
            valor_medido=ang, umbral=umbral,
            descripcion=f"Ángulo en hombro: {ang:.1f}° (correcto: >{umbral:.0f}°)",
            vista="lateral",
        )]

    # ── Postura 2: Flexión cervical excesiva ──────────────────────────────────
    # Ángulo del vector oído-hombro respecto al eje vertical
    # 0-15° normal, >30° excesivo
    # Ref: Trygub et al. 2023

    def _p2_flexion_cervical(self, lm: dict) -> List[ResultadoPostura]:
        o = _medio(_punto(lm, 7), _punto(lm, 8))
        h = _medio(_punto(lm, 11), _punto(lm, 12))
        if o is None or h is None: return []
        ang = _angulo_vectores(o - h, EJE_V)
        umbral = self._u.neck_flexion_alerta  # 30°

        nivel = (NivelAlerta.INCORRECTO if ang > umbral
                 else NivelAlerta.ADVERTENCIA if ang > umbral - 8
                 else NivelAlerta.CORRECTO)
        return [ResultadoPostura(
            nombre="Flexión Cervical Excesiva", nivel=nivel,
            valor_medido=ang, umbral=umbral,
            descripcion=f"Inclinación cuello: {ang:.1f}° (correcto: <{umbral:.0f}°)",
            vista="lateral",
        )]

    # ── Postura 3: Tronco hacia adelante ──────────────────────────────────────

    def _p3_tronco_adelante(self, lm: dict) -> List[ResultadoPostura]:
        h = _medio(_punto(lm, 11), _punto(lm, 12))
        c = _medio(_punto(lm, 23), _punto(lm, 24))
        if h is None or c is None: return []
        diff_x = float(h[0] - c[0])
        umbral = self._u.tronco_adelante_alerta

        nivel = (NivelAlerta.INCORRECTO if diff_x > umbral
                 else NivelAlerta.ADVERTENCIA if diff_x > umbral - 0.02
                 else NivelAlerta.CORRECTO)
        return [ResultadoPostura(
            nombre="Tronco Proyectado Adelante", nivel=nivel,
            valor_medido=diff_x, umbral=umbral,
            descripcion=f"Desplazamiento h-c: {diff_x:.3f}",
            vista="lateral",
        )]

    # ── Postura 4: Tronco hacia atrás ─────────────────────────────────────────

    def _p4_tronco_atras(self, lm: dict) -> List[ResultadoPostura]:
        h = _medio(_punto(lm, 11), _punto(lm, 12))
        c = _medio(_punto(lm, 23), _punto(lm, 24))
        if h is None or c is None: return []
        diff_x = float(h[0] - c[0])
        umbral = self._u.tronco_atras_alerta

        nivel = (NivelAlerta.INCORRECTO if diff_x < umbral
                 else NivelAlerta.ADVERTENCIA if diff_x < umbral + 0.02
                 else NivelAlerta.CORRECTO)
        return [ResultadoPostura(
            nombre="Tronco Recostado Atrás", nivel=nivel,
            valor_medido=diff_x, umbral=umbral,
            descripcion=f"Reclinación: {diff_x:.3f} (correcto: >{umbral:.3f})",
            vista="lateral",
        )]

    # ── Postura 5: Desviación tronco >20° ────────────────────────────────────

    def _p5_tronco_vertical(self, lm: dict) -> List[ResultadoPostura]:
        h = _medio(_punto(lm, 11), _punto(lm, 12))
        c = _medio(_punto(lm, 23), _punto(lm, 24))
        if h is None or c is None: return []
        ang = _angulo_vectores(h - c, EJE_V)
        umbral = self._u.tronco_vertical_alerta  # 20°

        nivel = (NivelAlerta.INCORRECTO if ang > umbral
                 else NivelAlerta.ADVERTENCIA if ang > umbral - 5
                 else NivelAlerta.CORRECTO)
        return [ResultadoPostura(
            nombre="Desviación Tronco Vertical", nivel=nivel,
            valor_medido=ang, umbral=umbral,
            descripcion=f"Desviación torso: {ang:.1f}° (correcto: <{umbral:.0f}°)",
            vista="ambas",
        )]

    # ── Postura 6: Inclinación lateral tronco ─────────────────────────────────
    # Umbral elevado a 20° para reducir falsos positivos por asimetría natural

    def _p6_inclinacion_lateral_tronco(self, lm: dict) -> List[ResultadoPostura]:
        hi = _punto(lm, 11); hd = _punto(lm, 12)
        if hi is None or hd is None: return []
        ang = abs(float(np.degrees(np.arctan2(hd[1] - hi[1], hd[0] - hi[0]))))
        umbral = self._u.inclinacion_lateral_tronco  # 20°

        nivel = (NivelAlerta.INCORRECTO if ang > umbral
                 else NivelAlerta.ADVERTENCIA if ang > umbral - 5
                 else NivelAlerta.CORRECTO)
        return [ResultadoPostura(
            nombre="Inclinación Lateral Tronco", nivel=nivel,
            valor_medido=ang, umbral=umbral,
            descripcion=f"Asimetría hombros: {ang:.1f}° (correcto: <{umbral:.0f}°)",
            vista="frontal",
        )]

    # ── Postura 7: Inclinación lateral cuello ─────────────────────────────────

    def _p7_inclinacion_lateral_cuello(self, lm: dict) -> List[ResultadoPostura]:
        oi = _punto(lm, 7); od = _punto(lm, 8)
        if oi is None or od is None: return []
        ang = abs(float(np.degrees(np.arctan2(od[1] - oi[1], od[0] - oi[0]))))
        umbral = self._u.inclinacion_lateral_cuello  # 15°

        nivel = (NivelAlerta.INCORRECTO if ang > umbral
                 else NivelAlerta.ADVERTENCIA if ang > umbral - 4
                 else NivelAlerta.CORRECTO)
        return [ResultadoPostura(
            nombre="Inclinación Lateral Cuello", nivel=nivel,
            valor_medido=ang, umbral=umbral,
            descripcion=f"Head tilt: {ang:.1f}° (correcto: <{umbral:.0f}°)",
            vista="frontal",
        )]

    # ── Postura 8: Brazos cruzados ────────────────────────────────────────────

    def _p8_brazos_cruzados(self, lm: dict) -> List[ResultadoPostura]:
        mi = _punto(lm, 15); md = _punto(lm, 16)
        ci = _punto(lm, 13); cd = _punto(lm, 14)
        if any(p is None for p in [mi, md, ci, cd]): return []
        val = min(float(np.linalg.norm(mi - cd)), float(np.linalg.norm(md - ci)))
        umbral = self._u.brazos_cruzados_dist

        nivel = (NivelAlerta.ADVERTENCIA if val < umbral else NivelAlerta.CORRECTO)
        return [ResultadoPostura(
            nombre="Brazos Cruzados", nivel=nivel,
            valor_medido=val, umbral=umbral,
            descripcion=f"Cruce muñeca-codo: {val:.3f} (correcto: >{umbral:.3f})",
            vista="frontal",
        )]

    # ── Postura 9: Piernas cruzadas ───────────────────────────────────────────

    def _p9_piernas_cruzadas(self, lm: dict) -> List[ResultadoPostura]:
        ri = _punto(lm, 25); rd = _punto(lm, 26)
        if ri is None or rd is None: return []
        diff = abs(float(ri[0] - rd[0]))
        umbral = self._u.piernas_cruzadas_dist

        nivel = (NivelAlerta.ADVERTENCIA if diff < umbral else NivelAlerta.CORRECTO)
        return [ResultadoPostura(
            nombre="Piernas Cruzadas", nivel=nivel,
            valor_medido=diff, umbral=umbral,
            descripcion=f"Separación rodillas: {diff:.3f} (correcto: >{umbral:.3f})",
            vista="frontal",
        )]
