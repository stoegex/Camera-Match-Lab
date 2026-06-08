# Camera Match Lab

Camera Match Lab is a desktop tool for creating camera-to-camera 3D LUTs from ColorChecker shots.

It is designed for matching one camera or log profile to another by sampling chart patches, solving a weighted color transform, and baking the result into a `.cube` LUT.

## Features

- **Single LUT mode** – match one source/target image pair
- **Master LUT mode** – combine multiple scene pairs for broader lighting coverage
- **Reference Match mode** – match source log directly to a display-referred reference screenshot
- **ColorChecker auto-detection** – automatically locate chart corners via variance scanning and Hough lines
- **Corner selection & patch fine-tuning** with manual undo and reset
- **Log profile selection** for source and target (built-in curves + GP-Log2)
- **Root-Polynomial correction** (Finlayson 2015) – 6-term expansion for exposure-invariant transforms
- **Black-point normalization** – ensures (0,0,0) maps cleanly to near-black output
- **Code-value tone-chroma transform** – preserves the full creative rendering of reference images
- 65^3 `.cube` LUT export

## Workflow

1. Load a source and target (or reference) image.
2. Mark the four outer ColorChecker corners, or use **Auto-Detect**.
3. Fine-tune the patch sample positions.
4. Choose source and target log profiles (or a project-standard label for Reference Match).
5. Generate and save the LUT.

For broader matching across lighting conditions, use Master mode and add multiple scene pairs.

## Supported Log Profiles

All built-in `colour-science` log curves, plus:

| Curve    | Description                          |
|----------|--------------------------------------|
| GP-Log   | GoPro Protune Log Base 113           |
| GP-Log2  | GoPro Log Base 600 (Labs)            |

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
  backend/         # Flask server, LUT engine, session management
  frontend/        # HTML, CSS, JS (desktop UI)
generate_lut.py    # CLI script-based workflow
build_mac.sh
build_windows.bat
```

## Notes

- The desktop app is the main product.
- `generate_lut.py` is the earlier script-based workflow supporting the same correction pipeline.
- Sample images and generated LUTs are ignored by Git via `.gitignore`.
