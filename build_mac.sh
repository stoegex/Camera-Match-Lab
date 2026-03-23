#!/usr/bin/env bash
set -e
echo "========================================="
echo " Camera Match Lab - macOS Build"
echo "========================================="

cd "$(dirname "$0")"

# ── Abhängigkeiten nur installieren wenn nötig ──
echo "[1/3] Checking dependencies..."
pip install -r requirements.txt --quiet
pip install dmgbuild --quiet

# ── Alten Build aufräumen ──
rm -rf "dist/Camera Match Lab.app" "dist/Camera Match Lab"

echo "[2/3] Building .app with PyInstaller..."
pyinstaller --noconfirm --onedir --windowed \
  --name "Camera Match Lab" \
  --icon="icon.icns" \
  --add-data "app/frontend:frontend" \
  --hidden-import webview \
  --hidden-import colour \
  --hidden-import cv2 \
  --collect-submodules colour \
  --collect-submodules cv2 \
  --exclude-module matplotlib \
  --exclude-module pandas \
  --exclude-module scipy \
  --exclude-module IPython \
  --exclude-module PIL \
  --exclude-module tkinter \
  --exclude-module unittest \
  --exclude-module xmlrpc \
  --exclude-module email \
  --strip \
  app/main.py

# Rohen UNIX-Ordner entfernen, nur .app behalten
rm -rf "dist/Camera Match Lab"

echo "[3/3] Creating DMG..."
# We generate the Python config file without 'EOF' quotes so Bash evaluates $PWD
cat << EOF > /tmp/dmg_settings.py
format = 'UDBZ'
size = None
files = ['$PWD/dist/Camera Match Lab.app']
symlinks = {'Applications': '/Applications'}
icon_size = 128
window_rect = ((200, 200), (600, 400))
default_view = 'icon-view'
EOF

dmgbuild -s /tmp/dmg_settings.py "Camera Match Lab" "dist/Camera Match Lab.dmg"
rm /tmp/dmg_settings.py

echo ""
echo "========================================="
echo " DONE! dist/Camera Match Lab.dmg"
echo "========================================="