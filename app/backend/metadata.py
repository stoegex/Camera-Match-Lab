"""
metadata.py – Extract camera metadata and suggest log profiles.

Reads EXIF/MakerNote from images (via PIL) and optionally video files
(via exiftool subprocess fallback).  Maps camera make/model to known
log encoding curves.
"""

import io
import re
import struct
import subprocess
import tempfile
from pathlib import Path


# ---------------------------------------------------------------------------
# Camera → Log Curve mapping table (make + model pattern → curve name)
# ---------------------------------------------------------------------------

_CAMERA_LOG_MAP = [
    # Sony
    (r'SONY',       r'(ILCE|DSC|FX[369]|VENICE|PXW|BURANO)',   'S-Log3'),
    # Panasonic
    (r'PANASONIC',  r'(DC-S1|DC-S5|DC-GH|LUMIX|AU-EVA)',        'V-Log'),
    # Canon
    (r'CANON',      r'(EOS R5|EOS R3|EOS R6|C70|C300|C500)',   'Canon Log 2'),
    (r'CANON',      r'(EOS R|EOS 5D|EOS 1D)',                    'Canon Log'),
    # Blackmagic
    (r'BLACKMAGIC', r'(POCKET|URSA|CINEMA)',                     'Blackmagic Film'),
    # ARRI
    (r'ARRI',       r'ALEXA',                                     'ARRI LogC4'),
    (r'ARRI',       r'.*',                                        'LogC3'),
    # RED
    (r'RED',        r'(KOMODO|HELIUM|GEMINI|MONSTRO|DRAGON)',   'REDlogFilm'),
    # Nikon
    (r'NIKON',      r'(Z\s|D\d+)',                                 'N-Log'),
    # Leica
    (r'LEICA',      r'(SL|Q[23]|M1)',                              'L-Log'),
    # Fujifilm
    (r'FUJIFILM',   r'(X-T|X-H|X-PRO|GFX)',                        'F-Log2'),
    (r'FUJIFILM',   r'.*',                                          'F-Log'),
    # GoPro
    (r'GOPRO',      r'HERO',                                       'GP-Log2'),
    (r'GOPRO',      r'.*',                                          'GP-Log'),
    # DJI
    (r'DJI',        r'(INSPIRE|MAVIC|RONIN)',                      'D-Log'),
    # Apple
    (r'APPLE',      r'(IPHONE|IPAD)',                               'Apple Log'),
]

# Fallback: no known log curve
_DEFAULT_FALLBACK = 'Rec709 (No Log)'


def _match_log_curve(make: str, model: str) -> str | None:
    """Try to find a known log curve for the given camera make/model."""
    if not make and not model:
        return None
    make_upper = make.upper().strip()
    model_upper = model.upper().strip()
    for make_pat, model_pat, curve in _CAMERA_LOG_MAP:
        if re.search(make_pat, make_upper) and re.search(model_pat, model_upper):
            return curve
    return None


# ---------------------------------------------------------------------------
# Metadata extraction from uploaded file data (bytes)
# ---------------------------------------------------------------------------

def extract_metadata_from_bytes(data: bytes, filename: str = '') -> dict:
    """
    Extract camera make/model from image bytes (PIL fallback) or a temporary
    file via exiftool.

    Returns dict with keys: make, model, suggested_log, software, iso,
    color_space, exif_note.
    """
    ext = Path(filename).suffix.lower() if filename else ''
    result = {
        'make': '', 'model': '', 'suggested_log': '',
        'software': '', 'iso': '', 'color_space': '', 'exif_note': '',
    }

    # Try PIL first (works for TIFF, JPEG, PNG)
    make, model = _try_pil_exif(data)
    if make or model:
        result['make'] = make or ''
        result['model'] = model or ''
        result['suggested_log'] = _match_log_curve(make or '', model or '') or ''
        return result

    # Try exiftool for video files
    if ext in ('.mov', '.mp4', '.mxf', '.r3d', '.braw', '.ari', '.mts', '.m2ts'):
        exif_data = _try_exiftool(data, ext)
        if exif_data:
            result.update(exif_data)
            return result

    return result


# ---------------------------------------------------------------------------
# PIL-based EXIF extraction (image files)
# ---------------------------------------------------------------------------

def _try_pil_exif(data: bytes) -> tuple:
    """Try to read EXIF from image bytes using PIL. Returns (make, model)."""
    try:
        from PIL import Image
        from PIL.ExifTags import Base as ExifTags
    except ImportError:
        return '', ''

    try:
        img = Image.open(io.BytesIO(data))
        exif = img.getexif()
        if not exif:
            return '', ''
        make = str(exif.get(271, '')).strip()
        model = str(exif.get(272, '')).strip()
        return make, model
    except Exception:
        return '', ''


# ---------------------------------------------------------------------------
# exiftool-based metadata extraction (video files)
# ---------------------------------------------------------------------------

def _try_exiftool(data: bytes, ext: str) -> dict | None:
    """Write data to a temp file and call exiftool. Returns dict or None."""
    try:
        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tf:
            tf.write(data)
            tmp_path = tf.name
    except Exception:
        return None

    try:
        result = subprocess.run(
            ['exiftool', '-json', '-n',
             '-Make', '-Model', '-Software', '-ISO',
             '-ColorSpace', '-Gamma', '-PictureMode',
             tmp_path],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return None

        import json
        tags = json.loads(result.stdout)
        if not tags:
            return None
        tag = tags[0]

        make = str(tag.get('Make', '')).strip()
        model = str(tag.get('Model', '')).strip()
        return {
            'make': make,
            'model': model,
            'software': str(tag.get('Software', '')).strip(),
            'iso': str(tag.get('ISO', '')).strip(),
            'color_space': str(tag.get('ColorSpace', '')).strip(),
            'suggested_log': _match_log_curve(make, model) or '',
            'exif_note': _parse_picture_mode(tag),
        }
    except (FileNotFoundError, subprocess.TimeoutExpired, json.JSONDecodeError):
        return None
    finally:
        try:
            Path(tmp_path).unlink(missing_ok=True)
        except Exception:
            pass


def _parse_picture_mode(tag: dict) -> str:
    """Extract gamma/picture-profile hint from MakerNote-style tags."""
    hints = []
    for key in ('PictureMode', 'PictureProfile', 'Gamma', 'CreativeStyle'):
        val = tag.get(key, '')
        if val:
            hints.append(f'{key}={val}')
    return '; '.join(hints)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def suggest_log_for_camera(make: str, model: str) -> str | None:
    """Given camera make and model strings, return the suggested log curve."""
    curve = _match_log_curve(make, model)
    return curve if curve else None
