"""
Analizador de 10 posturas biomecánicas — v4.4
Fuentes: Vaibhav 2025, Trygub 2023, Patel 2024, Pawitra 2025/2026, Sahoo 2026
"""

import numpy as np
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple

from core.calibrador import UmbralesPersonalizados
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
    vista: str          # frontal | lateral | ambas


@dataclass
class ResultadoAnalisis10:
    posturas: List[ResultadoPostura] = field(default_factory=list)
    nivel_global: NivelAlerta = NivelAlerta.CORRECTO
    vista_detectada: str = "frontal"
    usuario_presente: bool = True
    debe_alertar: bool = False
    alertas_activas: List[str] = field(default_factory=list)
    # Para compatibilidad con el sistema anterior
    angulo_cuello: Optional[float] = None
    angulo_espalda: Optional[float] = None
    inclinacion_lateral: Optional[float] = None


def _angulo_vectores(v1: np.ndarray, v2: np.ndarray) -> float:
    cos = np.dot(v1, v2) / (np.linalg.norm(v1) * np.linalg.norm(v2) + 1e-8)
    return float(np.degrees(np.arccos(np.clip(cos, -1, 1))))


def _punto(lm: dict, idx: int) -> Optional[np.ndarray]:
    p = lm.get(idx)
    if p is None: return None
    vis = p[3] if len(p) > 3 else 1.0
    return np.array(p[:2]) if vis > 0.4 else None


def _medio(a: Optional[np.ndarray], b: Optional[np.ndarray]) -> Optional[np.ndarray]:
    if a is None or b is None: return None
    return (a + b) / 2


EJE_V = np.array([0.0, -1.0])   # eje vertical hacia arriba
EJE_H = np.array([1.0,  0.0])   # eje horizontal


class AnalizadorPosturas:
    """Detecta las 10 posturas con umbrales personalizados o fijos."""

    def __init__(self, umbrales: Optional[UmbralesPersonalizados] = None):
        self._u = umbrales or UmbralesPersonalizados()

    def actualizar_umbrales(self, u: UmbralesPersonalizados):
        self._u = u

    # ── API principal ─────────────────────────────────────────────────────────

    def analizar(self, landmarks: dict, vista: str = "frontal") -> ResultadoAnalisis10:
        if not landmarks:
            return ResultadoAnalisis10(usuario_presente=False)

        posturas: List[ResultadoPostura] = []

        if vista in ("lateral", "auto"):
            posturas += self._p1_encorvamiento(landmarks)
            posturas += self._p2_flexion_cervical(landmarks)
            posturas += self._p3_tronco_adelante(landmarks)
            posturas += self._p4_tronco_atras(landmarks)

        if vista in ("frontal", "auto"):
            posturas += self._p6_inclinacion_lateral_tronco(landmarks)
            posturas += self._p7_inclinacion_lateral_cuello(landmarks)
            posturas += self._p8_brazos_cruzados(landmarks)
            posturas += self._p9_piernas_cruzadas(landmarks)

        # Postura 5 funciona en ambas vistas
        posturas += self._p5_tronco_vertical(landmarks)

        # Determinar nivel global
        niveles = [p.nivel for p in posturas]
        if NivelAlerta.INCORRECTO in niveles:
            global_ = NivelAlerta.INCORRECTO
        elif NivelAlerta.ADVERTENCIA in niveles:
            global_ = NivelAlerta.ADVERTENCIA
        else:
            global_ = NivelAlerta.CORRECTO

        alertas = [p.nombre for p in posturas
                   if p.nivel == NivelAlerta.INCORRECTO]

        # Extraer ángulos principales para compatibilidad con BD
        ang_cuello  = next((p.valor_medido for p in posturas if "Cervical" in p.nombre), None)
        ang_espalda = next((p.valor_medido for p in posturas if "Encorvamiento" in p.nombre), None)
        inc_lat     = next((p.valor_medido for p in posturas if "Lateral Tronco" in p.nombre), None)

        return ResultadoAnalisis10(
            posturas        = posturas,
            nivel_global    = global_,
            vista_detectada = vista,
            usuario_presente= True,
            debe_alertar    = global_ == NivelAlerta.INCORRECTO,
            alertas_activas = alertas,
            angulo_cuello   = ang_cuello,
            angulo_espalda  = ang_espalda,
            inclinacion_lateral = inc_lat,
        )

    # ── Postura 1: Encorvamiento ──────────────────────────────────────────────

    def _p1_encorvamiento(self, lm: dict) -> List[ResultadoPostura]:
        h = _medio(_punto(lm,11), _punto(lm,12))
        c = _medio(_punto(lm,23), _punto(lm,24))
        o = _medio(_punto(lm,7),  _punto(lm,8))
        if any(p is None for p in [h, c, o]):
            return []
        ang = _angulo_vectores(h - c, o - h)
        umbral = self._u.encorvamiento_alerta
        nivel = (NivelAlerta.INCORRECTO if ang < umbral
                 else NivelAlerta.ADVERTENCIA if ang < umbral + 15
                 else NivelAlerta.CORRECTO)
        return [ResultadoPostura(
            nombre="Encorvamiento (Slouching)",
            nivel=nivel, valor_medido=ang, umbral=umbral,
            descripcion=f"Ángulo torso-cuello: {ang:.1f}° (umbral: >{umbral:.0f}°)",
            vista="lateral",
        )]

    # ── Postura 2: Flexión cervical excesiva ──────────────────────────────────

    def _p2_flexion_cervical(self, lm: dict) -> List[ResultadoPostura]:
        o = _medio(_punto(lm,7), _punto(lm,8))
        h = _medio(_punto(lm,11), _punto(lm,12))
        if o is None or h is None:
            return []
        vec = o - h
        ang = _angulo_vectores(vec, EJE_V)
        umbral = self._u.neck_flexion_alerta
        nivel = (NivelAlerta.INCORRECTO if ang > umbral
                 else NivelAlerta.ADVERTENCIA if ang > umbral - 8
                 else NivelAlerta.CORRECTO)
        return [ResultadoPostura(
            nombre="Flexión Cervical Excesiva",
            nivel=nivel, valor_medido=ang, umbral=umbral,
            descripcion=f"Inclinación cuello: {ang:.1f}° (umbral: <{umbral:.0f}°)",
            vista="lateral",
        )]

    # ── Postura 3: Tronco hacia adelante ──────────────────────────────────────

    def _p3_tronco_adelante(self, lm: dict) -> List[ResultadoPostura]:
        h = _medio(_punto(lm,11), _punto(lm,12))
        c = _medio(_punto(lm,23), _punto(lm,24))
        if h is None or c is None:
            return []
        diff_x = float(h[0] - c[0])
        umbral = self._u.tronco_adelante_alerta
        nivel = (NivelAlerta.INCORRECTO if diff_x > umbral
                 else NivelAlerta.ADVERTENCIA if diff_x > umbral - 0.02
                 else NivelAlerta.CORRECTO)
        return [ResultadoPostura(
            nombre="Tronco Proyectado Adelante",
            nivel=nivel, valor_medido=diff_x, umbral=umbral,
            descripcion=f"Desplazamiento hombro-cadera: {diff_x:.3f}",
            vista="lateral",
        )]

    # ── Postura 4: Tronco hacia atrás ─────────────────────────────────────────

    def _p4_tronco_atras(self, lm: dict) -> List[ResultadoPostura]:
        h = _medio(_punto(lm,11), _punto(lm,12))
        c = _medio(_punto(lm,23), _punto(lm,24))
        if h is None or c is None:
            return []
        diff_x = float(h[0] - c[0])
        umbral = self._u.tronco_atras_alerta
        nivel = (NivelAlerta.INCORRECTO if diff_x < umbral
                 else NivelAlerta.ADVERTENCIA if diff_x < umbral + 0.02
                 else NivelAlerta.CORRECTO)
        return [ResultadoPostura(
            nombre="Tronco Recostado Atrás",
            nivel=nivel, valor_medido=diff_x, umbral=umbral,
            descripcion=f"Reclinación: {diff_x:.3f} (umbral: >{umbral:.3f})",
            vista="lateral",
        )]

    # ── Postura 5: Tronco > 20° vertical ─────────────────────────────────────

    def _p5_tronco_vertical(self, lm: dict) -> List[ResultadoPostura]:
        h = _medio(_punto(lm,11), _punto(lm,12))
        c = _medio(_punto(lm,23), _punto(lm,24))
        if h is None or c is None:
            return []
        vec = h - c
        ang = _angulo_vectores(vec, EJE_V)
        umbral = self._u.tronco_vertical_alerta
        nivel = (NivelAlerta.INCORRECTO if ang > umbral
                 else NivelAlerta.ADVERTENCIA if ang > umbral - 5
                 else NivelAlerta.CORRECTO)
        return [ResultadoPostura(
            nombre="Desviación Tronco Vertical",
            nivel=nivel, valor_medido=ang, umbral=umbral,
            descripcion=f"Desviación torso: {ang:.1f}° (umbral: <{umbral:.0f}°)",
            vista="ambas",
        )]

    # ── Postura 6: Inclinación lateral tronco ─────────────────────────────────

    def _p6_inclinacion_lateral_tronco(self, lm: dict) -> List[ResultadoPostura]:
        hi = _punto(lm, 11)
        hd = _punto(lm, 12)
        if hi is None or hd is None:
            return []
        ang = abs(float(np.degrees(np.arctan2(hd[1]-hi[1], hd[0]-hi[0]))))
        umbral = self._u.inclinacion_lateral_tronco
        nivel = (NivelAlerta.INCORRECTO if ang > umbral
                 else NivelAlerta.ADVERTENCIA if ang > umbral - 4
                 else NivelAlerta.CORRECTO)
        return [ResultadoPostura(
            nombre="Inclinación Lateral Tronco",
            nivel=nivel, valor_medido=ang, umbral=umbral,
            descripcion=f"Asimetría hombros: {ang:.1f}° (umbral: <{umbral:.0f}°)",
            vista="frontal",
        )]

    # ── Postura 7: Inclinación lateral cuello ─────────────────────────────────

    def _p7_inclinacion_lateral_cuello(self, lm: dict) -> List[ResultadoPostura]:
        oi = _punto(lm, 7)
        od = _punto(lm, 8)
        if oi is None or od is None:
            return []
        ang = abs(float(np.degrees(np.arctan2(od[1]-oi[1], od[0]-oi[0]))))
        umbral = self._u.inclinacion_lateral_cuello
        nivel = (NivelAlerta.INCORRECTO if ang > umbral
                 else NivelAlerta.ADVERTENCIA if ang > umbral - 4
                 else NivelAlerta.CORRECTO)
        return [ResultadoPostura(
            nombre="Inclinación Lateral Cuello",
            nivel=nivel, valor_medido=ang, umbral=umbral,
            descripcion=f"Head tilt: {ang:.1f}° (umbral: <{umbral:.0f}°)",
            vista="frontal",
        )]

    # ── Postura 8: Brazos cruzados ────────────────────────────────────────────

    def _p8_brazos_cruzados(self, lm: dict) -> List[ResultadoPostura]:
        mi = _punto(lm, 15)   # muñeca izq
        md = _punto(lm, 16)   # muñeca der
        ci = _punto(lm, 13)   # codo izq
        cd = _punto(lm, 14)   # codo der
        if any(p is None for p in [mi, md, ci, cd]):
            return []
        dist1 = float(np.linalg.norm(mi - cd))
        dist2 = float(np.linalg.norm(md - ci))
        val   = min(dist1, dist2)
        umbral = self._u.brazos_cruzados_dist
        nivel = (NivelAlerta.ADVERTENCIA if val < umbral
                 else NivelAlerta.CORRECTO)
        return [ResultadoPostura(
            nombre="Brazos Cruzados",
            nivel=nivel, valor_medido=val, umbral=umbral,
            descripcion=f"Dist. muñeca-codo cruzado: {val:.3f} (umbral: >{umbral:.3f})",
            vista="frontal",
        )]

    # ── Postura 9: Piernas cruzadas ───────────────────────────────────────────

    def _p9_piernas_cruzadas(self, lm: dict) -> List[ResultadoPostura]:
        ri = _punto(lm, 25)   # rodilla izq
        rd = _punto(lm, 26)   # rodilla der
        if ri is None or rd is None:
            return []
        diff = abs(float(ri[0] - rd[0]))
        umbral = self._u.piernas_cruzadas_dist
        nivel = (NivelAlerta.ADVERTENCIA if diff < umbral
                 else NivelAlerta.CORRECTO)
        return [ResultadoPostura(
            nombre="Piernas Cruzadas",
            nivel=nivel, valor_medido=diff, umbral=umbral,
            descripcion=f"Separación rodillas: {diff:.3f} (umbral: >{umbral:.3f})",
            vista="frontal",
        )]
