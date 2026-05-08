#!/usr/bin/env bash
set -e
echo "========================================="
echo " Camera Match Lab - macOS Build"
echo "========================================="

cd "$(dirname "$0")"

# ── Abhängigkeiten nur installieren wenn nötig ──
echo "[1/4] Checking dependencies..."
pip install -r requirements.txt --quiet

# ── Alten Build aufräumen ──
rm -rf "dist/Camera Match Lab.app" "dist/Camera Match Lab" "dist/Camera Match Lab.zip"

echo "[2/4] Building .app with PyInstaller..."
pyinstaller --noconfirm --onedir --windowed \
  --name "Camera Match Lab" \
  --icon="icon.icns" \
  --add-data "app/frontend:frontend" \
  --collect-submodules colour \
  --exclude-module matplotlib \
  --exclude-module pandas \
  --exclude-module scipy \
  --exclude-module IPython \
  --exclude-module PIL \
  --exclude-module tkinter \
  --exclude-module xmlrpc \
  --osx-bundle-identifier "com.cameramatchlab.app" \
  app/main.py

# Rohen UNIX-Ordner entfernen, nur .app behalten
rm -rf "dist/Camera Match Lab"

echo "[3/4] Patching cv2/__init__.py for frozen compat..."
python3 -c "
import os
app = 'dist/Camera Match Lab.app'
init = os.path.join(app, 'Contents', 'Resources', 'cv2', '__init__.py')
shim = '''import sys as _sys
import os as _os
from importlib import util as _util
_so_path = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), \"..\", \"..\", \"Frameworks\", \"cv2\", \"cv2.abi3.so\")
if not _os.path.exists(_so_path):
    _so_path = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), \"cv2.abi3.so\")
_our_mod = _sys.modules.pop(\"cv2\", None)
_spec = _util.spec_from_file_location(\"cv2\", _so_path)
_native = _util.module_from_spec(_spec)
_spec.loader.exec_module(_native)
if _our_mod:
    for _k in dir(_native):
        if not _k.startswith(\"_\"):
            setattr(_our_mod, _k, getattr(_native, _k))
    _our_mod._native = _native
    _sys.modules[\"cv2\"] = _our_mod
del _sys, _os, _util, _so_path, _spec, _native, _our_mod
'''
with open(init, 'w') as f:
    f.write(shim)
print('OK')
"

echo "[4/4] Ad-hoc signing & creating ZIP..."
codesign --force --deep --sign - "dist/Camera Match Lab.app"
xattr -cr "dist/Camera Match Lab.app"
(cd dist && zip -ry "Camera Match Lab.zip" "Camera Match Lab.app")

echo ""
echo "========================================="
echo " DONE! dist/Camera Match Lab.zip"
echo "========================================="