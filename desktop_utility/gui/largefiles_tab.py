"""Large & old file finder tab."""

from __future__ import annotations

import os
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from shared.format import human_size
from desktop_utility.core.largefiles import FileInfo, find_largest_files, find_oldest_files
from shared.safedelete import quarantine_paths
from shared.workers import CancellableTask


class LargeFilesTab(ttk.Frame):
    def __init__(self, master):
        super().__init__(master)
        self._results: list[FileInfo] = []
        self._task: CancellableTask | None = None
        self._build_widgets()

    def _build_widgets(self) -> None:
        top = ttk.Frame(self)
        top.pack(fill="x", padx=8, pady=6)

        self.path_var = tk.StringVar(value=os.path.expanduser("~"))
        ttk.Entry(top, textvariable=self.path_var).pack(side="left", fill="x", expand=True)
        ttk.Button(top, text="Browse…", command=self._browse).pack(side="left", padx=4)

        options = ttk.Frame(self)
        options.pack(fill="x", padx=8)

        self.mode_var = tk.StringVar(value="largest")
        ttk.Radiobutton(options, text="Largest files", variable=self.mode_var, value="largest").pack(
            side="left"
        )
        ttk.Radiobutton(options, text="Oldest files", variable=self.mode_var, value="oldest").pack(
            side="left", padx=(8, 0)
        )

        ttk.Label(options, text="  Top N:").pack(side="left", padx=(16, 2))
        self.top_n_var = tk.IntVar(value=50)
        ttk.Spinbox(options, from_=5, to=500, increment=5, textvariable=self.top_n_var, width=6).pack(
            side="left"
        )

        ttk.Label(options, text="  Min size (MB):").pack(side="left", padx=(16, 2))
        self.min_size_var = tk.IntVar(value=10)
        ttk.Spinbox(options, from_=0, to=100000, increment=10, textvariable=self.min_size_var, width=8).pack(
            side="left"
        )

        self.scan_btn = ttk.Button(options, text="Scan", command=self._start_scan)
        self.scan_btn.pack(side="left", padx=12)

        self.status_var = tk.StringVar(value="Pick a folder and click Scan.")
        ttk.Label(self, textvariable=self.status_var).pack(anchor="w", padx=8, pady=(4, 0))

        columns = ("size", "age", "path")
        self.tree = ttk.Treeview(self, columns=columns, show="headings", selectmode="extended")
        self.tree.heading("size", text="Size")
        self.tree.heading("age", text="Last modified")
        self.tree.heading("path", text="Path")
        self.tree.column("size", width=90, anchor="e")
        self.tree.column("age", width=140, anchor="center")
        self.tree.column("path", width=470)
        self.tree.pack(fill="both", expand=True, padx=8, pady=4)

        bottom = ttk.Frame(self)
        bottom.pack(fill="x", padx=8, pady=6)
        ttk.Button(bottom, text="Quarantine Selected", command=self._quarantine_selected).pack(
            side="left"
        )
        ttk.Label(
            bottom,
            text="Quarantined files move to ~/.dissect_trash and can be restored — nothing is "
            "permanently deleted here.",
        ).pack(side="left", padx=12)

    def _browse(self) -> None:
        chosen = filedialog.askdirectory(initialdir=self.path_var.get() or os.path.expanduser("~"))
        if chosen:
            self.path_var.set(chosen)

    def _start_scan(self) -> None:
        path = self.path_var.get().strip()
        if not path or not os.path.isdir(path):
            messagebox.showerror("Dissect", f"Not a valid folder:\n{path}")
            return

        if self._task is not None:
            self._task.cancel()

        mode = self.mode_var.get()
        top_n = max(1, self.top_n_var.get())
        min_size_bytes = max(0, self.min_size_var.get()) * 1024 * 1024

        self.scan_btn.config(state="disabled")
        self.status_var.set(f"Scanning {path} …")
        self._task = CancellableTask()

        def do_scan():
            if mode == "largest":
                return find_largest_files(
                    path, top_n=top_n, min_size=min_size_bytes, should_stop=self._task.should_stop
                )
            return find_oldest_files(
                path, top_n=top_n, should_stop=self._task.should_stop
            )

        def on_done(result, error):
            self.scan_btn.config(state="normal")
            if error is not None:
                self.status_var.set(f"Scan failed: {error}")
                messagebox.showerror("Dissect", f"Scan failed:\n{error}")
                return
            self._results = result
            self._refresh_list()

        self._task.run(self, do_scan, on_done)

    def _refresh_list(self) -> None:
        self.tree.delete(*self.tree.get_children())
        for info in self._results:
            when = time.strftime("%Y-%m-%d %H:%M", time.localtime(info.mtime))
            self.tree.insert(
                "", "end", iid=info.path, values=(human_size(info.size), when, info.path)
            )
        self.status_var.set(f"{len(self._results)} file(s) found.")

    def _quarantine_selected(self) -> None:
        selected = list(self.tree.selection())
        if not selected:
            messagebox.showinfo("Dissect", "Select one or more files first.")
            return
        if not messagebox.askyesno(
            "Dissect",
            f"Move {len(selected)} file(s) to the local quarantine "
            f"(~/.dissect_trash)? You can restore them later.",
        ):
            return
        result = quarantine_paths(selected)
        for src, _dest in result.moved:
            self.tree.delete(src)
        if result.failed:
            messagebox.showwarning(
                "Dissect",
                "Some files could not be moved:\n"
                + "\n".join(f"{p}: {err}" for p, err in result.failed),
            )
        self.status_var.set(f"Quarantined {len(result.moved)} file(s) to {result.batch_dir}")
