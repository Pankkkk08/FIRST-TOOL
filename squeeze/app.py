"""Squeeze — local video/photo/file compressor. Entry point.

Run with:  python run_squeeze.py   (from the repo root)
"""

from __future__ import annotations

import tkinter as tk

from squeeze.gui.archive_tab import ArchiveTab
from squeeze.gui.glass import (
    ACCENT,
    FONT_HEADING,
    GlassCanvas,
    TEXT_MUTED,
    apply_ttk_theme,
)
from squeeze.gui.photo_tab import PhotoTab
from squeeze.gui.video_tab import VideoTab

APP_TITLE = "Squeeze"
WINDOW_W, WINDOW_H = 1040, 760
HEADER_H = 64

TABS = [
    ("video", "Video"),
    ("photos", "Photos"),
    ("archive", "Files & Archives"),
]


class HeaderBar(GlassCanvas):
    """Slim top bar: app name on the left, a pill-style tab switcher on
    the right. Redraws once (the window is fixed-size — see build_app),
    so there's no resize-relayout to worry about.
    """

    def __init__(self, master, on_select):
        super().__init__(master, height=HEADER_H, highlightthickness=0)
        self._on_select = on_select
        self._active = TABS[0][0]
        self._pill_buttons = {}

    def draw(self) -> None:
        w = self.winfo_width()
        self.panel(0, 0, w, HEADER_H, radius=0, border=None)
        self.text(24, HEADER_H // 2, "Squeeze", font=FONT_HEADING, anchor="w")
        self.text(
            120, HEADER_H // 2, "video · photos · files", font=("Helvetica", 9), fill=TEXT_MUTED, anchor="w"
        )

        pill_w, pill_h, gap = 148, 36, 10
        x = w - 24 - (pill_w * len(TABS) + gap * (len(TABS) - 1))
        y = (HEADER_H - pill_h) // 2
        self._pill_buttons.clear()
        for key, label in TABS:
            style = "primary" if key == self._active else "ghost"
            btn = self.button(x, y, pill_w, pill_h, label, self._make_handler(key), style=style)
            self._pill_buttons[key] = btn
            x += pill_w + gap

    def _make_handler(self, key: str):
        def handler():
            self._active = key
            self._on_select(key)
            self.redraw()

        return handler


def build_app() -> tk.Tk:
    root = tk.Tk()
    root.title(APP_TITLE)
    root.geometry(f"{WINDOW_W}x{WINDOW_H}")
    # Fixed size: every tab is a hand-laid-out glass canvas rather than a
    # widget grid that reflows, so this sidesteps having to re-lay-out
    # (and re-render blurred panel art for) every widget on a live resize.
    root.resizable(False, False)
    root.configure(background="#0d0f1a")
    apply_ttk_theme(root)

    body = tk.Frame(root, background="#0d0f1a")

    # Each tab is itself a tk.Canvas subclass (GlassCanvas), and Canvas
    # overrides tkraise()/lift() to mean "raise a canvas item" rather than
    # the usual "raise this widget in the stacking order" — so switching
    # tabs by calling .tkraise() directly on them silently breaks. Wrap
    # each one in a plain tk.Frame container instead and raise that.
    containers = {}
    tabs = {}
    for key, cls in [("video", VideoTab), ("photos", PhotoTab), ("archive", ArchiveTab)]:
        container = tk.Frame(body, background="#0d0f1a")
        container.place(x=0, y=0, relwidth=1, relheight=1)
        tab = cls(container)
        tab.pack(fill="both", expand=True)
        containers[key] = container
        tabs[key] = tab

    def show(key: str) -> None:
        containers[key].tkraise()

    header = HeaderBar(root, on_select=show)
    header.pack(fill="x", side="top")
    header.redraw()

    body.pack(fill="both", expand=True)
    show("video")

    # Exposed for smoke tests / introspection — lets a test reach
    # `root.tabs["video"]` directly instead of walking widget geometry
    # (which reflects current stacking order, not creation order, once
    # any tab has been switched to — a real gotcha, see the comment above).
    root.tabs = tabs
    root.header = header
    return root


def main() -> None:
    app = build_app()
    app.mainloop()


if __name__ == "__main__":
    main()
