"""
server.py – Flask API backend for Camera Match Lab.
Handles image upload, corner extraction, patch sampling and LUT generation.
"""
import os
import base64
import json
import tempfile
import uuid
from pathlib import Path

from flask import Flask, request, jsonify, send_file, send_from_directory

from .lut_engine import (
    load_image,
    image_to_jpeg_bytes,
    warp_image,
    extract_patches,
    get_log_profiles,
    build_lut,
)
import numpy as np


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

def create_app(frontend_dir: str | None = None) -> Flask:
    # Resolve frontend path (works both in dev and PyInstaller bundle)
    if frontend_dir is None:
        base = Path(__file__).resolve().parent.parent
        frontend_dir = str(base / "frontend")

    app = Flask(__name__, static_folder=frontend_dir, static_url_path="")

    # Temp storage for uploaded images and session data
    SESSIONS: dict = {}

    # ------------------------------------------------------------------
    # Serve frontend
    # ------------------------------------------------------------------

    @app.route("/")
    def index():
        return send_from_directory(frontend_dir, "index.html")

    # ------------------------------------------------------------------
    # API: Log profiles
    # ------------------------------------------------------------------

    @app.get("/api/log-profiles")
    def api_log_profiles():
        return jsonify(get_log_profiles())

    # ------------------------------------------------------------------
    # API: Upload image
    # ------------------------------------------------------------------

    @app.post("/api/upload")
    def api_upload():
        if "file" not in request.files:
            return jsonify({"error": "No file provided"}), 400

        f = request.files["file"]
        ext = Path(f.filename).suffix.lower()
        if ext not in {".tif", ".tiff", ".jpg", ".jpeg", ".png"}:
            return jsonify({"error": f"Unsupported file type: {ext}"}), 400

        # Save to temp file
        tmp_dir = tempfile.gettempdir()
        img_id = str(uuid.uuid4())
        save_path = os.path.join(tmp_dir, f"clm_{img_id}{ext}")
        f.save(save_path)

        # Load and create preview
        try:
            img_float, img_display = load_image(save_path)
        except Exception as e:
            return jsonify({"error": str(e)}), 500

        # Resize preview so it's fast to transfer (max 1200px wide)
        orig_h, orig_w = img_float.shape[:2]
        import cv2 as _cv2
        max_w = 1200
        if orig_w > max_w:
            preview_scale = max_w / orig_w
            new_w = int(orig_w * preview_scale)
            new_h = int(orig_h * preview_scale)
            img_display = _cv2.resize(img_display, (new_w, new_h))
        else:
            preview_scale = 1.0

        preview_bytes = image_to_jpeg_bytes(img_display, quality=80)
        preview_b64 = base64.b64encode(preview_bytes).decode()

        # Store session — preview_scale lets api_warp convert back to full-res coords
        SESSIONS[img_id] = {
            "path": save_path,
            "orig_shape": (orig_h, orig_w),
            "preview_scale": preview_scale,
        }

        return jsonify({
            "img_id": img_id,
            "filename": f.filename,
            "width": img_display.shape[1],
            "height": img_display.shape[0],
            "preview": f"data:image/jpeg;base64,{preview_b64}",
        })

    # ------------------------------------------------------------------
    # API: Warp (extract corners, return warped preview + patch positions)
    # ------------------------------------------------------------------

    @app.post("/api/warp")
    def api_warp():
        data = request.get_json(force=True)
        img_id = data.get("img_id")
        corners = data.get("corners")  # [[x,y]*4]

        if img_id not in SESSIONS:
            return jsonify({"error": "Unknown image ID"}), 404
        if not corners or len(corners) != 4:
            return jsonify({"error": "Need exactly 4 corners"}), 400

        save_path = SESSIONS[img_id]["path"]
        orig_shape = SESSIONS[img_id]["orig_shape"]
        orig_h, orig_w = orig_shape

        # Corners are sent as normalized fractions (0.0 to 1.0) from frontend
        # Scale them directly to the full-res image pixel space
        corners_px = [[x * orig_w, y * orig_h] for x, y in corners]

        try:
            img_float, _ = load_image(save_path)
            warped_float, warped_display, default_patches = warp_image(img_float, corners_px)
        except Exception as e:
            return jsonify({"error": str(e)}), 500

        # Store warped data for patch extraction later
        warped_id = str(uuid.uuid4())
        warped_path = os.path.join(tempfile.gettempdir(), f"clm_warped_{warped_id}.npy")
        np.save(warped_path, warped_float)
        SESSIONS[warped_id] = {"warped_path": warped_path}

        preview_bytes = image_to_jpeg_bytes(warped_display, quality=85)
        preview_b64 = base64.b64encode(preview_bytes).decode()

        return jsonify({
            "warped_id": warped_id,
            "width": warped_display.shape[1],
            "height": warped_display.shape[0],
            "preview": f"data:image/jpeg;base64,{preview_b64}",
            "patch_centers": default_patches,  # list of [px, py]
        })

    # ------------------------------------------------------------------
    # API: Generate LUT
    # ------------------------------------------------------------------

    @app.post("/api/generate-lut")
    def api_generate_lut():
        data = request.get_json(force=True)

        pairs = data.get("pairs", [])          # [{source_warped_id, target_warped_id, source_patches, target_patches}]
        source_log = data.get("source_log")
        target_log = data.get("target_log")
        lut_name = data.get("lut_name", "CameraMatch")
        mode = data.get("mode", "single")       # "single" | "master"

        if not pairs or not source_log or not target_log:
            return jsonify({"error": "Missing required parameters"}), 400

        all_source_colors = []
        all_target_colors = []

        for pair in pairs:
            src_warped_id = pair.get("source_warped_id")
            tgt_warped_id = pair.get("target_warped_id")
            src_patches = pair.get("source_patches")   # [[px,py] * 32]
            tgt_patches = pair.get("target_patches")

            if src_warped_id not in SESSIONS or tgt_warped_id not in SESSIONS:
                return jsonify({"error": "Unknown warped image ID"}), 404

            src_warped = np.load(SESSIONS[src_warped_id]["warped_path"])
            tgt_warped = np.load(SESSIONS[tgt_warped_id]["warped_path"])

            src_colors = extract_patches(src_warped, src_patches)
            tgt_colors = extract_patches(tgt_warped, tgt_patches)

            all_source_colors.append(src_colors)
            all_target_colors.append(tgt_colors)

        all_source_colors = np.vstack(all_source_colors)
        all_target_colors = np.vstack(all_target_colors)

        # Output path: temp dir, user downloads via /api/download
        out_dir = tempfile.gettempdir()
        out_filename = _unique_filename(out_dir, lut_name, "cube")
        out_path = os.path.join(out_dir, out_filename)

        try:
            result = build_lut(
                all_source_colors,
                all_target_colors,
                source_log,
                target_log,
                lut_name,
                out_path,
            )
        except Exception as e:
            return jsonify({"error": str(e)}), 500

        return jsonify({
            "mse": result["mse"],
            "filename": out_filename,
            "download_url": f"/api/download/{out_filename}",
        })

    # ------------------------------------------------------------------
    # API: Download .cube file
    # ------------------------------------------------------------------

    @app.get("/api/download/<filename>")
    def api_download(filename: str):
        tmp_dir = tempfile.gettempdir()
        file_path = os.path.join(tmp_dir, filename)
        if not os.path.isfile(file_path):
            return jsonify({"error": "File not found"}), 404
        return send_file(file_path, as_attachment=True, download_name=filename)

    # ------------------------------------------------------------------
    # API: Open folder   (called after save, works on Win & Mac)
    # ------------------------------------------------------------------

    @app.post("/api/open-folder")
    def api_open_folder():
        data = request.get_json(force=True)
        folder = data.get("folder", "")
        if not folder or not os.path.isdir(folder):
            return jsonify({"error": "Folder not found"}), 404
        import sys, subprocess
        if sys.platform == "win32":
            os.startfile(folder)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", folder])
        else:
            subprocess.Popen(["xdg-open", folder])
        return jsonify({"ok": True})

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _unique_filename(directory: str, base: str, ext: str) -> str:
        name = f"{base}.{ext}"
        counter = 2
        while os.path.exists(os.path.join(directory, name)):
            name = f"{base}_{counter}.{ext}"
            counter += 1
        return name

    return app
