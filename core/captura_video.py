"""
Módulo de captura de video — soporte para cámara simple y dual.
- CapturaVideo:     una sola cámara (comportamiento original)
- CapturaDualVideo: detecta y gestiona cámara principal + secundaria opcional
"""

import cv2
import numpy as np
import threading
from typing import Optional, Tuple, List

from config.settings import ConfiguracionCamara
from utils.logger import crear_logger

logger = crear_logger("captura_video")


# ── Cámara simple (comportamiento original) ───────────────────────────────────

class CapturaVideo:
    def __init__(self, config: ConfiguracionCamara):
        self.config = config
        self._captura: Optional[cv2.VideoCapture] = None
        self.activa: bool = False

    def iniciar(self) -> bool:
        logger.info(f"Iniciando cámara en índice {self.config.indice_camara}...")
        self._captura = cv2.VideoCapture(self.config.indice_camara)
        if not self._captura.isOpened():
            logger.error(f"No se pudo abrir la cámara {self.config.indice_camara}.")
            return False
        self._captura.set(cv2.CAP_PROP_FRAME_WIDTH,  self.config.ancho_frame)
        self._captura.set(cv2.CAP_PROP_FRAME_HEIGHT, self.config.alto_frame)
        self._captura.set(cv2.CAP_PROP_FPS,          self.config.fps_objetivo)
        ancho = int(self._captura.get(cv2.CAP_PROP_FRAME_WIDTH))
        alto  = int(self._captura.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps   = self._captura.get(cv2.CAP_PROP_FPS)
        logger.info(f"Cámara {self.config.indice_camara} iniciada: {ancho}x{alto} @ {fps:.1f} FPS")
        self.activa = True
        return True

    def leer_frame(self) -> Tuple[bool, Optional[np.ndarray]]:
        if not self.activa or self._captura is None:
            return False, None
        exito, frame = self._captura.read()
        return (exito, frame) if exito else (False, None)

    def liberar(self) -> None:
        if self._captura is not None:
            self._captura.release()
            self.activa = False
            logger.info(f"Cámara {self.config.indice_camara} liberada.")

    def __enter__(self):
        self.iniciar()
        return self

    def __exit__(self, *_):
        self.liberar()


# ── Utilidad: detectar cámaras disponibles ────────────────────────────────────

def detectar_camaras_disponibles(max_indices: int = 6) -> List[int]:
    """
    Prueba índices 0..max_indices-1 y devuelve los que abren correctamente.
    Rápido: abre y cierra sin leer frames.
    """
    disponibles = []
    for idx in range(max_indices):
        cap = cv2.VideoCapture(idx)
        if cap.isOpened():
            disponibles.append(idx)
            cap.release()
    logger.info(f"Cámaras detectadas: {disponibles}")
    return disponibles


# ── Cámara dual ───────────────────────────────────────────────────────────────

class CapturaDualVideo:
    """
    Gestiona hasta dos cámaras simultáneas en hilos separados.

    Uso:
        dual = CapturaDualVideo(config)
        dual.iniciar()                         # detecta cámaras automáticamente
        frame_p, frame_s = dual.leer_frames()  # frame_s es None si solo hay 1 cámara
        dual.liberar()

    Propiedades:
        dual.tiene_secundaria  → True si se inició la cámara secundaria
        dual.indice_principal  → índice de la cámara principal
        dual.indice_secundario → índice de la cámara secundaria (o None)
    """

    def __init__(self, config: ConfiguracionCamara, indice_secundario: Optional[int] = None):
        """
        Args:
            config:             ConfiguracionCamara con indice_camara = cámara principal.
            indice_secundario:  Forzar índice de secundaria. Si es None, se auto-detecta.
        """
        self._config        = config
        self._idx_forzado   = indice_secundario

        self._cap_principal:  Optional[cv2.VideoCapture] = None
        self._cap_secundaria: Optional[cv2.VideoCapture] = None

        self._frame_principal:  Optional[np.ndarray] = None
        self._frame_secundaria: Optional[np.ndarray] = None
        self._lock = threading.Lock()

        self._hilo_principal:  Optional[threading.Thread] = None
        self._hilo_secundaria: Optional[threading.Thread] = None
        self._activo = False

        self.indice_principal:  int           = config.indice_camara
        self.indice_secundario: Optional[int] = None
        self.tiene_secundaria:  bool          = False

    # ── Inicio ────────────────────────────────────────────────────────────────

    def iniciar(self) -> bool:
        """
        Abre la cámara principal (obligatoria) y la secundaria (si existe).
        Devuelve False si la principal no está disponible.
        """
        disponibles = detectar_camaras_disponibles()

        if not disponibles:
            logger.error("No se encontró ninguna cámara.")
            return False

        # Principal
        if self._config.indice_camara not in disponibles:
            self.indice_principal = disponibles[0]
            logger.warning(
                f"Cámara {self._config.indice_camara} no disponible. "
                f"Usando cámara {self.indice_principal}."
            )
        else:
            self.indice_principal = self._config.indice_camara

        self._cap_principal = self._abrir_camara(self.indice_principal)
        if self._cap_principal is None:
            return False

        # Secundaria — auto-detectar o usar índice forzado
        if self._idx_forzado is not None:
            if self._idx_forzado in disponibles and self._idx_forzado != self.indice_principal:
                self._cap_secundaria = self._abrir_camara(self._idx_forzado)
                if self._cap_secundaria:
                    self.indice_secundario = self._idx_forzado
                    self.tiene_secundaria  = True
            else:
                logger.warning(
                    f"Cámara secundaria forzada ({self._idx_forzado}) no disponible."
                )
        else:
            # Tomar la primera disponible distinta a la principal
            for idx in disponibles:
                if idx != self.indice_principal:
                    cap = self._abrir_camara(idx)
                    if cap:
                        self._cap_secundaria   = cap
                        self.indice_secundario = idx
                        self.tiene_secundaria  = True
                        break

        if self.tiene_secundaria:
            logger.info(
                f"Modo DUAL: principal={self.indice_principal}, "
                f"secundaria={self.indice_secundario}"
            )
        else:
            logger.info(
                f"Modo SIMPLE: solo cámara {self.indice_principal} "
                f"(no se detectó secundaria)."
            )

        # Lanzar hilos de captura
        self._activo = True
        self._hilo_principal = threading.Thread(
            target=self._capturar, args=(self._cap_principal, "principal"),
            daemon=True, name="cap-principal"
        )
        self._hilo_principal.start()

        if self.tiene_secundaria:
            self._hilo_secundaria = threading.Thread(
                target=self._capturar, args=(self._cap_secundaria, "secundaria"),
                daemon=True, name="cap-secundaria"
            )
            self._hilo_secundaria.start()

        return True

    # ── Captura en hilo ───────────────────────────────────────────────────────

    def _capturar(self, cap: cv2.VideoCapture, rol: str) -> None:
        """Hilo que lee frames continuamente y los guarda en el buffer."""
        while self._activo:
            exito, frame = cap.read()
            if not exito:
                continue
            with self._lock:
                if rol == "principal":
                    self._frame_principal = frame
                else:
                    self._frame_secundaria = frame

    # ── Lectura ───────────────────────────────────────────────────────────────

    def leer_frames(self) -> Tuple[Optional[np.ndarray], Optional[np.ndarray]]:
        """
        Devuelve (frame_principal, frame_secundaria).
        frame_secundaria es None si solo hay una cámara.
        """
        with self._lock:
            fp = self._frame_principal.copy()  if self._frame_principal  is not None else None
            fs = self._frame_secundaria.copy() if self._frame_secundaria is not None else None
        return fp, fs

    def leer_frame_principal(self) -> Tuple[bool, Optional[np.ndarray]]:
        """Compatibilidad con CapturaVideo.leer_frame()"""
        with self._lock:
            f = self._frame_principal
        if f is None:
            return False, None
        return True, f.copy()

    # ── Apertura con configuración ────────────────────────────────────────────

    def _abrir_camara(self, idx: int) -> Optional[cv2.VideoCapture]:
        cap = cv2.VideoCapture(idx)
        if not cap.isOpened():
            logger.error(f"No se pudo abrir la cámara {idx}.")
            return None
        cap.set(cv2.CAP_PROP_FRAME_WIDTH,  self._config.ancho_frame)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self._config.alto_frame)
        cap.set(cv2.CAP_PROP_FPS,          self._config.fps_objetivo)
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        logger.info(f"  Cámara {idx}: {w}x{h}")
        return cap

    # ── Limpieza ──────────────────────────────────────────────────────────────

    def liberar(self) -> None:
        self._activo = False
        for hilo in (self._hilo_principal, self._hilo_secundaria):
            if hilo and hilo.is_alive():
                hilo.join(timeout=2.0)
        for cap in (self._cap_principal, self._cap_secundaria):
            if cap:
                cap.release()
        logger.info("Cámaras liberadas.")

    def __enter__(self):
        self.iniciar()
        return self

    def __exit__(self, *_):
        self.liberar()
