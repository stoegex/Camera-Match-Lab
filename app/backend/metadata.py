"""
metadata.py – Extract camera metadata and suggest log profiles.

Reads EXIF/MakerNote from images (via PIL) and optionally video files
(via exiftool subprocess fallback).  Maps camera make/model to known
log encoding curves.
"""

import io
import re
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
    (r'NIKON',      r'(Z\d)',                                       'N-Log'),
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
    (r'APPLE',      r'(IPHONE|IPAD)',                               'Apple Log Profile'),
]

# Regex patterns to detect log profiles by name in metadata text.
# Maps (case-insensitive regex, normalized colour‐science curve name).
# Searched BEFORE falling back to _CAMERA_LOG_MAP heuristics.
_LOG_NAME_PATTERNS = [
    # Sony
    (r'S-Log3',    'S-Log3'),
    (r'S-Log2',    'S-Log2'),
    (r'S-Log(?!\d)', 'S-Log'),
    # Canon
    (r'Canon\s*Log\s*3', 'Canon Log 3'),
    (r'Canon\s*Log\s*2', 'Canon Log 2'),
    (r'Canon\s*Log',     'Canon Log'),
    # Panasonic
    (r'V-Log(?:\s*L)?',  'V-Log'),
    # Fujifilm
    (r'F-Log2',     'F-Log2'),
    (r'F-Log(?!\d)','F-Log'),
    # Nikon
    (r'N-Log',      'N-Log'),
    # Leica
    (r'L-Log',      'L-Log'),
    # DJI
    (r'D-Log\s*M',  'D-Log'),
    (r'D-Log(?!\s*M)', 'D-Log'),
    # GoPro – stored as GPLOG2 / GPLOG in metadata
    (r'GP\s*-?\s*Log2', 'GP-Log2'),
    (r'GP\s*-?\s*Log(?!\d)', 'GP-Log'),
    # Blackmagic
    (r'Blackmagic\s*Film\s*Gen\s*\d', 'Blackmagic Film'),
    (r'Blackmagic\s*Film',            'Blackmagic Film'),
    # ARRI
    (r'ARRI\s*Log\s*C4', 'ARRI LogC4'),
    (r'ARRI\s*Log\s*C3', 'ARRI LogC3'),
    (r'LogC4',           'ARRI LogC4'),
    (r'LogC3',           'ARRI LogC3'),
    # RED
    (r'REDlogFilm',  'REDlogFilm'),
    (r'REDlog3G10',  'Log3G10'),
    (r'REDLog',      'REDLog'),
    # Apple
    (r'Apple\s*Log', 'Apple Log Profile'),
    # Generic fallbacks (AVC-Intra, Cineon, etc.)
    (r'ACEScc',      'ACEScc'),
    (r'ACEScct',     'ACEScct'),
]

# Fallback: no known log curve
_DEFAULT_FALLBACK = 'Rec709 (No Log)'


def _search_log_in_tags(tags: dict) -> str | None:
    """Search all tag values (case-insensitive) for a known log profile name."""
    for key, val in tags.items():
        if not isinstance(val, str) or not val:
            continue
        for pattern, curve in _LOG_NAME_PATTERNS:
            if re.search(pattern, val, re.IGNORECASE):
                return curve
    return None


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

# Tags queried from exiftool – broad set covering all major manufacturers.
_EXIFTOOL_TAGS = [
    '-Make', '-Model', '-Software', '-ISO',
    '-ColorSpace', '-ColorMode',           # GoPro
    '-PhotoStyle', '-PictureMode',         # Panasonic
    '-PictureProfile', '-PictureStyle',    # Sony / Canon / general
    '-CreativeStyle',                      # Sony
    '-SLog', '-Gamma', '-HLG',
    '-CanonLog',                           # Canon
    '-CameraProfile', '-ProfileName',
    '-FilmMode',                           # Fuji
    '-CaptureGamma', '-CaptureGamut',      # Panasonic XML
    '-ColorTempKelvin',
]


def _try_exiftool(data: bytes, ext: str) -> dict | None:
    """Write data to a temp file and call exiftool. Returns dict or None."""
    try:
        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tf:
            tmp_path = tf.name
            tf.write(data)
    except Exception:
        return None

    try:
        result = subprocess.run(
            ['exiftool', '-json', *_EXIFTOOL_TAGS, tmp_path],
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

        # 1. Direct text search in all metadata values
        suggested = _search_log_in_tags(tag)

        # 2. Fallback: Make/Model heuristic
        if not suggested:
            suggested = _match_log_curve(make, model) or ''

        return {
            'make': make,
            'model': model,
            'software': str(tag.get('Software', '')).strip(),
            'iso': str(tag.get('ISO', '')).strip(),
            'color_space': str(tag.get('ColorSpace', '')).strip(),
            'suggested_log': suggested,
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
    for key in ('ColorMode', 'PhotoStyle', 'PictureMode', 'PictureProfile',
                'PictureStyle', 'FilmMode', 'CreativeStyle', 'CanonLog',
                'SLog', 'Gamma', 'HLG', 'CameraProfile', 'ProfileName',
                'CaptureGamma', 'CaptureGamut'):
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
