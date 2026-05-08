# Camera Match Lab

Camera Match Lab is a desktop tool for creating camera-to-camera 3D LUTs from ColorChecker shots.

It is designed for matching one camera or log profile to another by sampling chart patches, solving a weighted color transform, and baking the result into a `.cube` LUT.

## Features

- Single LUT mode for one source/target image pair
- Master LUT mode for combining multiple scene pairs
- ColorChecker corner selection and patch fine-tuning
- Source and target log profile selection
- 65^3 `.cube` LUT export
- Desktop UI built with Python, Flask, and pywebview

## Workflow

1. Load a source and target image.
2. Mark the four outer ColorChecker corners.
3. Fine-tune the patch sample positions.
4. Choose source and target log profiles.
5. Generate and save the LUT.

For broader matching across lighting conditions, use Master mode and add multiple scene pairs.
 
## Tech Stack

- Python
- Flask
- pywebview
- OpenCV
- NumPy
- colour-science
- PyInstaller

## Install

```bash
pip install -r requirements.txt
```

## Run

```bash
python app/main.py
```

## Build

macOS:

```bash
bash build_mac.sh
```

Windows:

```bat
build_windows.bat
```

## Project Structure

```text
app/
  main.py
  backend/
  frontend/
generate_lut.py
build_mac.sh
build_windows.bat
```

## Notes

- The desktop app is the main product.
- `generate_lut.py` is the earlier script-based workflow.
- Sample images and generated LUTs are ignored by Git via `.gitignore`.
