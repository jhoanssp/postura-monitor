"""
Analizador de 10 posturas biomecánicas — v4.5.0
Correcciones v4.5.0:
  - Encorvamiento frontal via ratio nariz-hombros/ancho-hombros
  - Distracción solo en modo frontal (lateral = usuario mira pantalla, no cámara)
  - GestorVista estable (10 frames para cambiar a lateral)
  - arctan2 corregido para espejo MediaPipe
  - p8 brazos cruzados deshabilitado
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
    usuario_distraido: bool = False
    debe_alertar: bool = False
    alertas_activas: List[str] = field(default_factory=list)
    angulo_cuello: Optional[float] = None
    angulo_espalda: Optional[float] = None
    inclinacion_lateral: Optional[float] = None


def _ang(v1: np.ndarray, v2: np.ndarray) -> float:
    n1 = np.linalg.norm(v1); n2 = np.linalg.norm(v2)
    if n1 < 1e-8 or n2 < 1e-8: return 0.0
    return float(np.degrees(np.arccos(np.clip(np.dot(v1, v2)/(n1*n2), -1, 1))))


def _p(lm: dict, idx: int) -> Optional[np.ndarray]:
    pt = lm.get(idx)
    if pt is None: return None
    if hasattr(pt, 'x'):
        if getattr(pt, 'visibilidad', 1.0) < 0.4: return None
        return np.array([pt.x, pt.y])
    try:
        vis = pt[3] if len(pt) > 3 else 1.0
        return np.array(pt[:2]) if vis > 0.4 else None
    except Exception: return None


def _m(a, b):
    if a is None or b is None: return None
    return (a + b) / 2


EJE_V = np.array([0.0, -1.0])


from core.calibrador import UmbralesPersonalizados


# ── Gestor de vista estable ───────────────────────────────────────────────────

class GestorVista:
    """
    Requiere 10 frames consecutivos de señal lateral para cambiar vista.
    Vuelve a frontal rápidamente (3 frames).
    """
    def __init__(self):
        self._contador = 0
        self._vista    = "frontal"

    def actualizar(self, lm: Optional[dict]) -> str:
        if not lm: return self._vista
        hi = lm.get(11); hd = lm.get(12)
        if hi is None or hd is None: return self._vista
        hix = hi.x if hasattr(hi,'x') else float(hi[0])
        hdx = hd.x if hasattr(hd,'x') else float(hd[0])

        if abs(hix - hdx) < 0.15:
            self._contador = min(self._contador + 1, 15)
        else:
            self._contador = max(self._contador - 2, -10)

        if   self._contador >= 10: self._vista = "lateral"
        elif self._contador <= -3: self._vista = "frontal"
        return self._vista


# ── Analizador principal ──────────────────────────────────────────────────────

class AnalizadorPosturas:

    def __init__(self, umbrales: Optional[UmbralesPersonalizados] = None):
        self._u  = umbrales or UmbralesPersonalizados()
        self._gv = GestorVista()

    def actualizar_umbrales(self, u: UmbralesPersonalizados):
        self._u = u

    def analizar(self, landmarks: dict, vista: str = "auto") -> ResultadoAnalisis10:
        if not landmarks:
            return ResultadoAnalisis10(usuario_presente=False)

        vista_estable = self._gv.actualizar(landmarks) if vista == "auto" else vista

        # Distracción SOLO en modo frontal
        # En lateral el usuario mira a la pantalla, no a la cámara → normal
        distraido = False
        if vista_estable == "frontal":
            distraido = self._detectar_distraccion(landmarks)
        if distraido:
            return ResultadoAnalisis10(
                usuario_presente=True, usuario_distraido=True,
                nivel_global=NivelAlerta.CORRECTO,
                vista_detectada=vista_estable,
            )

        posturas: List[ResultadoPostura] = []

        if vista_estable == "lateral":
            posturas += self._p1_encorvamiento(landmarks)
            posturas += self._p2_flexion_cervical(landmarks)
            posturas += self._p3_tronco_adelante(landmarks)
            posturas += self._p4_tronco_atras(landmarks)

        if vista_estable == "frontal":
            posturas += self._p6_inclinacion_lateral_tronco(landmarks)
            posturas += self._p7_inclinacion_lateral_cuello(landmarks)
            posturas += self._p10_encorvamiento_frontal(landmarks)
            posturas += self._p9_piernas_cruzadas(landmarks)

        posturas += self._p5_tronco_vertical(landmarks)

        niveles = [p.nivel for p in posturas]
        global_ = (NivelAlerta.INCORRECTO  if NivelAlerta.INCORRECTO  in niveles else
                   NivelAlerta.ADVERTENCIA if NivelAlerta.ADVERTENCIA in niveles else
                   NivelAlerta.CORRECTO)
        alertas = [p.nombre for p in posturas if p.nivel == NivelAlerta.INCORRECTO]

        return ResultadoAnalisis10(
            posturas=posturas, nivel_global=global_,
            vista_detectada=vista_estable,
            usuario_presente=True, usuario_distraido=False,
            debe_alertar=(global_ == NivelAlerta.INCORRECTO),
            alertas_activas=alertas,
            angulo_cuello =next((p.valor_medido for p in posturas if "Cervical"      in p.nombre), None),
            angulo_espalda=next((p.valor_medido for p in posturas if "Encorvam"      in p.nombre), None),
            inclinacion_lateral=next((p.valor_medido for p in posturas if "Lateral Tronco" in p.nombre), None),
        )

    # ── Detección de distracción (solo frontal) ───────────────────────────────

    def _detectar_distraccion(self, lm: dict) -> bool:
        oi = _p(lm,7); od = _p(lm,8)
        hi = _p(lm,11); hd = _p(lm,12)
        if any(x is None for x in [oi,od,hi,hd]): return False
        ear_span      = abs(float(oi[0] - od[0]))
        shoulder_span = abs(float(hi[0] - hd[0]))
        if shoulder_span < 0.05: return False
        return (ear_span / shoulder_span) < 0.30

    # ── Postura 1: Encorvamiento lateral ─────────────────────────────────────

    def _p1_encorvamiento(self, lm: dict) -> List[ResultadoPostura]:
        h = _m(_p(lm,11),_p(lm,12))
        c = _m(_p(lm,23),_p(lm,24))
        o = _m(_p(lm,7), _p(lm,8))
        if any(x is None for x in [h,c,o]): return []
        a = _ang(c-h, o-h)
        u = self._u.encorvamiento_alerta
        n = (NivelAlerta.INCORRECTO  if a < u else
             NivelAlerta.ADVERTENCIA if a < u+12 else
             NivelAlerta.CORRECTO)
        return [ResultadoPostura("Encorvamiento (Slouching)", n, a, u,
            f"Ángulo hombro: {a:.1f}° (correcto: >{u:.0f}°)", "lateral")]

    # ── Postura 2: Flexión cervical ───────────────────────────────────────────

    def _p2_flexion_cervical(self, lm: dict) -> List[ResultadoPostura]:
        o = _m(_p(lm,7),_p(lm,8))
        h = _m(_p(lm,11),_p(lm,12))
        if o is None or h is None: return []
        a = _ang(o-h, EJE_V)
        u = self._u.neck_flexion_alerta
        n = (NivelAlerta.INCORRECTO  if a > u else
             NivelAlerta.ADVERTENCIA if a > u-8 else
             NivelAlerta.CORRECTO)
        return [ResultadoPostura("Flexión Cervical Excesiva", n, a, u,
            f"Inclinación cuello: {a:.1f}° (correcto: <{u:.0f}°)", "lateral")]

    # ── Postura 3: Tronco adelante (solo lateral) ─────────────────────────────

    def _p3_tronco_adelante(self, lm: dict) -> List[ResultadoPostura]:
        h = _m(_p(lm,11),_p(lm,12))
        c = _m(_p(lm,23),_p(lm,24))
        if h is None or c is None: return []
        dx = float(h[0]-c[0])
        u  = self._u.tronco_adelante_alerta
        n  = (NivelAlerta.INCORRECTO  if dx > u else
              NivelAlerta.ADVERTENCIA if dx > u-0.02 else
              NivelAlerta.CORRECTO)
        return [ResultadoPostura("Tronco Proyectado Adelante", n, dx, u,
            f"Desplazamiento: {dx:.3f}", "lateral")]

    # ── Postura 4: Tronco atrás (solo lateral) ────────────────────────────────

    def _p4_tronco_atras(self, lm: dict) -> List[ResultadoPostura]:
        h = _m(_p(lm,11),_p(lm,12))
        c = _m(_p(lm,23),_p(lm,24))
        if h is None or c is None: return []
        dx = float(h[0]-c[0])
        u  = self._u.tronco_atras_alerta
        n  = (NivelAlerta.INCORRECTO  if dx < u else
              NivelAlerta.ADVERTENCIA if dx < u+0.02 else
              NivelAlerta.CORRECTO)
        return [ResultadoPostura("Tronco Recostado Atrás", n, dx, u,
            f"Reclinación: {dx:.3f} (correcto: >{u:.3f})", "lateral")]

    # ── Postura 5: Desviación tronco vertical ─────────────────────────────────

    def _p5_tronco_vertical(self, lm: dict) -> List[ResultadoPostura]:
        h = _m(_p(lm,11),_p(lm,12))
        c = _m(_p(lm,23),_p(lm,24))
        if h is None or c is None: return []
        a = _ang(h-c, EJE_V)
        u = self._u.tronco_vertical_alerta
        n = (NivelAlerta.INCORRECTO  if a > u else
             NivelAlerta.ADVERTENCIA if a > u-5 else
             NivelAlerta.CORRECTO)
        return [ResultadoPostura("Desviación Tronco Vertical", n, a, u,
            f"Desviación: {a:.1f}° (correcto: <{u:.0f}°)", "ambas")]

    # ── Postura 6: Inclinación lateral tronco ─────────────────────────────────

    def _p6_inclinacion_lateral_tronco(self, lm: dict) -> List[ResultadoPostura]:
        hi = _p(lm,11); hd = _p(lm,12)
        if hi is None or hd is None: return []
        # LM11 (izq persona) aparece a la DERECHA en imagen → hi[0] > hd[0]
        dx = float(hi[0]-hd[0])
        dy = float(hi[1]-hd[1])
        a  = abs(float(np.degrees(np.arctan2(dy, dx))))
        u  = self._u.inclinacion_lateral_tronco
        n  = (NivelAlerta.INCORRECTO  if a > u else
              NivelAlerta.ADVERTENCIA if a > u-5 else
              NivelAlerta.CORRECTO)
        return [ResultadoPostura("Inclinación Lateral Tronco", n, a, u,
            f"Asimetría hombros: {a:.1f}° (correcto: <{u:.0f}°)", "frontal")]

    # ── Postura 7: Inclinación lateral cuello ─────────────────────────────────

    def _p7_inclinacion_lateral_cuello(self, lm: dict) -> List[ResultadoPostura]:
        oi = _p(lm,7); od = _p(lm,8)
        if oi is None or od is None: return []
        # LM7 (oído izq persona) aparece a la DERECHA en imagen → oi[0] > od[0]
        dx = float(oi[0]-od[0])
        dy = float(oi[1]-od[1])
        a  = abs(float(np.degrees(np.arctan2(dy, dx))))
        u  = self._u.inclinacion_lateral_cuello
        n  = (NivelAlerta.INCORRECTO  if a > u else
              NivelAlerta.ADVERTENCIA if a > u-4 else
              NivelAlerta.CORRECTO)
        return [ResultadoPostura("Inclinación Lateral Cuello", n, a, u,
            f"Head tilt: {a:.1f}° (correcto: <{u:.0f}°)", "frontal")]

    # ── Postura 8: Brazos cruzados — DESHABILITADA ────────────────────────────

    def _p8_brazos_cruzados(self, lm: dict) -> List[ResultadoPostura]:
        return []  # FP excesivos con teclado/mouse

    # ── Postura 9: Piernas cruzadas ───────────────────────────────────────────

    def _p9_piernas_cruzadas(self, lm: dict) -> List[ResultadoPostura]:
        ri = _p(lm,25); rd = _p(lm,26)
        if ri is None or rd is None: return []
        diff = abs(float(ri[0]-rd[0]))
        u    = self._u.piernas_cruzadas_dist
        n    = (NivelAlerta.ADVERTENCIA if diff < u else NivelAlerta.CORRECTO)
        return [ResultadoPostura("Piernas Cruzadas", n, diff, u,
            f"Separación rodillas: {diff:.3f} (correcto: >{u:.3f})", "frontal")]

    # ── Postura 10: Encorvamiento frontal (NUEVA) ─────────────────────────────
    # Ratio = (hombro_y - nariz_y) / ancho_hombros
    # Recto: ~0.85-1.0  |  Encorvado: <0.70
    # Detectable desde cámara frontal sin necesidad de vista lateral

    def _p10_encorvamiento_frontal(self, lm: dict) -> List[ResultadoPostura]:
        nariz = _p(lm, 0)
        hi    = _p(lm, 11); hd = _p(lm, 12)
        if any(x is None for x in [nariz, hi, hd]): return []

        shoulder_w = abs(float(hi[0] - hd[0]))
        if shoulder_w < 0.05: return []

        hombro_y_med = float((hi[1] + hd[1]) / 2)
        ratio = (hombro_y_med - float(nariz[1])) / shoulder_w

        u_inc  = self._u.encorvamiento_frontal_min       # 0.68
        u_adv  = self._u.encorvamiento_frontal_min + 0.12  # 0.80

        n = (NivelAlerta.INCORRECTO  if ratio < u_inc else
             NivelAlerta.ADVERTENCIA if ratio < u_adv else
             NivelAlerta.CORRECTO)

        return [ResultadoPostura(
            "Encorvamiento Frontal", n, round(ratio, 3), u_inc,
            f"Ratio nariz-hombro: {ratio:.2f} (correcto: >{u_inc:.2f})",
            "frontal",
        )]
