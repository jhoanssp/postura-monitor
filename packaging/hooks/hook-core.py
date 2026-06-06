# packaging/hooks/hook-core.py
# PyInstaller hook — incluye todos los submodulos del proyecto + sklearn + joblib
from PyInstaller.utils.hooks import collect_submodules, collect_data_files
import os

hiddenimports = (
    collect_submodules('core') +
    collect_submodules('config') +
    collect_submodules('database') +
    collect_submodules('notifications') +
    collect_submodules('onboarding') +
    collect_submodules('utils') +
    # ── Random Forest ───────────────────────────────────────────────────────
    collect_submodules('sklearn') +
    collect_submodules('sklearn.ensemble') +
    collect_submodules('sklearn.tree') +
    collect_submodules('sklearn.preprocessing') +
    collect_submodules('joblib') +
    ['sklearn.utils._cython_blas',
     'sklearn.neighbors.typedefs',
     'sklearn.neighbors.quad_tree',
     'sklearn.tree._utils']
)

# Incluir los archivos .pkl de los modelos RF en el ejecutable
datas = []
models_dir = os.path.join(os.path.dirname(__file__), '..', '..', 'models')
models_dir = os.path.normpath(models_dir)
if os.path.isdir(models_dir):
    datas += [(models_dir, 'models')]
