"""Squeeze — local video/photo/file compressor. Entry point.

Run with:  python run_squeeze.py   (from the repo root)
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from squeeze.gui.archive_tab import ArchiveTab
from squeeze.gui.photo_tab import PhotoTab
from squeeze.gui.video_tab import VideoTab

APP_TITLE = "Squeeze — Local Video, Photo & File Compressor"


def build_app() -> tk.Tk:
    root = tk.Tk()
    root.title(APP_TITLE)
    root.geometry("960x650")
    root.minsize(760, 520)

    notebook = ttk.Notebook(root)
    notebook.pack(fill="both", expand=True)

    notebook.add(VideoTab(notebook), text="Video")
    notebook.add(PhotoTab(notebook), text="Photos")
    notebook.add(ArchiveTab(notebook), text="Files / Archives")

    return root


def main() -> None:
    app = build_app()
    app.mainloop()


if __name__ == "__main__":
    main()
