@echo off
echo =========================================
echo  Camera Match Lab - Windows Build
echo =========================================

cd /d "%~dp0"

echo [1/3] Pruefe Python-Umgebung...
python --version

echo [2/3] Installiere Abhaengigkeiten...
pip install -r requirements.txt

echo [3/3] Erstelle portable EXE mit PyInstaller...
python -m PyInstaller --noconfirm --onefile --windowed ^
  --name Camera Match Lab ^
  --icon="icon.ico" ^
  --add-data "app\frontend;frontend" ^
  --hidden-import webview ^
  --hidden-import colour ^
  --hidden-import cv2 ^
  app\main.py

echo.
echo =========================================
echo  FERTIG! Deine Standalone EXE liegt in:
echo  dist\Camera Match Lab.exe
echo =========================================
pause
