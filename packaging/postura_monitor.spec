# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec — Monitor de Postura v4
Funciona en Linux (para .deb) y Windows (para .exe)
Uso:
    pyinstaller packaging/postura_monitor.spec
"""

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
        # Qt / PySide6
        "PySide6.QtCore",
        "PySide6.QtGui",
        "PySide6.QtWidgets",
        # Mediapipe
        "mediapipe",
        "mediapipe.python",
        "mediapipe.python.solutions",
        "mediapipe.python.solutions.pose",
        "mediapipe.python.solutions.drawing_utils",
        # Matplotlib (requerido por mediapipe internamente)
        "matplotlib",
        "matplotlib.pyplot",
        "matplotlib.backends.backend_agg",
        # OpenCV headless
        "cv2",
        # Red
        "requests",
        "urllib3",
        # Supabase
        "supabase",
        "postgrest",
        "httpx",
        # Propios
        "config.credentials",
        "config.settings",
        "onboarding.estado",
        "onboarding.wizard",
        "core.captura_video",
        "core.deteccion_postura",
        "core.analisis_postura",
        "core.monitor_segundo_plano",
        "database.base_datos",
        "database.supabase_client",
        "notifications.notificaciones",
        "utils.logger",
        "utils.visualizacion_hud",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # NOTA: NO excluir matplotlib — mediapipe lo necesita internamente
    excludes=["tkinter", "scipy", "pandas", "IPython"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="postura-monitor",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="postura-monitor",
)
