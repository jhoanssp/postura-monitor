"""
Configuración central del sistema - v4.0
Rutas XDG-compatibles: funciona tanto en desarrollo (venv) como instalado (.deb).
"""

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# ── Detección de entorno ──────────────────────────────────────────────────────
def _get_config_dir() -> Path:
    """Directorio de configuración del usuario (XDG / AppData)."""
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home()))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    d = base / "postura-monitor"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _get_data_dir() -> Path:
    """Directorio de datos del usuario (logs, cache)."""
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home()))
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    d = base / "postura-monitor"
    d.mkdir(parents=True, exist_ok=True)
    return d


CONFIG_DIR = _get_config_dir()
DATA_DIR   = _get_data_dir()

# ── Cargar .env del usuario (solo contiene TELEGRAM_CHAT_ID) ─────────────────
_env_usuario = CONFIG_DIR / "config.env"
if _env_usuario.exists():
    load_dotenv(_env_usuario, override=True)

# También intentar .env de desarrollo (si existe junto al proyecto)
_env_dev = Path(__file__).resolve().parent.parent / ".env"
if _env_dev.exists() and not _env_usuario.exists():
    load_dotenv(_env_dev, override=False)

# ── Cargar credenciales integradas (ofuscadas) ────────────────────────────────
from config.credentials import (
    get_telegram_bot_token,
    get_supabase_url,
    get_supabase_anon_key,
)

# Las credenciales de la app se inyectan al arrancar si no están en el entorno
if not os.environ.get("TELEGRAM_BOT_TOKEN"):
    os.environ["TELEGRAM_BOT_TOKEN"] = get_telegram_bot_token()
if not os.environ.get("SUPABASE_URL"):
    os.environ["SUPABASE_URL"] = get_supabase_url()
if not os.environ.get("SUPABASE_ANON_KEY"):
    os.environ["SUPABASE_ANON_KEY"] = get_supabase_anon_key()

# ── Rutas de logs ─────────────────────────────────────────────────────────────
LOG_DIR  = DATA_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_PATH = LOG_DIR / "sistema.log"


# ── Dataclasses de configuración ──────────────────────────────────────────────

@dataclass
class ConfiguracionCamara:
    indice_camara: int = 0
    ancho_frame: int = 1280
    alto_frame: int = 720
    fps_objetivo: int = 30
    orientacion: str = "auto"


@dataclass
class UmbralesPostura:
    # FRONTAL (biomecánica ISO 11228)
    frontal_cuello_correcto_max: float = 15.0
    frontal_cuello_advertencia: float = 25.0
    frontal_cuello_incorrecto: float = 25.0
    frontal_espalda_correcto_max: float = 15.0
    frontal_espalda_advertencia: float = 25.0
    frontal_espalda_incorrecto: float = 25.0
    frontal_tronco_correcto_max: float = 15.0
    frontal_tronco_advertencia: float = 25.0
    frontal_tronco_incorrecto: float = 25.0
    frontal_encorvamiento_correcto_min: float = 160.0
    frontal_encorvamiento_advertencia_min: float = 130.0
    frontal_encorvamiento_incorrecto_min: float = 120.0
    frontal_inclinacion_lateral_correcto_max: float = 10.0
    frontal_inclinacion_lateral_advertencia: float = 15.0
    frontal_inclinacion_lateral_incorrecto: float = 15.0
    # LATERAL (LearnOpenCV)
    lateral_neck_correcto_max: float = 20.0
    lateral_neck_advertencia: float = 35.0
    lateral_neck_incorrecto: float = 35.0
    lateral_torso_correcto_max: float = 14.0
    lateral_torso_advertencia: float = 15.0
    lateral_torso_incorrecto: float = 15.0
    # ORIENTACIÓN
    hombros_dist_lateral_max: float = 0.40
    hombros_dist_frontal_min: float = 0.60
    # ALERTAS
    segundos_antes_alerta: int = 10
    cooldown_alerta_segundos: int = 120
    frames_confirmacion: int = 10
    tiempo_sedentarismo_minutos: int = 30
    sonido_alerta: bool = True


@dataclass
class ConfiguracionTelegram:
    token_bot: str = field(default_factory=lambda: os.environ.get("TELEGRAM_BOT_TOKEN", ""))
    chat_id: str   = field(default_factory=lambda: os.environ.get("TELEGRAM_CHAT_ID", ""))
    habilitado: bool = field(default_factory=lambda: bool(
        os.environ.get("TELEGRAM_BOT_TOKEN") and os.environ.get("TELEGRAM_CHAT_ID")
    ))
    timeout_segundos: int = 10


@dataclass
class ConfiguracionVisualizacion:
    mostrar_esqueleto: bool = True
    mostrar_angulos: bool = True
    mostrar_estado: bool = True
    mostrar_alertas: bool = True
    mostrar_fps: bool = True
    color_correcto: tuple = (0, 200, 0)
    color_advertencia: tuple = (0, 165, 255)
    color_incorrecto: tuple = (0, 0, 220)
    color_texto: tuple = (255, 255, 255)
    color_fondo_hud: tuple = (20, 20, 20)
    grosor_linea_esqueleto: int = 2
    radio_punto_clave: int = 5


@dataclass
class ModoEjecucion:
    debug: bool = True
    verbose_logs: bool = True


camara       = ConfiguracionCamara()
umbrales     = UmbralesPostura()
telegram     = ConfiguracionTelegram()
visualizacion = ConfiguracionVisualizacion()
modo         = ModoEjecucion()
