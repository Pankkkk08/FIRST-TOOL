"""Duplicate file finder tab."""

from __future__ import annotations

import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from shared.format import human_size
from sweep.core.duplicates import DuplicateGroup, find_duplicates
from shared.safedelete import quarantine_paths
from shared.workers import CancellableTask


class DuplicatesTab(ttk.Frame):
    def __init__(self, master):
        super().__init__(master)
        self._groups: list[DuplicateGroup] = []
        self._task: CancellableTask | None = None
        self._build_widgets()

    def _build_widgets(self) -> None:
        top = ttk.Frame(self)
        top.pack(fill="x", padx=8, pady=6)

        self.path_var = tk.StringVar(value=os.path.expanduser("~"))
        ttk.Entry(top, textvariable=self.path_var).pack(side="left", fill="x", expand=True)
        ttk.Button(top, text="Browse…", command=self._browse).pack(side="left", padx=4)
        self.scan_btn = ttk.Button(top, text="Find Duplicates", command=self._start_scan)
        self.scan_btn.pack(side="left")

        self.status_var = tk.StringVar(value="Pick a folder and click Find Duplicates.")
        ttk.Label(self, textvariable=self.status_var).pack(anchor="w", padx=8)

        columns = ("group", "size", "path")
        self.tree = ttk.Treeview(self, columns=columns, show="headings", selectmode="extended")
        self.tree.heading("group", text="Group #")
        self.tree.heading("size", text="Size")
        self.tree.heading("path", text="Path")
        self.tree.column("group", width=70, anchor="center")
        self.tree.column("size", width=90, anchor="e")
        self.tree.column("path", width=520)
        self.tree.pack(fill="both", expand=True, padx=8, pady=4)

        bottom = ttk.Frame(self)
        bottom.pack(fill="x", padx=8, pady=6)
        ttk.Label(
            self,
            text="Tip: select all but one file per group, then Quarantine Selected. "
            "Quarantined files move to ~/.sweep_trash and can be restored — nothing is "
            "permanently deleted here.",
            wraplength=760,
            justify="left",
        ).pack(anchor="w", padx=8)
        ttk.Button(
            bottom, text="Quarantine Selected", command=self._quarantine_selected
        ).pack(side="left")
        self.savings_var = tk.StringVar(value="")
        ttk.Label(bottom, textvariable=self.savings_var).pack(side="left", padx=12)

    def _browse(self) -> None:
        chosen = filedialog.askdirectory(initialdir=self.path_var.get() or os.path.expanduser("~"))
        if chosen:
            self.path_var.set(chosen)

    def _start_scan(self) -> None:
        path = self.path_var.get().strip()
        if not path or not os.path.isdir(path):
            messagebox.showerror("Sweep", f"Not a valid folder:\n{path}")
            return

        if self._task is not None:
            self._task.cancel()

        self.scan_btn.config(state="disabled")
        self.status_var.set(f"Scanning {path} for duplicates …")
        self._task = CancellableTask()

        def do_scan():
            return find_duplicates(path, should_stop=self._task.should_stop)

        def on_done(result, error):
            self.scan_btn.config(state="normal")
            if error is not None:
                self.status_var.set(f"Scan failed: {error}")
                messagebox.showerror("Sweep", f"Scan failed:\n{error}")
                return
            self._groups = result
            self._refresh_list()

        self._task.run(self, do_scan, on_done)

    def _refresh_list(self) -> None:
        self.tree.delete(*self.tree.get_children())
        total_wasted = 0
        for i, group in enumerate(self._groups, start=1):
            total_wasted += group.wasted_bytes
            for path in group.paths:
                self.tree.insert("", "end", iid=path, values=(i, human_size(group.size), path))
        n_groups = len(self._groups)
        self.status_var.set(f"{n_groups} duplicate group(s) found.")
        self.savings_var.set(f"Reclaimable if you keep one copy per group: {human_size(total_wasted)}")

    def _quarantine_selected(self) -> None:
        selected = list(self.tree.selection())
        if not selected:
            messagebox.showinfo("Sweep", "Select one or more files first.")
            return
        if not messagebox.askyesno(
            "Sweep",
            f"Move {len(selected)} file(s) to the local quarantine "
            f"(~/.sweep_trash)? You can restore them later.",
        ):
            return
        result = quarantine_paths(selected)
        for src, _dest in result.moved:
            self.tree.delete(src)
        if result.failed:
            messagebox.showwarning(
                "Sweep",
                "Some files could not be moved:\n"
                + "\n".join(f"{p}: {err}" for p, err in result.failed),
            )
        self.status_var.set(
            f"Quarantined {len(result.moved)} file(s) to {result.batch_dir}"
        )
