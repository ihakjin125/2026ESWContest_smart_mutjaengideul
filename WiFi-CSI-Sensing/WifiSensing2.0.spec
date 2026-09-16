# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files

source = Path(SPECPATH)
resources = (
    'app.ico', 'LICENSE', 'NOTICE.md', 'THIRD_PARTY_NOTICES.txt', 'LICENSE-C6.txt',
    'firmware/ESP-IDF-LICENSE.txt', 'edge_runtime.py', 'core.py', 'radio.py',
    'live_timing.py', 'signal_pipeline.py', 'cnn_runtime.py',
    'signal_processing/__init__.py', 'PI-사용방법.md',
)
datas = [(str(source / name), str(Path(name).parent)) for name in resources]
datas += [(str(source / 'firmware-c6/bin'), 'firmware-c6/bin')]
datas += collect_data_files('torch')
datas += collect_data_files('esptool')

a = Analysis(
    [str(source / 'app.py')],
    pathex=[str(source)], binaries=[], datas=datas,
    hiddenimports=['sklearn.ensemble._forest', 'sklearn.tree._utils'],
    hookspath=[], hooksconfig={}, runtime_hooks=[],
    excludes=[
        'tkinter', 'matplotlib', 'pandas', 'IPython', 'notebook', 'jupyter',
        'tensorflow', 'torchvision', 'torchaudio', 'cv2', 'numba', 'pytest',
        'PyQt5', 'PyQt6', 'PySide2', 'pyqtgraph.opengl',
        'PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets',
        'PySide6.QtQml', 'PySide6.QtQuick',
    ],
    noarchive=False, optimize=0,
)
# Qt requires the Windows ICU ABI. A same-named Poppler DLL on PATH is incompatible.
# Windows 10/11 provide the system version used by the unfrozen application.
a.binaries = [entry for entry in a.binaries
              if Path(entry[0]).name.lower() not in ('icuuc.dll', 'icudt78.dll')]
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name='WifiSensing2.0', debug=False, bootloader_ignore_signals=False,
    strip=False, upx=False, upx_exclude=[], runtime_tmpdir=None,
    console=False, disable_windowed_traceback=False, argv_emulation=False,
    target_arch=None, codesign_identity=None, entitlements_file=None,
    icon=[str(source / 'app.ico')],
)
