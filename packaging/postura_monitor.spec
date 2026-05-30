# -*- mode: python ; coding: utf-8 -*-
import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

block_cipher = None
APP_ROOT = Path(SPECPATH).parent

mediapipe_datas = collect_data_files("mediapipe")
img_dir = str(APP_ROOT / "onboarding" / "img")
onboarding_datas = [(img_dir, "onboarding/img")]
mediapipe_bins = collect_dynamic_libs("mediapipe")

a = Analysis(
    [str(APP_ROOT / "main.py")],
    pathex=[str(APP_ROOT)],
    binaries=mediapipe_bins,
    datas=mediapipe_datas + onboarding_datas,
    hiddenimports=[
        # Qt
        "PySide6.QtCore", "PySide6.QtGui", "PySide6.QtWidgets",
        # Mediapipe
        "mediapipe", "mediapipe.python", "mediapipe.python.solutions",
        "mediapipe.python.solutions.pose",
        "mediapipe.python.solutions.drawing_utils",
        # Matplotlib
        "matplotlib", "matplotlib.pyplot", "matplotlib.backends.backend_agg",
        # OpenCV
        "cv2",
        # Red
        "requests", "urllib3",
        # Supabase
        "supabase", "postgrest", "httpx",
        # Notificaciones
        "plyer", "plyer.platforms.linux.notification",
        "plyer.platforms.win.notification",
        # ── Módulos propios — TODOS explícitos ────────────────────────────────
        "config.credentials",
        "config.settings",
        "config.i18n",
        "core.captura_video",
        "core.deteccion_postura",
        "core.analisis_postura",
        "core.analizador_posturas",      # ← nuevo v4.4
        "core.detector_ausencia",        # ← nuevo v4.4
        "core.calibrador",               # ← nuevo v4.4
        "core.monitor_segundo_plano",
        "core.bandeja",
        "database.base_datos",
        "database.supabase_client",
        "notifications.notificaciones",
        "notifications.local",           # ← nuevo v4.4
        "onboarding.estado",
        "onboarding.wizard",
        "onboarding.calibracion_widget", # ← nuevo v4.4
        "utils.logger",
        "utils.visualizacion_hud",
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "scipy", "pandas", "IPython"],
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="postura-monitor",
    debug=False, strip=False, upx=True,
    console=False,
)

coll = COLLECT(
    exe, a.binaries, a.zipfiles, a.datas,
    strip=False, upx=True, upx_exclude=[],
    name="postura-monitor",
)
