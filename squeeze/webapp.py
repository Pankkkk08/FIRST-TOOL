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
        background_color="#0d0f1a",
    )
    api.window = window
    webview.start()


if __name__ == "__main__":
    main()
