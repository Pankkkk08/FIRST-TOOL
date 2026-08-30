"""Live system monitor tab: CPU / memory / disk usage bars."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from desktop_utility.core.common import human_size
from desktop_utility.core.sysmon import get_snapshot

REFRESH_MS = 1500


class SysMonTab(ttk.Frame):
    def __init__(self, master):
        super().__init__(master)
        self._disk_rows: list[tuple[ttk.Label, ttk.Progressbar, ttk.Label]] = []
        self._build_widgets()
        self._refresh()

    def _build_widgets(self) -> None:
        self.warning_var = tk.StringVar(value="")
        ttk.Label(self, textvariable=self.warning_var, foreground="#c0392b").pack(
            anchor="w", padx=8, pady=(6, 0)
        )

        cpu_frame = ttk.LabelFrame(self, text="CPU")
        cpu_frame.pack(fill="x", padx=8, pady=6)
        self.cpu_bar = ttk.Progressbar(cpu_frame, maximum=100)
        self.cpu_bar.pack(fill="x", padx=8, pady=6, side="left", expand=True)
        self.cpu_label = ttk.Label(cpu_frame, text="—")
        self.cpu_label.pack(side="left", padx=8)

        mem_frame = ttk.LabelFrame(self, text="Memory")
        mem_frame.pack(fill="x", padx=8, pady=6)
        self.mem_bar = ttk.Progressbar(mem_frame, maximum=100)
        self.mem_bar.pack(fill="x", padx=8, pady=6, side="left", expand=True)
        self.mem_label = ttk.Label(mem_frame, text="—")
        self.mem_label.pack(side="left", padx=8)

        self.disk_frame = ttk.LabelFrame(self, text="Disks")
        self.disk_frame.pack(fill="both", expand=True, padx=8, pady=6)

    def _ensure_disk_rows(self, n: int) -> None:
        while len(self._disk_rows) < n:
            row = ttk.Frame(self.disk_frame)
            row.pack(fill="x", padx=8, pady=3)
            name_label = ttk.Label(row, width=28, anchor="w")
            name_label.pack(side="left")
            bar = ttk.Progressbar(row, maximum=100)
            bar.pack(side="left", fill="x", expand=True, padx=6)
            pct_label = ttk.Label(row, width=18, anchor="e")
            pct_label.pack(side="left")
            self._disk_rows.append((name_label, bar, pct_label))

    def _refresh(self) -> None:
        snap = get_snapshot()
        if not snap.available:
            self.warning_var.set(
                f"System monitor unavailable ({snap.error or 'psutil not installed'}). "
                f"Run: pip install psutil"
            )
        else:
            self.warning_var.set("")
            self.cpu_bar["value"] = snap.cpu_percent
            self.cpu_label.config(text=f"{snap.cpu_percent:.0f}%")

            self.mem_bar["value"] = snap.mem_percent
            self.mem_label.config(
                text=f"{snap.mem_percent:.0f}%  ({human_size(snap.mem_used)} / {human_size(snap.mem_total)})"
            )

            self._ensure_disk_rows(len(snap.disks))
            for row, disk in zip(self._disk_rows, snap.disks):
                name_label, bar, pct_label = row
                name_label.config(text=disk.mountpoint)
                bar["value"] = disk.percent
                pct_label.config(
                    text=f"{disk.percent:.0f}%  ({human_size(disk.used)} / {human_size(disk.total)})"
                )

        self.after(REFRESH_MS, self._refresh)
