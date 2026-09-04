"""Squeeze — local video/photo/file compressor. Entry point.

Run with:  python run_squeeze.py   (from the repo root)

Renders the UI with the OS's own webview (WebView2 on Windows, WebKit on
macOS/Linux) instead of Tkinter — real GPU-accelerated rendering and
genuine live CSS blur for the glass panels, rather than a hand-drawn
imitation. The Python side (squeeze/webui/api.py) is a thin adapter over
squeeze/core/*, which is unchanged from the previous Tkinter build.
"""

from __future__ import annotations

import os

import webview

from squeeze.webui.api import Api

APP_TITLE = "Squeeze"
WINDOW_W, WINDOW_H = 1080, 780

_STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "webui", "static")


def main() -> None:
    api = Api()
    window = webview.create_window(
        APP_TITLE,
        url=os.path.join(_STATIC_DIR, "index.html"),
        js_api=api,
        width=WINDOW_W,
        height=WINDOW_H,
        min_size=(860, 620),
        background_color="#0e1014",  # matches --bg-base in static/style.css
    )
    api.window = window

    # Register the drag-and-drop handler on `loaded` — DOM element lookup
    # needs the page to exist first. Registering a Python-side `drop`
    # handler is also what switches on pywebview's native drag-and-drop
    # path resolution (it counts drop listeners), so this line is what
    # makes `pywebviewFullPath` appear on dropped files at all.
    def register_drop_handler() -> None:
        window.dom.get_element("body").events.drop += api._on_drop

    window.events.loaded += register_drop_handler
    # icon= sets the window/taskbar icon on Linux (GTK loads PNG fine).
    # It must NOT be passed on Windows: pywebview's WinForms backend
    # feeds the path to .NET's Icon(), which only accepts .ico files and
    # throws on PNG — crashing the app at startup (caught by CI's
    # Windows launch check). Windows doesn't need it anyway: the icon is
    # embedded into Squeeze.exe at build time (packaging/squeeze.spec)
    # and pywebview extracts it from the executable automatically, as
    # macOS does from the .app bundle.
    webview.start(icon=None if os.name == "nt" else os.path.join(_STATIC_DIR, "icon.png"))


if __name__ == "__main__":
    main()
