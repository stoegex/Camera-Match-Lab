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
    """Load an image or extract the first frame from a video, return (float32 0-1 BGR, uint8 BGR)."""
    ext = os.path.splitext(path)[1].lower()
    if ext in ('.mp4', '.mov', '.mxf', '.mts', '.m2ts', '.avi'):
        return _extract_video_frame(path)

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


def _extract_video_frame(path: str):
    """Open a video file and return the first valid frame as (float32 BGR, uint8 BGR)."""
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        raise ValueError(f"Cannot open video: {path}")
    success, frame = cap.read()
    cap.release()
    if not success or frame is None:
        raise ValueError(f"No readable frame in video: {path}")
    frame_float = frame.astype(np.float32) / 255.0
    frame_uint8 = frame  # already uint8 BGR from VideoCapture
    return frame_float, frame_uint8


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

    Multi-strategy approach:
    1. Contour-based quadrilateral detection (primary)
    2. Color variance scanning + adaptive Hough lines (fallback)
    3. Sub-pixel corner refinement

    Returns:
        list of [[x,y]*4] normalized corners (TL,TR,BR,BL) or None on failure.
    """
    h, w = img_float_bgr.shape[:2]
    if h < 100 or w < 100:
        return None

    # Convert to uint8 for OpenCV operations
    img_uint8 = (np.clip(img_float_bgr, 0.0, 1.0) * 255).astype(np.uint8)
    gray = cv2.cvtColor(img_uint8, cv2.COLOR_BGR2GRAY)

    # CLAHE preprocessing – critical for low-contrast / unevenly lit charts
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
    gray_eq = clahe.apply(gray)

    # Try strategies at multiple scales (large → small chart in frame)
    for down in [1.0, 0.6, 0.4]:
        scale = min(down, 800.0 / max(w, h))
        if scale >= 1.0 and down < 1.0:
            continue
        corners = _try_detect_at_scale(img_float_bgr, gray_eq, w, h, scale)
        if corners is not None:
            return corners

    return None


def _try_detect_at_scale(img_float_bgr, gray_eq, orig_w, orig_h, scale):
    """Run contour and variance detection at a given downscale factor."""
    if scale < 0.99:
        nw, nh = int(orig_w * scale), int(orig_h * scale)
        small = cv2.resize(img_float_bgr, (nw, nh))
        gray_s = cv2.resize(gray_eq, (nw, nh))
    else:
        nw, nh = orig_w, orig_h
        small = img_float_bgr
        gray_s = gray_eq

    # Strategy 1: contour-based quadrilateral
    corners_px = _find_chart_quadrilateral(gray_s)
    if corners_px is not None:
        return [[x / nw, y / nh] for x, y in corners_px]

    # Strategy 2: variance + adaptive Hough
    corners_norm = _find_chart_variance_hough(small, nw, nh)
    if corners_norm is not None:
        return corners_norm

    return None


def _find_chart_quadrilateral(gray_eq):
    """
    Find the largest quadrilateral in the edge map of a CLAHE-equalized image.
    Uses adaptive threshold + morphological cleanup to isolate the chart border.
    """
    h, w = gray_eq.shape[:2]
    min_area = (w * h) * 0.04
    max_area = (w * h) * 0.90

    best_quad = None
    best_score = 0.0

    for block_size in (21, 31, 51):
        for c_val in (5, 11, 17):
            binary = cv2.adaptiveThreshold(
                gray_eq, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                cv2.THRESH_BINARY, block_size, c_val,
            )

            kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
            binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel, iterations=2)
            binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel, iterations=1)

            contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            for cnt in contours:
                area = float(cv2.contourArea(cnt))
                if area < min_area or area > max_area:
                    continue

                peri = cv2.arcLength(cnt, True)
                approx = cv2.approxPolyDP(cnt, 0.03 * peri, True)

                if len(approx) == 4:
                    pts = approx.reshape(4, 2)
                    test_area = float(cv2.contourArea(pts))
                    if test_area < min_area:
                        continue

                    # Verify convexity and reasonable aspect ratio
                    pts_sorted = _order_corners(pts)
                    tl, tr, br, bl = pts_sorted
                    quad_w = float(np.linalg.norm(np.array(tr) - np.array(tl)))
                    quad_h = float(np.linalg.norm(np.array(bl) - np.array(tl)))
                    if quad_w < 5 or quad_h < 5:
                        continue

                    aspect = quad_w / quad_h
                    if aspect < 0.35 or aspect > 1.8:
                        continue

                    # Score: prefer larger quads with aspect ratios close to CC Video (~0.57)
                    size_score = test_area / (w * h)
                    aspect_score = 1.0 - min(abs(aspect - 0.57) / 0.57, 1.0)
                    score = size_score * 0.6 + aspect_score * 0.4

                    if score > best_score:
                        best_score = score
                        best_quad = pts_sorted

    if best_quad is not None:
        tl, tr, br, bl = best_quad
        return [(float(tl[0]), float(tl[1])),
                (float(tr[0]), float(tr[1])),
                (float(br[0]), float(br[1])),
                (float(bl[0]), float(bl[1]))]
    return None


def _find_chart_variance_hough(small_float_bgr, sw, sh):
    """
    Fallback detection using local color-variance scanning to locate the
    high-texture chart region, then adaptive Hough line grid refinement.
    """
    rgb_small = small_float_bgr[:, :, ::-1]  # BGR → RGB (float 0-1)

    # Compute local color variance (larger kernel for robustness)
    ksize = max(11, int(min(sw, sh) * 0.025))
    ksize += 1 if ksize % 2 == 0 else 0  # ensure odd

    sq_sum = cv2.blur(rgb_small ** 2, (ksize, ksize), borderType=cv2.BORDER_REPLICATE)
    mean_sum = cv2.blur(rgb_small, (ksize, ksize), borderType=cv2.BORDER_REPLICATE)
    local_var = (sq_sum[:, :, 0] - mean_sum[:, :, 0] ** 2 +
                 sq_sum[:, :, 1] - mean_sum[:, :, 1] ** 2 +
                 sq_sum[:, :, 2] - mean_sum[:, :, 2] ** 2) / 3.0

    # Sliding window: try multiple aspect ratios matching CC variants
    aspect_pairs = [(0.50, 0.65), (0.40, 0.55), (0.55, 0.70)]

    best, best_y, best_x, best_ww, best_wh = 0.0, 0, 0, 0, 0
    for wa, ha in aspect_pairs:
        win_w = int(sw * wa)
        win_h = int(sh * ha)
        step = max(int(min(win_w, win_h) * 0.10), 4)
        for y in range(0, sh - win_h, step):
            for x in range(0, sw - win_w, step):
                score = float(local_var[y:y + win_h, x:x + win_w].sum())
                # Normalize by window area so different sizes are comparable
                score_norm = score / (win_w * win_h)
                if score_norm > best:
                    best = score_norm
                    best_y, best_x = y, x
                    best_ww, best_wh = win_w, win_h

    if best <= 0:
        return None

    # Expand slightly around the best window for edge detection
    margin = int(max(best_ww, best_wh) * 0.20)
    ry1 = max(0, best_y - margin)
    ry2 = min(sh, best_y + best_wh + margin)
    rx1 = max(0, best_x - margin)
    rx2 = min(sw, best_x + best_ww + margin)

    # Extract region for edge processing (with CLAHE)
    region_float = small_float_bgr[ry1:ry2, rx1:rx2, :]
    region_uint8 = (np.clip(region_float, 0.0, 1.0) * 255).astype(np.uint8)
    region_gray = cv2.cvtColor(region_uint8, cv2.COLOR_BGR2GRAY)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    region_eq = clahe.apply(region_gray)

    r_h, r_w = region_eq.shape[:2]
    min_line_len = max(r_w, r_h) // 10
    max_gap = max(r_w, r_h) // 20
    hough_thresh = max(30, min(r_w, r_h) // 8)

    for low_t in (15, 30, 50, 75):
        edges = cv2.Canny(region_eq, low_t, low_t * 3)
        lines = cv2.HoughLinesP(edges, 1, np.pi / 180, threshold=hough_thresh,
                                minLineLength=min_line_len, maxLineGap=max_gap)
        if lines is None:
            continue

        h_vals, v_vals = [], []
        for line in lines:
            x1_l, y1_l, x2_l, y2_l = line[0]
            dx, dy = abs(x2_l - x1_l), abs(y2_l - y1_l)
            if dx + dy < max(8, min_line_len // 2):
                continue
            if dx > dy * 2.5:
                h_vals.extend([y1_l, y2_l])
            elif dy > dx * 2.5:
                v_vals.extend([x1_l, x2_l])

        if len(h_vals) < 6 or len(v_vals) < 3:
            continue

        # Use median instead of percentile for outlier resistance
        hv, vv = np.array(h_vals), np.array(v_vals)
        h_med = float(np.median(hv))
        v_med = float(np.median(vv))
        h_mad = float(np.median(np.abs(hv - h_med))) * 1.4826
        v_mad = float(np.median(np.abs(vv - v_med))) * 1.4826

        # Filter outliers: keep lines within 2 sigma of median
        h_in = hv[np.abs(hv - h_med) < max(h_mad * 2.0, 10)]
        v_in = vv[np.abs(vv - v_med) < max(v_mad * 2.0, 10)]

        if len(h_in) < 4 or len(v_in) < 3:
            continue

        top_l = ry1 + float(np.percentile(h_in, 2))
        bot_l = ry1 + float(np.percentile(h_in, 98))
        left_l = rx1 + float(np.percentile(v_in, 2))
        right_l = rx1 + float(np.percentile(v_in, 98))

        cw, ch = right_l - left_l, bot_l - top_l
        if cw < sw * 0.06 or ch < sh * 0.06:
            continue

        aspect = cw / max(ch, 1)
        if 0.30 < aspect < 1.6:
            return [
                [left_l / sw, top_l / sh],
                [right_l / sw, top_l / sh],
                [right_l / sw, bot_l / sh],
                [left_l / sw, bot_l / sh],
            ]

    # Fallback – return the variance window directly (with 5 % inset)
    inset = 0.05
    left = (best_x + best_ww * inset) / sw
    right = (best_x + best_ww * (1 - inset)) / sw
    top = (best_y + best_wh * inset) / sh
    bottom = (best_y + best_wh * (1 - inset)) / sh
    return [[left, top], [right, top], [right, bottom], [left, bottom]]


def _order_corners(pts):
    """
    Order 4 corner points as [TL, TR, BR, BL] based on their spatial arrangement.
    TL = min(x+y), BR = max(x+y).  Remaining two sorted by x-coordinate for TR/BL.
    """
    pts = np.array(pts, dtype=np.float64).reshape(4, 2)
    s = pts.sum(axis=1)
    tl_idx = int(np.argmin(s))
    br_idx = int(np.argmax(s))
    tl = pts[tl_idx]
    br = pts[br_idx]

    remaining_idx = [i for i in range(4) if i not in (tl_idx, br_idx)]
    if len(remaining_idx) != 2:
        return tl, pts[0], br, pts[1]  # fallback
    r0, r1 = remaining_idx
    if pts[r0, 0] < pts[r1, 0]:
        tr, bl = pts[r0], pts[r1]
    else:
        tr, bl = pts[r1], pts[r0]

    return tl, tr, br, bl

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


def extract_patches(warped_float: np.ndarray, patch_centers_px: list,
                    roi_size: int = 20, sampling: str = 'trimmed') -> np.ndarray:
    """
    Average colour inside each patch ROI.

    sampling modes:
      'mean'    – plain arithmetic mean (fast, but hotpixel-sensitive)
      'trimmed' – 10 % trimmed mean (discards lowest/highest 10 % of pixels
                  per channel; robust against hotpixels and edge CA)
      'gaussian'– Gaussian-weighted mean (σ = roi/4, center-weighted;
                  de-emphasizes patch-edge artefacts)

    Returns shape (N, 3) float64 array in RGB order (0-1).
    """
    patch_colors = []
    h, w = warped_float.shape[:2]
    half = roi_size // 2

    for cx, cy in patch_centers_px:
        cy_min = max(0, cy - half)
        cy_max = min(h, cy + half)
        cx_min = max(0, cx - half)
        cx_max = min(w, cx + half)
        roi = warped_float[cy_min:cy_max, cx_min:cx_max].astype(np.float64)

        if sampling == 'trimmed':
            flat = roi.reshape(-1, 3)
            trim_n = max(1, int(flat.shape[0] * 0.10))
            avg_color = np.mean(np.sort(flat, axis=0)[trim_n:-trim_n], axis=0)
        elif sampling == 'gaussian':
            rh, rw = roi.shape[:2]
            yy, xx = np.meshgrid(
                np.arange(rh, dtype=np.float64) - rh / 2.0,
                np.arange(rw, dtype=np.float64) - rw / 2.0,
                indexing='ij',
            )
            sigma = max(rh, rw) / 4.0
            kernel = np.exp(-(xx ** 2 + yy ** 2) / (2.0 * sigma ** 2))
            kernel /= kernel.sum()
            avg_color = np.sum(roi * kernel[..., np.newaxis], axis=(0, 1))
        else:  # 'mean' (fallback)
            avg_color = roi.mean(axis=(0, 1))

        patch_colors.append(avg_color)

    colors = np.array(patch_colors, dtype=np.float64)
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


# ColorChecker Video: reflectance of the darkest gray patch (#31, index 31)
# Measured ~3.1 % under D65 (X-Rite / BabelColor data).
# The full 32-patch table is available for future per-patch weighting.
_CC_REFLECTANCE_P31 = 0.031


def _neutral_patch_indices(patch_count: int) -> np.ndarray:
    """Return indices of the four large neutral patches (28-31) in every chart set."""
    return np.array(
        [i for i in range(patch_count) if (i % 32) in {28, 29, 30, 31}],
        dtype=np.int64,
    )


def _compute_wb_gains(source_rgb: np.ndarray, target_rgb: np.ndarray) -> np.ndarray:
    """
    Compute per-channel white-balance gains from all neutral patches.

    Uses all four gray patches (28-31) averaged for robustness against
    clipping of the white patch and spectral imbalances.

    Returns (R, G, B) gain vector; clipped to [0.5, 2.0] as sanity.
    """
    neutral_idx = _neutral_patch_indices(len(source_rgb))
    if len(neutral_idx) < 4:
        return np.ones(3, dtype=np.float64)

    src_gray = np.mean(source_rgb[neutral_idx], axis=0)
    tgt_gray = np.mean(target_rgb[neutral_idx], axis=0)
    gain = tgt_gray / np.maximum(src_gray, 1e-8)
    return np.clip(gain, 0.5, 2.0)


# ---------------------------------------------------------------------------
# Delta-E quality report  (CIEDE2000, relative to sRGB / Rec.709 primaries)
# ---------------------------------------------------------------------------

def _compute_delta_e_report(source_rgb: np.ndarray, target_rgb: np.ndarray) -> dict:
    """
    Compute CIEDE2000 between target and predicted (corrected) values.

    IMPORTANT: Uses sRGB primaries as a proxy for camera gamut.  In Log→Log
    mode the input values are camera-native linear — NOT sRGB-encoded — so
    the resulting ΔE is a *relative* figure for internal comparison only.
    For Display-Reference-Match mode the values are display-encoded, making
    sRGB primaries a reasonable approximation.

    Returns per-patch list + summary stats (mean, p95, max).  The 'note'
    field explains the limitation.
    """
    if len(source_rgb) < 1:
        return {"per_patch": [], "mean": None, "p95": None, "max": None}

    try:
        # Both are already in linear space (target, predicted after correction)
        src_lin = np.clip(np.asarray(source_rgb, dtype=np.float64), 0.0, 1.0)
        tgt_lin = np.clip(np.asarray(target_rgb, dtype=np.float64), 0.0, 1.0)

        # RGB → XYZ via sRGB primaries (D65)
        src_xyz = colour.RGB_to_XYZ(src_lin, colourspace='sRGB')
        tgt_xyz = colour.RGB_to_XYZ(tgt_lin, colourspace='sRGB')

        # XYZ → Lab
        src_lab = colour.XYZ_to_Lab(src_xyz)
        tgt_lab = colour.XYZ_to_Lab(tgt_xyz)

        # CIEDE2000 per patch
        de = colour.difference.delta_E_CIE2000(src_lab, tgt_lab)
        de_list = [float(d) for d in de]

        return {
            "per_patch": de_list,
            "mean": round(float(np.mean(de_list)), 3),
            "p95": round(float(np.percentile(de_list, 95)), 3),
            "max": round(float(np.max(de_list)), 3),
            "unit": "CIEDE2000 (relative, sRGB primaries)",
        }
    except Exception:
        return {"per_patch": [], "mean": None, "p95": None, "max": None,
                "error": "Delta-E computation failed"}


def _normalize_black_points(source_lin: np.ndarray, target_lin: np.ndarray):
    """
    Estimate black points using the two extreme gray patches of the
    ColorChecker Video (#28 white ~90 % reflectance, #31 dark ~3.1 %).

    Assumes a linear sensor response between these two points.  The slope
    (gain) and intercept (black offset) are solved from:

        white = black + gain × 0.899
        dark  = black + gain × 0.031

    Extrapolating to 0 % reflectance gives a physically plausible black
    point instead of a magic-number scaling factor.
    """
    white_idx = [i for i in range(len(source_lin)) if (i % 32) == 28]
    dark_idx  = [i for i in range(len(source_lin)) if (i % 32) == 31]

    if len(white_idx) >= 1 and len(dark_idx) >= 1:
        src_w = float(np.mean(source_lin[white_idx]))
        src_d = float(np.mean(source_lin[dark_idx]))
        tgt_w = float(np.mean(target_lin[white_idx]))
        tgt_d = float(np.mean(target_lin[dark_idx]))

        # Solve:  white = black + gain * R_white,  dark = black + gain * R_dark
        # → gain = (white - dark) / (R_white - R_dark)
        # → black = dark - gain * R_dark
        denom = 0.899 - _CC_REFLECTANCE_P31  # ≈ 0.868
        if denom > 0 and src_w > src_d + 1e-8 and tgt_w > tgt_d + 1e-8:
            src_gain = (src_w - src_d) / denom
            tgt_gain = (tgt_w - tgt_d) / denom
            src_black = src_d - src_gain * _CC_REFLECTANCE_P31
            tgt_black = tgt_d - tgt_gain * _CC_REFLECTANCE_P31
            src_black = max(src_black, 0.0)
            tgt_black = max(tgt_black, 0.0)
        else:
            src_black = float(np.percentile(source_lin, 1))
            tgt_black = float(np.percentile(target_lin, 1))
    else:
        src_black = float(np.percentile(source_lin, 1))
        tgt_black = float(np.percentile(target_lin, 1))

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
    Log-to-Log LUT: source-log → target-log.

    Pipeline:
        1. Log → Linear decode
        2. Black-point normalization (Patch #31 reflectance extrapolation)
        3. Auto exposure-gain from mid-gray patch (#30)
        4. White-balance pre-gain on all patches
        5. Root-polynomial matrix (Finlayson 2015, exposure-invariant)
        6. Denormalize black, encode to target log
    The matrix only handles chroma deviations — WB and exposure are pre-corrected.
    """
    source_rgb = np.clip(np.asarray(all_source_colors, dtype=np.float64), 0.0, 1.0)
    target_rgb = np.clip(np.asarray(all_target_colors, dtype=np.float64), 0.0, 1.0)

    # 1. Decode log to scene-linear
    source_lin = _safe_log_decode(source_rgb, source_log_curve)
    target_lin = _safe_log_decode(target_rgb, target_log_curve)

    # 2. Black-point normalization — patch #31 reflectance extrapolation
    source_n, target_n, src_black, tgt_black = _normalize_black_points(source_lin, target_lin)

    # 3. Auto exposure-gain from mid-gray patch (#30) on perceptually weighted
    #    luminance BEFORE WB — so WB differences don't leak into exposure.
    midgray_idx = [i for i in range(len(source_n)) if (i % 32) == 30]
    exposure_gain = 1.0
    if midgray_idx:
        # Luma: BT.601 coefficients, effectively mono-chromatic → WB-independent
        def _luma(rgb):
            return 0.299 * rgb[:, 0] + 0.587 * rgb[:, 1] + 0.114 * rgb[:, 2]
        src_mg = float(np.mean(_luma(source_n[midgray_idx])))
        tgt_mg = float(np.mean(_luma(target_n[midgray_idx])))
        if src_mg > 1e-8:
            exposure_gain = tgt_mg / src_mg
            exposure_gain = float(np.clip(exposure_gain, 0.25, 4.0))

    # 4. White-balance pre-gain — computed from neutral patches
    wb_gains = _compute_wb_gains(source_n, target_n)
    source_wb = source_n * wb_gains[np.newaxis, :]
    source_wb = source_wb * exposure_gain

    # 5. Weight gray patches for the least-squares fit
    source_w, target_w = _weight_gray_patches(source_wb, target_n, weight=10)

    # 6. Root-polynomial expansion WITHOUT offset (all-ones removed)
    expanded = _expand_root_polynomial(source_w, degree=_POLY_DEGREE)[:, :-1]
    M, _, _, _ = np.linalg.lstsq(expanded.astype(np.float64), target_w.astype(np.float64), rcond=None)

    # 7. Measure accuracy on original (unweighted, WB-corrected) patches
    expanded_src = _expand_root_polynomial(source_wb, degree=_POLY_DEGREE)[:, :-1]
    predicted = np.dot(expanded_src, M)
    mse = float(np.mean((target_n - predicted) ** 2))

    # 8. Build 65³ LUT grid
    lut = colour.LUT3D(size=65, name=lut_name)
    grid_rgb = lut.table.reshape(-1, 3)

    grid_lin = _safe_log_decode(grid_rgb, source_log_curve)
    grid_n = np.maximum(grid_lin - src_black, 0.0)
    grid_wb = grid_n * wb_gains[np.newaxis, :]
    grid_exposed = grid_wb * exposure_gain
    grid_expanded = _expand_root_polynomial(grid_exposed, degree=_POLY_DEGREE)[:, :-1]
    grid_transformed = np.dot(grid_expanded, M)
    grid_transformed = np.maximum(grid_transformed + tgt_black, 1e-6)
    grid_transformed = np.clip(grid_transformed, 1e-6, 100.0)

    grid_log = _safe_log_encode(grid_transformed, target_log_curve)
    grid_log = np.clip(grid_log, 0.0, 1.0)

    lut.table = grid_log.reshape((65, 65, 65, 3))
    colour.write_LUT(lut, output_path)

    delta_e = _compute_delta_e_report(predicted, target_n)

    return {
        "mse": mse,
        "output_file": output_path,
        "wb_gains": wb_gains.tolist(),
        "exposure_gain": round(exposure_gain, 4),
        "exposure_stops": round(np.log2(exposure_gain), 2),
        "delta_e_mean": delta_e["mean"],
        "delta_e_p95": delta_e["p95"],
        "delta_e_max": delta_e["max"],
        "delta_e_per_patch": delta_e["per_patch"],
    }


def build_display_lut(
    all_source_colors: np.ndarray,
    all_target_colors: np.ndarray,
    source_log_curve: str,
    display_transform: str,
    lut_name: str,
    output_path: str,
) -> dict:
    """
    Display-Reference Match LUT: source-log → display-referred.

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

    # Delta-E: decode display-referred back to linear for CIEDE2000
    pred_lin = _apply_display_decode(predicted, display_transform)
    ref_lin = _apply_display_decode(ref_rgb, display_transform)
    delta_e = _compute_delta_e_report(pred_lin, ref_lin)

    return {
        "mse": mse,
        "output_file": output_path,
        "method": "code-value-tone-chroma",
        "tone_source": source_knots.tolist(),
        "tone_target": target_knots.tolist(),
        "delta_e_mean": delta_e["mean"],
        "delta_e_p95": delta_e["p95"],
        "delta_e_max": delta_e["max"],
        "delta_e_per_patch": delta_e["per_patch"],
    }
