"""Sweep — local desktop disk & system utility. Entry point.

Run with:  python run_sweep.py   (from the repo root)
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from sweep.gui.disk_tab import DiskUsageTab
from sweep.gui.duplicates_tab import DuplicatesTab
from sweep.gui.largefiles_tab import LargeFilesTab
from sweep.gui.sysmon_tab import SysMonTab

APP_TITLE = "Sweep — Local Disk & System Utility"


def build_app() -> tk.Tk:
    root = tk.Tk()
    root.title(APP_TITLE)
    root.geometry("900x600")
    root.minsize(700, 480)

    notebook = ttk.Notebook(root)
    notebook.pack(fill="both", expand=True)

    notebook.add(DiskUsageTab(notebook), text="Disk Usage")
    notebook.add(DuplicatesTab(notebook), text="Duplicates")
    notebook.add(LargeFilesTab(notebook), text="Large & Old Files")
    notebook.add(SysMonTab(notebook), text="System Monitor")

    return root


def main() -> None:
    app = build_app()
    app.mainloop()


if __name__ == "__main__":
    main()
