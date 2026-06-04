# -*- mode: python ; coding: utf-8 -*-
import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

block_cipher = None
APP_ROOT = Path(SPECPATH).parent

# ========== DATOS Y BINARIOS ADICIONALES ==========
# MediaPipe
mediapipe_datas = collect_data_files("mediapipe")
mediapipe_bins = collect_dynamic_libs("mediapipe")

# PySide6 (lo que faltaba: plugins, translations, etc.)
pyside6_datas = collect_data_files("PySide6", include_py_files=False)   # recursos estáticos
pyside6_bins  = collect_dynamic_libs("PySide6")                         # DLLs internos

# Carpeta de imágenes del onboarding
img_dir = str(APP_ROOT / "onboarding" / "img")
onboarding_datas = [(img_dir, "onboarding/img")]

# Combinar todas las datas y binaries
all_datas = mediapipe_datas + pyside6_datas + onboarding_datas
all_binaries = mediapipe_bins + pyside6_bins

# ========== RUNTIME HOOK (fija QT_QPA_PLATFORM_PLUGIN_PATH) ==========
# Crear el archivo hook temporal en la carpeta packaging/hooks
hook_path = Path(SPECPATH) / "hooks" / "qt_fix_runtime.py"
hook_path.parent.mkdir(parents=True, exist_ok=True)
hook_content = '''import os, sys
if sys.platform == "win32" and getattr(sys, 'frozen', False):
    # PyInstaller extrae los archivos en sys._MEIPASS
    base = sys._MEIPASS
    # La ruta esperada de los plugins de Qt dentro del paquete
    plugin_path = os.path.join(base, 'PySide6', 'Qt', 'plugins')
    if os.path.isdir(plugin_path):
        os.environ['QT_QPA_PLATFORM_PLUGIN_PATH'] = plugin_path
    else:
        # fallback (estructura alternativa)
        alt = os.path.join(base, 'PySide6', 'plugins')
        if os.path.isdir(alt):
            os.environ['QT_QPA_PLATFORM_PLUGIN_PATH'] = alt
'''
hook_path.write_text(hook_content, encoding='utf-8')

# ========== ANÁLISIS ==========
a = Analysis(
    [str(APP_ROOT / "main.py")],
    pathex=[str(APP_ROOT)],
    binaries=all_binaries,
    datas=all_datas,
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
        # Módulos propios
        "config.credentials",
        "config.settings",
        "config.i18n",
        "core.captura_video",
        "core.deteccion_postura",
        "core.analisis_postura",
        "core.analizador_posturas",
        "core.detector_ausencia",
        "core.calibrador",
        "core.gestor_alertas",
        "core.monitor_segundo_plano",
        "core.bandeja",
        "database.base_datos",
        "database.supabase_client",
        "notifications.notificaciones",
        "notifications.local",
        "onboarding.estado",
        "onboarding.wizard",
        "onboarding.calibracion_widget",
        "utils.logger",
        "utils.visualizacion_hud",
    ],
    hookspath=[str(Path(SPECPATH) / 'hooks')],
    runtime_hooks=[str(hook_path)],   # ← se ejecuta al iniciar
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
