"""
lut_engine.py – Pure calculation logic, no UI, no stdin.
Extracted from generate_lut.py.
"""
import os
import numpy as np
import cv2
import colour


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


# ---------------------------------------------------------------------------
# LUT generation
# ---------------------------------------------------------------------------

def build_lut(
    all_source_colors: np.ndarray,
    all_target_colors: np.ndarray,
    source_log_curve: str,
    target_log_curve: str,
    lut_name: str,
    output_path: str,
) -> dict:
    """
    Compute weighted least-squares color matrix and bake into a 65^3 3D LUT.

    Returns dict with keys: mse, output_file
    """
    # 1. Log → Linear
    try:
        source_lin = colour.models.log_decoding(all_source_colors, function=source_log_curve)
        target_lin = colour.models.log_decoding(all_target_colors, function=target_log_curve)
    except Exception as e:
        source_lin = np.power(np.clip(all_source_colors, 0, 1), 2.4)
        target_lin = np.power(np.clip(all_target_colors, 0, 1), 2.4)

    # 2. Gray-patch weighting (indices 28-31 per 32-patch chunk)
    weights = np.ones(len(source_lin))
    gray_indices = {28, 29, 30, 31}
    for i in range(len(source_lin)):
        if (i % 32) in gray_indices:
            weights[i] = 100.0
    W = np.diag(weights)

    # 3. Weighted least-squares: solve [source_lin | 1] @ matrix ≈ target_lin
    source_pad = np.c_[source_lin, np.ones(source_lin.shape[0])]
    WX = W @ source_pad
    WY = W @ target_lin
    matrix, _, _, _ = np.linalg.lstsq(WX, WY, rcond=None)

    source_transformed_lin = source_pad @ matrix
    mse = float(np.mean((target_lin - source_transformed_lin) ** 2))

    # 4. Bake into 65^3 LUT
    lut = colour.LUT3D(size=65, name=lut_name)
    try:
        grid_lin = colour.models.log_decoding(lut.table, function=source_log_curve)
    except Exception:
        grid_lin = np.power(np.clip(lut.table, 0, 1), 2.4)

    flat_grid_lin = grid_lin.reshape(-1, 3)
    flat_grid_pad = np.c_[flat_grid_lin, np.ones(flat_grid_lin.shape[0])]
    flat_transformed_lin = flat_grid_pad @ matrix
    flat_transformed_lin = np.clip(flat_transformed_lin, 1e-6, 100.0)

    try:
        flat_transformed_log = colour.models.log_encoding(flat_transformed_lin, function=target_log_curve)
    except Exception:
        flat_transformed_log = np.power(flat_transformed_lin, 1 / 2.4)

    flat_transformed_log = np.clip(flat_transformed_log, 0.0, 1.0)
    lut.table = flat_transformed_log.reshape((65, 65, 65, 3))

    colour.write_LUT(lut, output_path)
    return {"mse": mse, "output_file": output_path}
