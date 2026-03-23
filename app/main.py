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
        Copies the .cube from the temp dir to the chosen path.
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

        dest_path = result[0]
        src_path = os.path.join(tempfile.gettempdir(), tmp_filename)

        if not os.path.isfile(src_path):
            return {"success": False, "error": "Source file not found"}

        shutil.copy2(src_path, dest_path)
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


def main():
    global _window

    t = threading.Thread(target=_run_flask, daemon=True)
    t.start()
    time.sleep(0.8)

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
