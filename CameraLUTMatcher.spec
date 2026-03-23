# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_submodules

hiddenimports = ['webview', 'colour', 'cv2']
hiddenimports += collect_submodules('colour')
hiddenimports += collect_submodules('cv2')


a = Analysis(
    ['app/main.py'],
    pathex=[],
    binaries=[],
    datas=[('app/frontend', 'frontend')],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['matplotlib', 'pandas', 'scipy', 'IPython', 'PIL', 'tkinter', 'unittest', 'xmlrpc', 'email'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Camera Match Lab',
    debug=False,
    bootloader_ignore_signals=False,
    strip=True,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['icon.icns'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=True,
    upx=True,
    upx_exclude=[],
    name='Camera Match Lab',
)
app = BUNDLE(
    coll,
    name='Camera Match Lab.app',
    icon='icon.icns',
    bundle_identifier=None,
)
