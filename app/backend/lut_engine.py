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


def _gp_log2_encoding(x):
    """
    Encode linear Rec.2020 values using GoPro's documented Log Base 600 curve.

    Reference:
    https://gopro.github.io/labs/log/
    """
    x = np.asarray(x, dtype=np.float64)
    x = np.clip(x, 0.0, None)
    return np.log(x * 599.0 + 1.0) / np.log(600.0)


def _gp_log2_decoding(x):
    """Decode GP-Log2 code values to linear Rec.2020 values."""
    x = np.asarray(x, dtype=np.float64)
    x = np.clip(x, 0.0, 1.0)
    return (np.power(600.0, x) - 1.0) / 599.0


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
    'GP-Log2':         {'encode': _gp_log2_encoding,       'decode': _gp_log2_decoding},
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
# ColorChecker auto-detection
# ---------------------------------------------------------------------------

def detect_colorchecker(img_float_bgr: np.ndarray) -> list | None:
    """
    Auto-detect ColorChecker chart corners in the image.

    Uses local color-variance scanning to find the chart region, then Hough
    line detection to refine the grid boundaries.

    Returns:
        list of [[x,y]*4] normalized corners (TL,TR,BR,BL) or None on failure.
    """
    h, w = img_float_bgr.shape[:2]
    if h < 100 or w < 100:
        return None

    # 1. Downsample for speed
    target_w = 1200
    scale = min(target_w / w, 1.0)
    small = cv2.resize(img_float_bgr, (int(w * scale), int(h * scale)))
    sh, sw = small.shape[:2]
    rgb_small = small[:, :, ::-1]  # BGR → RGB    (already float 0-1)

    # 2. Local colour variance – the chart grid has high variance
    ksize = 15
    sq_sum = cv2.blur(rgb_small ** 2, (ksize, ksize), borderType=cv2.BORDER_REPLICATE)
    mean_sum = cv2.blur(rgb_small, (ksize, ksize), borderType=cv2.BORDER_REPLICATE)
    local_var = (sq_sum[:, :, 0] - mean_sum[:, :, 0] ** 2 +
                 sq_sum[:, :, 1] - mean_sum[:, :, 1] ** 2 +
                 sq_sum[:, :, 2] - mean_sum[:, :, 2] ** 2) / 3.0

    # 3. Scan for window with maximum total variance
    win_w = int(sw * 0.45)
    win_h = int(sh * 0.60)
    step = int(min(win_w, win_h) * 0.12)
    best, best_y, best_x = 0.0, 0, 0
    for y in range(0, sh - win_h, step):
        for x in range(0, sw - win_w, step):
            score = float(local_var[y:y + win_h, x:x + win_w].sum())
            if score > best:
                best, best_y, best_x = score, y, x

    # 4. Try Hough line refinement within the best window
    margin = int(max(win_w, win_h) * 0.25)
    ry1 = max(0, best_y - margin)
    ry2 = min(sh, best_y + win_h + margin)
    rx1 = max(0, best_x - margin)
    rx2 = min(sw, best_x + win_w + margin)

    gray_region = (rgb_small[ry1:ry2, rx1:rx2, :].mean(axis=2) * 255).astype(np.uint8)
    corners_norm = None

    for low_t in (25, 45, 70):
        edges = cv2.Canny(gray_region, low_t, low_t * 3)
        lines = cv2.HoughLinesP(edges, 1, np.pi / 180, threshold=60,
                                minLineLength=40, maxLineGap=30)
        if lines is None:
            continue

        h_vals, v_vals = [], []
        for line in lines:
            x1_l, y1_l, x2_l, y2_l = line[0]
            dx, dy = abs(x2_l - x1_l), abs(y2_l - y1_l)
            if dx + dy < 15:
                continue
            if dx > dy * 3.0:
                h_vals.extend([y1_l, y2_l])
            elif dy > dx * 3.0:
                v_vals.extend([x1_l, x2_l])

        if len(h_vals) < 6 or len(v_vals) < 3:
            continue

        hv, vv = np.array(h_vals), np.array(v_vals)
        top_l = ry1 + float(np.percentile(hv, 3))
        bot_l = ry1 + float(np.percentile(hv, 97))
        left_l = rx1 + float(np.percentile(vv, 3))
        right_l = rx1 + float(np.percentile(vv, 97))

        aspect = (right_l - left_l) / max(bot_l - top_l, 1)
        if 0.25 < aspect < 1.6 and (right_l - left_l) > sw * 0.08:
            corners_norm = [
                [left_l / sw, top_l / sh],
                [right_l / sw, top_l / sh],
                [right_l / sw, bot_l / sh],
                [left_l / sw, bot_l / sh],
            ]
            break

    # 5. Fallback – use the variance window with a 5 % inset
    if corners_norm is None:
        inset = 0.05
        left = (best_x + win_w * inset) / sw
        right = (best_x + win_w * (1 - inset)) / sw
        top = (best_y + win_h * inset) / sh
        bottom = (best_y + win_h * (1 - inset)) / sh
        corners_norm = [[left, top], [right, top], [right, bottom], [left, bottom]]

    # 6. Remap coordinates back to original image (the down-sampled coords are
    #    already normalized to 0-1, so they work for the original image too)
    return [[float(x), float(y)] for x, y in corners_norm]

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

def _apply_idw_interpolation(source_lin: np.ndarray, target_lin: np.ndarray, grid_lin: np.ndarray, gray_weight: int = 10, p: float = 2.0) -> np.ndarray:
    """
    1. Base mapping is Identity (no 3x3 matrix) to prevent non-linear color flipping (blue/dark issues).
    2. Calculates exact residual vectors for each patch.
    3. Uses Inverse Distance Weighting (IDW) to smoothly interpolate residuals across the grid.
    Returns the transformed grid in empirical RGB space.
    """
    # 1. Base Mapping is Identity
    mapped_src = source_lin
    base_grid = grid_lin

    # 2. Residuals (exact error for each patch)
    residuals = target_lin - mapped_src

    # 3. Inverse Distance Weighting Interpolation
    # Compute squared Euclidean distance from every grid point to every mapped patch
    # grid: (G, 3), mapped_src: (N, 3) -> diff: (G, N, 3)
    diff = base_grid[:, np.newaxis, :] - mapped_src[np.newaxis, :, :]
    dist_sq = np.sum(diff**2, axis=2)
    dist_sq = np.maximum(dist_sq, 1e-8)  # prevent division by zero

    # Calculate weights (1 / d^p)
    weights = 1.0 / (dist_sq ** (p / 2.0))
    weight_sum = np.sum(weights, axis=1, keepdims=True)
    weights_norm = weights / weight_sum

    # Interpolate residuals and apply to base grid
    grid_residuals = weights_norm @ residuals
    final_grid = base_grid + grid_residuals

    return final_grid


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


# ---------------------------------------------------------------------------
# Root-Polynomial Expansion  (Finlayson et al. 2015)
# ---------------------------------------------------------------------------

def _expand_root_polynomial(rgb: np.ndarray, degree: int = 2) -> np.ndarray:
    """
    Expand RGB to root-polynomial terms of the given degree.
    degree 1: [R, G, B, 1]                        → 4 terms  (linear matrix)
    degree 2: [R, G, B, sqrt(RG), sqrt(RB), sqrt(GB), 1]  → 7 terms
    All terms scale linearly with scene irradiance → exposure-invariant.
    """
    r, g, b = rgb[:, 0:1], rgb[:, 1:2], rgb[:, 2:3]
    terms = [r, g, b]
    if degree >= 2:
        terms.append(np.sqrt(np.maximum(r * g, 0.0)))
        terms.append(np.sqrt(np.maximum(r * b, 0.0)))
        terms.append(np.sqrt(np.maximum(g * b, 0.0)))
    terms.append(np.ones_like(r))
    return np.hstack(terms)


# ---------------------------------------------------------------------------
# Display transform helpers  (for reference-match mode)
# ---------------------------------------------------------------------------

def _apply_display_decode(values: np.ndarray, transform_name: str) -> np.ndarray:
    """Decode display-referred values to scene-linear."""
    x = np.clip(np.asarray(values, dtype=np.float64), 0.0, 1.0)
    if transform_name in DISPLAY_TRANSFORMS:
        return DISPLAY_TRANSFORMS[transform_name]['decode'](x)
    return np.power(x, 2.4)


def _apply_display_encode(values: np.ndarray, transform_name: str) -> np.ndarray:
    """Encode scene-linear values to display-referred."""
    x = np.clip(np.asarray(values, dtype=np.float64), 1e-6, 100.0)
    if transform_name in DISPLAY_TRANSFORMS:
        return np.clip(DISPLAY_TRANSFORMS[transform_name]['encode'](x), 0.0, 1.0)
    return np.clip(np.power(x, 1.0 / 2.4), 0.0, 1.0)


# ---------------------------------------------------------------------------
# LUT generation
# ---------------------------------------------------------------------------

_POLY_DEGREE = 2   # 2 = root-polynomial (Finlayson 2015) — exposure-invariant, handles non-linearities


def _reference_neutral_indices(patch_count: int) -> np.ndarray:
    """Return the four large neutral patches from every 32-patch chart."""
    return np.array(
        [i for i in range(patch_count) if (i % 32) in {28, 29, 30, 31}],
        dtype=np.int64,
    )


def _prepare_reference_tone_curve(
    source_rgb: np.ndarray,
    target_rgb: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Build a monotonic code-value tone curve from the large neutral patches.

    Reference screenshots already contain their final display rendering. Fitting
    the measured code values directly preserves the complete source-to-look
    relationship and prevents unconstrained polynomial fits from producing
    reversed tones.
    """
    neutral_indices = _reference_neutral_indices(len(source_rgb))
    if len(neutral_indices) < 4:
        raise ValueError("Reference matching requires a complete 32-patch chart")

    source_neutral = np.mean(source_rgb[neutral_indices], axis=1)
    target_neutral = target_rgb[neutral_indices]
    order = np.argsort(source_neutral)

    source_knots = np.concatenate(([0.0], source_neutral[order], [1.0]))
    target_knots = np.vstack((np.zeros(3), target_neutral[order], np.ones(3)))

    # Merge nearly identical source values before interpolation.
    unique_source = []
    unique_target = []
    for value, rgb in zip(source_knots, target_knots):
        if unique_source and abs(value - unique_source[-1]) < 1e-6:
            unique_target[-1] = (unique_target[-1] + rgb) * 0.5
        else:
            unique_source.append(float(value))
            unique_target.append(np.asarray(rgb, dtype=np.float64))

    source_knots = np.asarray(unique_source, dtype=np.float64)
    target_knots = np.asarray(unique_target, dtype=np.float64)

    # Sampling noise must not make a neutral ramp reverse direction.
    target_knots = np.maximum.accumulate(target_knots, axis=0)
    target_knots = np.clip(target_knots, 0.0, 1.0)
    return source_knots, target_knots


def _apply_reference_tone_curve(
    values: np.ndarray,
    source_knots: np.ndarray,
    target_knots: np.ndarray,
) -> np.ndarray:
    values = np.clip(np.asarray(values, dtype=np.float64), 0.0, 1.0)
    return np.column_stack([
        np.interp(values, source_knots, target_knots[:, channel])
        for channel in range(3)
    ])


def _fit_reference_code_value_transform(
    source_rgb: np.ndarray,
    target_rgb: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Fit a stable source-code to final-display transform.

    Luminance is handled by the measured neutral tone curve. A regularized
    matrix maps only chroma deviations, so it cannot bend or reverse the
    neutral axis.
    """
    source_knots, target_knots = _prepare_reference_tone_curve(source_rgb, target_rgb)
    source_luma = np.mean(source_rgb, axis=1)
    base_target = _apply_reference_tone_curve(source_luma, source_knots, target_knots)
    source_chroma = source_rgb - source_luma[:, np.newaxis]
    target_residual = target_rgb - base_target

    gram = source_chroma.T @ source_chroma
    ridge = max(float(np.trace(gram)) / 300.0, 1e-8)
    chroma_matrix = np.linalg.solve(
        gram + ridge * np.eye(3),
        source_chroma.T @ target_residual,
    )
    return source_knots, target_knots, chroma_matrix


def _apply_reference_code_value_transform(
    rgb: np.ndarray,
    source_knots: np.ndarray,
    target_knots: np.ndarray,
    chroma_matrix: np.ndarray,
) -> np.ndarray:
    rgb = np.clip(np.asarray(rgb, dtype=np.float64), 0.0, 1.0)
    luma = np.mean(rgb, axis=1)
    base_target = _apply_reference_tone_curve(luma, source_knots, target_knots)
    chroma = rgb - luma[:, np.newaxis]
    return np.clip(base_target + chroma @ chroma_matrix, 0.0, 1.0)


def _normalize_black_points(source_lin: np.ndarray, target_lin: np.ndarray):
    """
    Shift both source and target so their black points are at zero.
    Uses the 5th percentile as a robust estimate of the black level.
    This ensures the LUT's (0,0,0) entry maps to near-black output.
    """
    src_black = float(np.percentile(source_lin, 5))
    tgt_black = float(np.percentile(target_lin, 5))
    src_norm = source_lin - src_black
    tgt_norm = target_lin - tgt_black
    return np.maximum(src_norm, 0.0), np.maximum(tgt_norm, 0.0), src_black, tgt_black


def build_lut(
    all_source_colors: np.ndarray,
    all_target_colors: np.ndarray,
    source_log_curve: str,
    target_log_curve: str,
    lut_name: str,
    output_path: str,
) -> dict:
    """
    Single / Master LUT: source-log → target-log.
    Pipeline: log → linear, black-point normalization, weighted root-polynomial
    matrix (no offset), denormalize, linear → target-log.
    """
    source_rgb = np.clip(np.asarray(all_source_colors, dtype=np.float64), 0.0, 1.0)
    target_rgb = np.clip(np.asarray(all_target_colors, dtype=np.float64), 0.0, 1.0)

    # 1. Decode log to scene-linear
    source_lin = _safe_log_decode(source_rgb, source_log_curve)
    target_lin = _safe_log_decode(target_rgb, target_log_curve)

    # 2. Black-point normalization — ensures (0,0,0) → (0,0,0)
    source_n, target_n, src_black, tgt_black = _normalize_black_points(source_lin, target_lin)

    # 3. Weight gray patches
    source_w, target_w = _weight_gray_patches(source_n, target_n, weight=10)

    # 4. Root-polynomial expansion WITHOUT offset term (all-ones removed)
    expanded = _expand_root_polynomial(source_w, degree=_POLY_DEGREE)[:, :-1]
    M, _, _, _ = np.linalg.lstsq(expanded.astype(np.float64), target_w.astype(np.float64), rcond=None)

    # 5. Measure accuracy on original patches
    expanded_src = _expand_root_polynomial(source_n, degree=_POLY_DEGREE)[:, :-1]
    predicted = np.dot(expanded_src, M)
    mse = float(np.mean((target_n - predicted) ** 2))

    # 6. Build 65³ LUT grid
    lut = colour.LUT3D(size=65, name=lut_name)
    grid_rgb = lut.table.reshape(-1, 3)

    grid_lin = _safe_log_decode(grid_rgb, source_log_curve)
    grid_n = np.maximum(grid_lin - src_black, 0.0)
    grid_expanded = _expand_root_polynomial(grid_n, degree=_POLY_DEGREE)[:, :-1]
    grid_transformed = np.dot(grid_expanded, M)
    grid_transformed = np.maximum(grid_transformed + tgt_black, 1e-6)
    grid_transformed = np.clip(grid_transformed, 1e-6, 100.0)

    grid_log = _safe_log_encode(grid_transformed, target_log_curve)
    grid_log = np.clip(grid_log, 0.0, 1.0)

    lut.table = grid_log.reshape((65, 65, 65, 3))
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
    Reference-Match LUT: source-log → display-referred.

    Both screenshots are sampled in their stored code values because the target
    image already contains the complete creative rendering. A measured monotonic
    neutral-axis curve plus a regularized chroma matrix preserves that empirical
    source-to-look relationship without allowing the fit to reverse tones.
    """
    source_rgb = np.clip(np.asarray(all_source_colors, dtype=np.float64), 0.0, 1.0)
    ref_rgb = np.clip(np.asarray(all_target_colors, dtype=np.float64), 0.0, 1.0)

    source_knots, target_knots, chroma_matrix = _fit_reference_code_value_transform(
        source_rgb,
        ref_rgb,
    )
    predicted = _apply_reference_code_value_transform(
        source_rgb,
        source_knots,
        target_knots,
        chroma_matrix,
    )
    mse = float(np.mean((ref_rgb - predicted) ** 2))

    # Build the complete source-code → final-display transform.
    lut = colour.LUT3D(size=65, name=lut_name)
    grid_rgb = lut.table.reshape(-1, 3)
    grid_display = _apply_reference_code_value_transform(
        grid_rgb,
        source_knots,
        target_knots,
        chroma_matrix,
    )

    lut.table = grid_display.reshape((65, 65, 65, 3))
    colour.write_LUT(lut, output_path)
    return {
        "mse": mse,
        "output_file": output_path,
        "method": "code-value-tone-chroma",
        "tone_source": source_knots.tolist(),
        "tone_target": target_knots.tolist(),
    }
