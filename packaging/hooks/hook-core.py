from PyInstaller.utils.hooks import collect_submodules
hiddenimports = (
    collect_submodules('core') +
    collect_submodules('config') +
    collect_submodules('database') +
    collect_submodules('notifications') +
    collect_submodules('onboarding') +
    collect_submodules('utils')
)
