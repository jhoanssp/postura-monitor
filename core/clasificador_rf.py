"""
Clasificador de Postura con Random Forest — v1.0
Integra el dataset de Zenodo (https://zenodo.org/records/14230872)
con 4794 muestras de 13 sujetos y 99 landmarks de MediaPipe.

Etiquetas de tronco superior (upperbody_label):
  TUP  → Upright (erguido, correcto)
  TLF  → Leaning Forward (inclinado hacia adelante)
  TLB  → Leaning Backward (recostado hacia atrás)
  TLL  → Leaning Left (inclinado a la izquierda)
  TLR  → Leaning Right (inclinado a la derecha)

Etiquetas de piernas/parte inferior (lowerbody_label):
  LAP  → Ankles Parallel (pies paralelos, correcto)
  LWA  → Wide Ankles (pies separados)
  LCS  → Cross Sitting (sentado cruzado)
  LCL  → Crossed Legs Left (pierna izquierda encima)
  LCR  → Crossed Legs Right (pierna derecha encima)
  LLL  → Legs Left (piernas hacia la izquierda)
  LLR  → Legs Right (piernas hacia la derecha)

CV accuracy (GroupKFold, subject-independent):
  Upper body: 96.9% ± 1.2%
  Lower body: 94.6% ± 4.0%
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Dict, Optional, Tuple

import numpy as np

from utils.logger import crear_logger

logger = crear_logger("clasificador_rf")

# ---------------------------------------------------------------------------
# Rutas de los modelos (.pkl generados por entrenamiento_rf.py)
# ---------------------------------------------------------------------------
_DIR_MODELOS = Path(__file__).resolve().parent.parent / "models"


# ---------------------------------------------------------------------------
# Enums con las etiquetas del dataset
# ---------------------------------------------------------------------------

class PosturaTronco(Enum):
    ERGUIDO          = "TUP"   # correcto
    INCLINADO_FRENTE = "TLF"   # forward lean
    INCLINADO_ATRAS  = "TLB"   # backward lean
    INCLINADO_IZQ    = "TLL"   # lean left
    INCLINADO_DER    = "TLR"   # lean right
    DESCONOCIDO      = "?"


class PosturaPiernas(Enum):
    PARALELAS        = "LAP"   # correcto
    PIES_SEPARADOS   = "LWA"
    SENTADO_CRUZADO  = "LCS"
    PIERNA_IZQ_ENCIMA = "LCL"
    PIERNA_DER_ENCIMA = "LCR"
    PIERNAS_IZQ      = "LLL"
    PIERNAS_DER      = "LLR"
    DESCONOCIDO      = "?"


# ---------------------------------------------------------------------------
# Resultado del clasificador
# ---------------------------------------------------------------------------

@dataclass
class ResultadoRF:
    postura_tronco: PosturaTronco = PosturaTronco.DESCONOCIDO
    postura_piernas: PosturaPiernas = PosturaPiernas.DESCONOCIDO
    confianza_tronco: float = 0.0
    confianza_piernas: float = 0.0
    es_correcto: bool = False
    descripcion_tronco: str = ""
    descripcion_piernas: str = ""
    modelo_disponible: bool = False

    # Mapeo de etiqueta → descripción en español
    _DESC_TRONCO = {
        "TUP": "Tronco erguido ✓",
        "TLF": "Tronco inclinado hacia adelante",
        "TLB": "Tronco recostado hacia atrás",
        "TLL": "Tronco inclinado a la izquierda",
        "TLR": "Tronco inclinado a la derecha",
    }
    _DESC_PIERNAS = {
        "LAP": "Pies paralelos ✓",
        "LWA": "Pies muy separados",
        "LCS": "Sentado con piernas cruzadas",
        "LCL": "Pierna izquierda encima",
        "LCR": "Pierna derecha encima",
        "LLL": "Piernas hacia la izquierda",
        "LLR": "Piernas hacia la derecha",
    }


# ---------------------------------------------------------------------------
# Clasificador principal
# ---------------------------------------------------------------------------

class ClasificadorRF:
    """
    Wrapper liviano sobre los modelos RandomForest entrenados.
    Se carga una sola vez y reutiliza en cada frame.

    Uso:
        clf = ClasificadorRF()
        resultado = clf.clasificar(landmarks_dict)
    """

    # Índices de MediaPipe que corresponden a los 99 features del dataset
    # (33 puntos × 3 coordenadas = 99 valores; igual orden que el CSV)
    _MP_INDICES_XYZ = [
        # nose
        0,
        # left eye inner/center/outer
        1, 2, 3,
        # right eye inner/center/outer
        4, 5, 6,
        # left ear, right ear
        7, 8,
        # mouth left/right
        9, 10,
        # shoulders
        11, 12,
        # elbows
        13, 14,
        # wrists
        15, 16,
        # left pinky/index/thumb
        17, 18, 19,
        # right pinky/index/thumb
        20, 21, 22,
        # hips
        23, 24,
        # knees
        25, 26,
        # ankles
        27, 28,
        # heels
        29, 30,
        # foot indices
        31, 32,
    ]

    def __init__(self, dir_modelos: Optional[Path] = None):
        self._dir = dir_modelos or _DIR_MODELOS
        self._rf_up  = None
        self._rf_lo  = None
        self._le_up  = None
        self._le_lo  = None
        self._feat   = None
        self._listo  = False
        self._cargar_modelos()

    # ------------------------------------------------------------------
    # Carga
    # ------------------------------------------------------------------

    def _cargar_modelos(self) -> None:
        try:
            import joblib
        except ImportError:
            logger.warning("joblib no instalado. Ejecuta: pip install joblib")
            return

        archivos = {
            "rf_upperbody.pkl": "_rf_up",
            "rf_lowerbody.pkl": "_rf_lo",
            "le_upperbody.pkl": "_le_up",
            "le_lowerbody.pkl": "_le_lo",
            "feature_cols.pkl": "_feat",
        }
        for nombre, attr in archivos.items():
            ruta = self._dir / nombre
            if not ruta.exists():
                logger.warning(
                    f"Modelo no encontrado: {ruta}. "
                    "Ejecuta 'python entrenamiento_rf.py' para generarlo."
                )
                return
            setattr(self, attr, joblib.load(ruta))

        self._listo = True
        logger.info(
            f"ClasificadorRF listo | upper: {list(self._le_up.classes_)} | "
            f"lower: {list(self._le_lo.classes_)}"
        )

    @property
    def disponible(self) -> bool:
        return self._listo

    # ------------------------------------------------------------------
    # Conversión landmarks → vector de features
    # ------------------------------------------------------------------

    def _landmarks_a_vector(self, landmarks: Dict) -> Optional[np.ndarray]:
        """
        Convierte el dict de landmarks de MediaPipe al vector de 99 floats
        esperado por el modelo.

        Acepta tanto PuntoLandmark (objeto con .x .y .z) como dict/lista.
        Los puntos ausentes se rellenan con 0.0.
        """
        vec = np.zeros(99, dtype=np.float32)
        for i, idx in enumerate(self._MP_INDICES_XYZ):
            pt = landmarks.get(idx)
            if pt is None:
                continue
            base = i * 3
            if hasattr(pt, "x"):
                vec[base]     = float(pt.x)
                vec[base + 1] = float(pt.y)
                vec[base + 2] = float(pt.z)
            else:
                try:
                    vec[base]     = float(pt[0])
                    vec[base + 1] = float(pt[1])
                    vec[base + 2] = float(pt[2]) if len(pt) > 2 else 0.0
                except Exception:
                    pass
        return vec

    # ------------------------------------------------------------------
    # Inferencia
    # ------------------------------------------------------------------

    def clasificar(self, landmarks: Optional[Dict]) -> ResultadoRF:
        """
        Clasifica la postura a partir del dict de landmarks de MediaPipe.

        Returns:
            ResultadoRF con la predicción de tronco y piernas.
        """
        resultado = ResultadoRF(modelo_disponible=self._listo)

        if not self._listo or not landmarks:
            return resultado

        vec = self._landmarks_a_vector(landmarks)
        X   = vec.reshape(1, -1)

        # ── Tronco superior ───────────────────────────────────────────────
        try:
            pred_up   = self._rf_up.predict(X)[0]
            proba_up  = self._rf_up.predict_proba(X)[0].max()
            label_up  = self._le_up.inverse_transform([pred_up])[0]
            try:
                resultado.postura_tronco   = PosturaTronco(label_up)
            except ValueError:
                resultado.postura_tronco   = PosturaTronco.DESCONOCIDO
            resultado.confianza_tronco = float(proba_up)
            resultado.descripcion_tronco = ResultadoRF._DESC_TRONCO.get(
                label_up, label_up
            )
        except Exception as e:
            logger.error(f"Error predicción tronco: {e}")

        # ── Piernas / parte inferior ──────────────────────────────────────
        try:
            pred_lo   = self._rf_lo.predict(X)[0]
            proba_lo  = self._rf_lo.predict_proba(X)[0].max()
            label_lo  = self._le_lo.inverse_transform([pred_lo])[0]
            try:
                resultado.postura_piernas   = PosturaPiernas(label_lo)
            except ValueError:
                resultado.postura_piernas   = PosturaPiernas.DESCONOCIDO
            resultado.confianza_piernas = float(proba_lo)
            resultado.descripcion_piernas = ResultadoRF._DESC_PIERNAS.get(
                label_lo, label_lo
            )
        except Exception as e:
            logger.error(f"Error predicción piernas: {e}")

        # ── Estado global ─────────────────────────────────────────────────
        tronco_ok  = resultado.postura_tronco  == PosturaTronco.ERGUIDO
        piernas_ok = resultado.postura_piernas == PosturaPiernas.PARALELAS
        resultado.es_correcto = tronco_ok and piernas_ok

        return resultado

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def es_postura_correcta(self, landmarks: Optional[Dict]) -> bool:
        return self.clasificar(landmarks).es_correcto

    def __repr__(self) -> str:  # pragma: no cover
        estado = "listo" if self._listo else "sin modelos"
        return f"ClasificadorRF({estado})"
