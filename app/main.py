"""
main.py – Camera Match Lab desktop app entry point.
Starts Flask in a background thread and opens a native OS window via pywebview.
"""
import sys
import os
import shutil
import tempfile
import threading
import time
import urllib.request
import urllib.error

# When bundled by PyInstaller, __file__ lives inside the temp _MEIPASS folder.
if getattr(sys, "frozen", False):
    BASE_DIR = sys._MEIPASS  # type: ignore[attr-defined]
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

FRONTEND_DIR = os.path.join(BASE_DIR, "frontend")
sys.path.insert(0, BASE_DIR)

from backend.server import create_app  # noqa: E402
import webview  # noqa: E402

PORT = 7432
flask_app = create_app(frontend_dir=FRONTEND_DIR)

# Keeps a reference to the main window so the API can call dialogs on it.
_window = None


class PyWebViewApi:
    """Methods exposed to JavaScript via window.pywebview.api.*"""

    def save_lut(self, tmp_filename: str, suggested_name: str) -> dict:
        """
        Opens a native Save-As dialog.
        Copies the .cube from the cache dir to the chosen path.
        Returns {"success": True/False, "path": "...", "folder": "..."}
        """
        if _window is None:
            return {"success": False, "error": "No window"}

        result = _window.create_file_dialog(
            webview.SAVE_DIALOG,
            directory=os.path.expanduser("~"),
            save_filename=suggested_name,
            file_types=("CUBE LUT (*.cube)", "All files (*.*)",),
        )
        if not result:
            return {"success": False}  # user cancelled

        dest_path = os.path.abspath(result[0])
        dest_dir = os.path.dirname(dest_path)

        # Guard: if the path resolves to filesystem root (macOS save dialog quirk),
        # redirect to Desktop which is always writable.
        if dest_dir == "/" or not os.access(dest_dir, os.W_OK):
            fallback = os.path.join(os.path.expanduser("~"), "Desktop", os.path.basename(dest_path))
            dest_path = fallback
            dest_dir = os.path.dirname(dest_path)
            os.makedirs(dest_dir, exist_ok=True)

        if not os.access(dest_dir, os.W_OK):
            return {"success": False, "error": f"Verzeichnis nicht beschreibbar: {dest_dir}"}

        cache_dir = os.path.join(os.path.expanduser("~"), "Library", "Caches", "Camera Match Lab", "luts")
        src_path = os.path.join(cache_dir, tmp_filename)

        if not os.path.isfile(src_path):
            return {"success": False, "error": "Source file not found"}

        shutil.copy(src_path, dest_path)
        folder = os.path.dirname(dest_path)
        return {"success": True, "path": dest_path, "folder": folder}

    def open_folder(self, folder: str) -> dict:
        """Opens the folder in the OS file manager."""
        import subprocess
        if not os.path.isdir(folder):
            return {"success": False}
        if sys.platform == "win32":
            os.startfile(folder)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", folder])
        else:
            subprocess.Popen(["xdg-open", folder])
        return {"success": True}


def _run_flask():
    flask_app.run(host="127.0.0.1", port=PORT, debug=False, use_reloader=False)


def _wait_for_server(url: str, timeout: float = 5.0) -> bool:
    """Polls the given URL until it returns HTTP 200 or times out."""
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            with urllib.request.urlopen(url) as response:
                if response.status == 200:
                    return True
        except urllib.error.URLError:
            pass
        time.sleep(0.1)
    return False


def main():
    global _window

    t = threading.Thread(target=_run_flask, daemon=True)
    t.start()

    server_url = f"http://127.0.0.1:{PORT}"
    _wait_for_server(server_url)

    api = PyWebViewApi()
    _window = webview.create_window(
        title="Camera Match Lab",
        url=f"http://127.0.0.1:{PORT}",
        width=1300,
        height=860,
        min_size=(900, 600),
        resizable=True,
        js_api=api,
    )

    webview.start(debug=False)


if __name__ == "__main__":
    main()
