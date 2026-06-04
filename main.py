"""
SISTEMA DE MONITOREO DE POSTURA - v4.1
Punto de entrada principal. Compatible con ejecución directa y .deb instalado.
"""

import os

# ── FIX PUNTO 6: silenciar QFontDatabase warnings de Qt/OpenCV ──────────────
os.environ.setdefault("QT_LOGGING_RULES", "qt.qpa.fonts=false")
os.environ.setdefault("QT_QPA_PLATFORM", os.environ.get("QT_QPA_PLATFORM", "xcb"))

import argparse
import sys
import time
import signal
from pathlib import Path
import cv2

# ── FIX WINDOWS: forzar ruta de plugins de Qt (necesario para ejecutable) ──
if sys.platform == "win32" and getattr(sys, 'frozen', False):
    base = getattr(sys, '_MEIPASS', None)
    if base:
        plugin_path = os.path.join(base, 'PySide6', 'Qt', 'plugins')
        if os.path.isdir(plugin_path):
            os.environ['QT_QPA_PLATFORM_PLUGIN_PATH'] = plugin_path
        else:
            alt = os.path.join(base, 'PySide6', 'plugins')
            if os.path.isdir(alt):
                os.environ['QT_QPA_PLATFORM_PLUGIN_PATH'] = alt
# ─────────────────────────────────────────────────────────────────────────────

# Asegurar que el paquete raíz esté en el path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import camara, umbrales, telegram, visualizacion, modo
from core.captura_video import CapturaVideo
from core.deteccion_postura import DetectorPostura
from core.analisis_postura import AnalizadorPostura, EstadoPostura
from core.monitor_segundo_plano import MonitorSegundoPlano
from database.base_datos import BaseDatosPostura
from notifications.notificaciones import GestorNotificacionesTelegram
from utils.visualizacion_hud import HUDPostura
from utils.logger import crear_logger

logger = crear_logger("main")

# ... el resto de tu código (verificar_onboarding, ejecutar_modo_debug, etc.) se mantiene igual ...
# Asegúrate de copiar también las funciones que siguen desde tu archivo original.
