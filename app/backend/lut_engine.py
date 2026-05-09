"""
lut_engine.py – Pure calculation logic, no UI, no stdin.

Core algorithm: Root-Polynomial Color Correction (Finlayson 2015)
instead of simple 3×3 linear matrix.  This yields exposure-invariant,
non-linear colour matching that handles saturation roll-off and
hue-shifts across luminance ranges far better than a linear fit.
"""
import os
import numpy as np
import cv2
import colour


# ---------------------------------------------------------------------------
# Custom log curves (not natively available in colour-science)
# ---------------------------------------------------------------------------

def _gp_log_encoding(x):
    x = np.asarray(x, dtype=np.float64)
    x = np.clip(x, 0.0, None)
    return np.where(
        x < 0.005,
        x * 8.0,
        np.clip(0.325 * np.log2(x * 11.0 + 0.01) + 0.512, 0.0, 1.0)
    )


def _gp_log_decoding(x):
    x = np.asarray(x, dtype=np.float64)
    x = np.clip(x, 0.0, 1.0)
    return np.where(
        x < 0.04,
        x / 8.0,
        np.clip((np.power(2.0, (x - 0.512) / 0.325) - 0.01) / 11.0, 0.0, None)
    )


# Pseudo-log curves for sources that are already display-referred
def _rec709_display_encoding(x):
    x = np.asarray(x, dtype=np.float64)
    return np.power(np.clip(x, 0.0, 1.0), 1.0 / 2.4)


def _rec709_display_decoding(x):
    x = np.asarray(x, dtype=np.float64)
    return np.power(np.clip(x, 0.0, 1.0), 2.4)


def _srgb_display_encoding(x):
    x = np.asarray(x, dtype=np.float64)
    return np.power(np.clip(x, 0.0, 1.0), 1.0 / 2.2)


def _srgb_display_decoding(x):
    x = np.asarray(x, dtype=np.float64)
    return np.power(np.clip(x, 0.0, 1.0), 2.2)


# ---------------------------------------------------------------------------
# Reliable custom curve registry (avoids LOG_ENCODINGS / LOG_DECODINGS
# confusion across different colour-science versions)
# ---------------------------------------------------------------------------

CUSTOM_LOG_CURVES = {
    'GP-Log':          {'encode': _gp_log_encoding,        'decode': _gp_log_decoding},
    'Rec709 (No Log)': {'encode': _rec709_display_encoding, 'decode': _rec709_display_decoding},
    'sRGB (No Log)':   {'encode': _srgb_display_encoding,   'decode': _srgb_display_decoding},
}

# Register encoding side so the names appear in get_log_profiles()
for _name, _fns in CUSTOM_LOG_CURVES.items():
    if _name not in colour.models.LOG_ENCODINGS:
        colour.models.LOG_ENCODINGS[_name] = _fns['encode']


# ---------------------------------------------------------------------------
# Display transform presets (for reference match mode)
# ---------------------------------------------------------------------------

DISPLAY_TRANSFORMS = {}


def _register_display_transform(name, decode_fn, encode_fn):
    DISPLAY_TRANSFORMS[name] = {'decode': decode_fn, 'encode': encode_fn}


def _decode_rec709(x):
    return colour.models.oetf_inverse_BT709(np.clip(np.asarray(x, dtype=np.float64), 0.0, 1.0))


def _encode_rec709(x):
    return np.clip(colour.models.oetf_BT709(np.clip(np.asarray(x, dtype=np.float64), 0.0, 100.0)), 0.0, 1.0)


def _decode_srgb(x):
    return colour.models.eotf_sRGB(np.clip(np.asarray(x, dtype=np.float64), 0.0, 1.0))


def _encode_srgb(x):
    return np.clip(colour.models.eotf_inverse_sRGB(np.clip(np.asarray(x, dtype=np.float64), 0.0, 100.0)), 0.0, 1.0)


def _decode_gamma24(x):
    return np.power(np.clip(np.asarray(x, dtype=np.float64), 0.0, 1.0), 2.4)


def _encode_gamma24(x):
    return np.power(np.clip(np.asarray(x, dtype=np.float64), 0.0, 100.0), 1.0 / 2.4)


def _decode_gamma22(x):
    return np.power(np.clip(np.asarray(x, dtype=np.float64), 0.0, 1.0), 2.2)


def _encode_gamma22(x):
    return np.power(np.clip(np.asarray(x, dtype=np.float64), 0.0, 100.0), 1.0 / 2.2)


_register_display_transform('Rec709 (BT.709)', _decode_rec709, _encode_rec709)
_register_display_transform('sRGB', _decode_srgb, _encode_srgb)
_register_display_transform('Gamma 2.4', _decode_gamma24, _encode_gamma24)
_register_display_transform('Gamma 2.2', _decode_gamma22, _encode_gamma22)


# ---------------------------------------------------------------------------
# Image helpers
# ---------------------------------------------------------------------------

def load_image(path: str):
    """Load TIFF/JPG/PNG and return (float32 0-1 image, display 8-bit image)."""
    img = cv2.imread(path, cv2.IMREAD_UNCHANGED)
    if img is None:
        raise ValueError(f"Cannot read image: {path}")
    # Drop alpha channel
    if len(img.shape) == 3 and img.shape[2] == 4:
        img = img[:, :, :3]

    is_16bit = img.dtype == np.uint16
    if is_16bit:
        img_float = (img / 65535.0).astype(np.float32)
    else:
        img_float = (img / 255.0).astype(np.float32)

    img_display = (np.clip(img_float, 0, 1) * 255).astype(np.uint8)
    return img_float, img_display


def image_to_jpeg_bytes(img_uint8_bgr: np.ndarray, quality: int = 85) -> bytes:
    """Encode a BGR uint8 image to JPEG bytes."""
    success, buf = cv2.imencode(".jpg", img_uint8_bgr, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not success:
        raise RuntimeError("Failed to encode image to JPEG")
    return buf.tobytes()


# ---------------------------------------------------------------------------
# ColorChecker extraction
# ---------------------------------------------------------------------------

# Default patch center positions (fractional, for a 600×400 warped rectangle)
# ColorChecker Video layout: 4 columns × 7 rows outer + 4 large gray blocks
DEFAULT_PATCH_CENTERS_FRAC = [
    [0.0533, 0.0850], [0.1533, 0.0950], [0.8467, 0.0925], [0.9433, 0.0900],
    [0.0533, 0.2275], [0.1517, 0.2275], [0.8467, 0.2325], [0.9467, 0.2250],
    [0.0533, 0.3650], [0.1567, 0.3650], [0.8467, 0.3700], [0.9467, 0.3675],
    [0.0567, 0.4975], [0.1533, 0.5050], [0.8467, 0.5075], [0.9467, 0.5050],
    [0.0567, 0.6350], [0.1567, 0.6400], [0.8467, 0.6400], [0.9500, 0.6375],
    [0.0533, 0.7700], [0.1533, 0.7750], [0.8467, 0.7750], [0.9467, 0.7700],
    [0.0533, 0.9100], [0.1550, 0.9100], [0.8500, 0.9075], [0.9467, 0.9100],
    [0.5000, 0.1400], [0.5000, 0.3750], [0.5000, 0.6250], [0.5000, 0.8625],
]

WARP_W, WARP_H = 600, 400


def warp_image(img_float: np.ndarray, corners: list) -> tuple:
    """
    Perspective-warp an image given 4 corner points.
    corners: [[x0,y0], [x1,y1], [x2,y2], [x3,y3]]  (TL, TR, BR, BL)

    Returns:
        warped_float  – float32 warped image
        warped_display – uint8 BGR warped image for preview
        default_patch_px – list of [px, py] pixel coordinates of patch centers
    """
    src = np.array(corners, dtype="float32")
    dst = np.array([
        [0, 0],
        [WARP_W - 1, 0],
        [WARP_W - 1, WARP_H - 1],
        [0, WARP_H - 1],
    ], dtype="float32")
    M = cv2.getPerspectiveTransform(src, dst)
    warped_float = cv2.warpPerspective(img_float, M, (WARP_W, WARP_H))
    warped_display = (np.clip(warped_float, 0, 1) * 255).astype(np.uint8)

    default_patch_px = [
        [int(fx * WARP_W), int(fy * WARP_H)]
        for fx, fy in DEFAULT_PATCH_CENTERS_FRAC
    ]
    return warped_float, warped_display, default_patch_px


def extract_patches(warped_float: np.ndarray, patch_centers_px: list, roi_size: int = 20) -> np.ndarray:
    """
    Average colour inside each patch ROI.
    Returns shape (N, 3) float32 array in RGB order (0-1).
    """
    patch_colors = []
    h, w = warped_float.shape[:2]
    for cx, cy in patch_centers_px:
        cy_min = max(0, cy - roi_size // 2)
        cy_max = min(h, cy + roi_size // 2)
        cx_min = max(0, cx - roi_size // 2)
        cx_max = min(w, cx + roi_size // 2)
        roi = warped_float[cy_min:cy_max, cx_min:cx_max]
        avg_color = roi.mean(axis=(0, 1))  # BGR
        patch_colors.append(avg_color)
    colors = np.array(patch_colors, dtype=np.float32)
    return colors[:, ::-1]  # BGR → RGB


# ---------------------------------------------------------------------------
# Log profiles
# ---------------------------------------------------------------------------

def get_log_profiles() -> list:
    return sorted(list(colour.models.LOG_ENCODINGS.keys()))


def get_display_gammas() -> list:
    return sorted(DISPLAY_TRANSFORMS.keys())


# ---------------------------------------------------------------------------
# Safe log decode / encode  (handles custom curves + fallback)
# ---------------------------------------------------------------------------

def _safe_log_decode(values: np.ndarray, curve_name: str) -> np.ndarray:
    """Decode log values to linear, using custom registry first, then colour-science."""
    if curve_name in CUSTOM_LOG_CURVES:
        return CUSTOM_LOG_CURVES[curve_name]['decode'](values)
    try:
        return colour.models.log_decoding(values, function=curve_name)
    except Exception:
        return np.power(np.clip(np.asarray(values, dtype=np.float64), 0.0, 1.0), 2.4)


def _safe_log_encode(values: np.ndarray, curve_name: str) -> np.ndarray:
    """Encode linear values to log, using custom registry first, then colour-science."""
    if curve_name in CUSTOM_LOG_CURVES:
        return CUSTOM_LOG_CURVES[curve_name]['encode'](values)
    try:
        return colour.models.log_encoding(values, function=curve_name)
    except Exception:
        return np.power(np.clip(np.asarray(values, dtype=np.float64), 0.0, 1.0), 1.0 / 2.4)


# ---------------------------------------------------------------------------
# Root-Polynomial Color Correction  (Finlayson et al. 2015)
#
# Instead of a simple 3×3+offset linear matrix, this expands the input RGB
# into a higher-dimensional space using root-polynomial terms:
#   degree 1: [R, G, B, 1]                          →  4 terms (= old approach)
#   degree 2: [R, G, B, √(RG), √(RB), √(GB), 1]    →  7 terms (default)
#
# Key property: *exposure-invariant* — all terms scale linearly with scene
# irradiance, so the correction matrix stays valid across different exposures.
# ---------------------------------------------------------------------------

def _root_polynomial_expand(RGB: np.ndarray, degree: int = 2) -> np.ndarray:
    """
    Expand RGB into root-polynomial basis (Finlayson 2015).
    Returns array with extra columns; offset column (1.0) added separately.
    """
    RGB = np.asarray(RGB, dtype=np.float64)
    R, G, B = RGB[..., 0], RGB[..., 1], RGB[..., 2]

    if degree <= 1:
        return np.stack([R, G, B], axis=-1)

    # Degree 2: add cross-channel root terms
    # np.abs prevents NaN from negative values after log decoding edge cases
    RG = np.sqrt(np.abs(R * G))
    RB = np.sqrt(np.abs(R * B))
    GB = np.sqrt(np.abs(G * B))
    return np.stack([R, G, B, RG, RB, GB], axis=-1)


def _weight_gray_patches(source: np.ndarray, target: np.ndarray,
                         weight: int = 10) -> tuple:
    """
    Amplify gray-patch influence by duplicating them.
    Gray patches are at indices 28-31 in each 32-patch chunk.
    This replaces the old np.diag(weights) approach which created
    an N×N matrix and didn't scale for Master-mode.
    """
    gray_indices = {28, 29, 30, 31}
    extra_s, extra_t = [], []
    for i in range(len(source)):
        if (i % 32) in gray_indices:
            for _ in range(weight - 1):  # original already counts once
                extra_s.append(source[i])
                extra_t.append(target[i])
    if extra_s:
        source = np.vstack([source, np.array(extra_s)])
        target = np.vstack([target, np.array(extra_t)])
    return source, target


def _compute_correction_matrix(source_lin: np.ndarray, target_lin: np.ndarray,
                               degree: int = 2, gray_weight: int = 10) -> np.ndarray:
    """
    Compute the root-polynomial correction matrix.
    Returns shape (terms+1, 3) matrix  (last row = offset).
    """
    src_w, tgt_w = _weight_gray_patches(source_lin, target_lin, gray_weight)
    src_w = np.clip(src_w, 1e-6, None)

    expanded = _root_polynomial_expand(src_w, degree=degree)
    # Add offset column (constant 1.0)
    expanded_pad = np.c_[expanded, np.ones(expanded.shape[0])]

    matrix, _, _, _ = np.linalg.lstsq(expanded_pad, tgt_w, rcond=None)
    return matrix


def _apply_correction(rgb_linear: np.ndarray, matrix: np.ndarray,
                      degree: int = 2) -> np.ndarray:
    """Apply pre-computed root-polynomial correction matrix."""
    rgb_clipped = np.clip(rgb_linear, 1e-6, None)
    expanded = _root_polynomial_expand(rgb_clipped, degree=degree)
    expanded_pad = np.c_[expanded, np.ones(expanded.shape[0])]
    return expanded_pad @ matrix


# ---------------------------------------------------------------------------
# LUT generation
# ---------------------------------------------------------------------------

_POLY_DEGREE = 2   # configurable: 1 = old linear, 2 = root-polynomial (recommended)


def build_lut(
    all_source_colors: np.ndarray,
    all_target_colors: np.ndarray,
    source_log_curve: str,
    target_log_curve: str,
    lut_name: str,
    output_path: str,
) -> dict:
    """
    Compute root-polynomial color correction and bake into a 65³ 3D LUT.
    Source and target are both in log space; output LUT maps source_log → target_log.
    """
    # 1. Log → Linear
    source_lin = _safe_log_decode(all_source_colors, source_log_curve)
    target_lin = _safe_log_decode(all_target_colors, target_log_curve)

    # 2. Compute correction matrix (root-polynomial, exposure-invariant)
    matrix = _compute_correction_matrix(source_lin, target_lin, degree=_POLY_DEGREE)

    # 3. Measure accuracy on training patches
    corrected = _apply_correction(source_lin, matrix, degree=_POLY_DEGREE)
    mse = float(np.mean((target_lin - corrected) ** 2))

    # 4. Bake into 65³ LUT
    lut = colour.LUT3D(size=65, name=lut_name)
    grid_lin = _safe_log_decode(lut.table, source_log_curve)
    flat_grid_lin = grid_lin.reshape(-1, 3)

    flat_transformed_lin = _apply_correction(flat_grid_lin, matrix, degree=_POLY_DEGREE)
    flat_transformed_lin = np.clip(flat_transformed_lin, 1e-6, 100.0)

    flat_transformed_log = _safe_log_encode(flat_transformed_lin, target_log_curve)
    flat_transformed_log = np.clip(flat_transformed_log, 0.0, 1.0)

    lut.table = flat_transformed_log.reshape((65, 65, 65, 3))
    colour.write_LUT(lut, output_path)
    return {"mse": mse, "output_file": output_path}


def build_display_lut(
    all_source_colors: np.ndarray,
    all_target_colors: np.ndarray,
    source_log_curve: str,
    display_transform: str,
    lut_name: str,
    output_path: str,
) -> dict:
    """
    Compute root-polynomial color correction for log→display matching
    and bake into a 65³ 3D LUT whose output is display-referred.
    """
    xform = DISPLAY_TRANSFORMS.get(display_transform)
    if xform is None:
        raise ValueError(f"Unknown display transform: {display_transform}")

    # 1. Decode source log → linear; decode target display → linear
    source_lin = _safe_log_decode(all_source_colors, source_log_curve)
    target_lin = xform['decode'](all_target_colors)

    # 2. Compute correction matrix
    matrix = _compute_correction_matrix(source_lin, target_lin, degree=_POLY_DEGREE)

    # 3. Measure accuracy
    corrected = _apply_correction(source_lin, matrix, degree=_POLY_DEGREE)
    mse = float(np.mean((target_lin - corrected) ** 2))

    # 4. Bake into 65³ LUT: source_log → display
    lut = colour.LUT3D(size=65, name=lut_name)
    grid_lin = _safe_log_decode(lut.table, source_log_curve)
    flat_grid_lin = grid_lin.reshape(-1, 3)

    flat_transformed_lin = _apply_correction(flat_grid_lin, matrix, degree=_POLY_DEGREE)
    flat_transformed_lin = np.clip(flat_transformed_lin, 1e-6, 100.0)

    flat_transformed_display = xform['encode'](flat_transformed_lin)
    flat_transformed_display = np.clip(flat_transformed_display, 0.0, 1.0)

    lut.table = flat_transformed_display.reshape((65, 65, 65, 3))
    colour.write_LUT(lut, output_path)
    return {"mse": mse, "output_file": output_path}
