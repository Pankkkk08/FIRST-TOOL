"""Files/folders archive tab: bundle into one archive, or gzip each file
individually — two different shapes of "compress my files", both offered
since they solve different problems (one shareable file vs. many smaller
individual files).
"""

from __future__ import annotations

import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from shared.format import human_size
from shared.workers import CancellableTask
from compressor.core.archive import (
    ARCHIVE_FORMATS,
    create_archive,
    default_archive_extension,
    gzip_files_individually,
)


class ArchiveTab(ttk.Frame):
    def __init__(self, master):
        super().__init__(master)
        self._items: list[str] = []
        self._task: CancellableTask | None = None
        self._build_widgets()

    def _build_widgets(self) -> None:
        queue_btns = ttk.Frame(self)
        queue_btns.pack(fill="x", padx=8, pady=6)
        ttk.Button(queue_btns, text="Add Files…", command=self._add_files).pack(side="left")
        ttk.Button(queue_btns, text="Add Folder…", command=self._add_folder).pack(side="left", padx=4)
        ttk.Button(queue_btns, text="Remove Selected", command=self._remove_selected).pack(side="left", padx=4)
        ttk.Button(queue_btns, text="Clear", command=self._clear_queue).pack(side="left", padx=4)

        self.listbox = tk.Listbox(self, selectmode="extended", height=10)
        self.listbox.pack(fill="both", expand=True, padx=8, pady=4)

        mode_frame = ttk.LabelFrame(self, text="Mode")
        mode_frame.pack(fill="x", padx=8, pady=6)
        self.mode_var = tk.StringVar(value="bundle")
        ttk.Radiobutton(
            mode_frame, text="Bundle into one archive", variable=self.mode_var, value="bundle",
            command=self._on_mode_changed,
        ).pack(side="left", padx=6, pady=4)
        ttk.Radiobutton(
            mode_frame, text="Compress each file individually (.gz)", variable=self.mode_var, value="gzip",
            command=self._on_mode_changed,
        ).pack(side="left", padx=6, pady=4)

        self.bundle_options = ttk.Frame(self)
        self.bundle_options.pack(fill="x", padx=8, pady=3)
        ttk.Label(self.bundle_options, text="Format:").pack(side="left")
        self.format_var = tk.StringVar(value=next(iter(ARCHIVE_FORMATS)))
        ttk.Combobox(
            self.bundle_options, textvariable=self.format_var, values=list(ARCHIVE_FORMATS.keys()),
            state="readonly", width=32,
        ).pack(side="left", padx=4)

        ttk.Label(self.bundle_options, text="  Compression level:").pack(side="left", padx=(12, 0))
        self.level_var = tk.IntVar(value=6)
        ttk.Scale(
            self.bundle_options, from_=0, to=9, orient="horizontal", variable=self.level_var, length=140
        ).pack(side="left", padx=4)
        ttk.Label(self.bundle_options, text="(0=fastest, 9=smallest)").pack(side="left")

        row = ttk.Frame(self)
        row.pack(fill="x", padx=8, pady=3)
        ttk.Label(row, text="Output folder:").pack(side="left")
        self.output_dir_var = tk.StringVar(value="")
        ttk.Entry(row, textvariable=self.output_dir_var, width=50).pack(side="left", padx=4, fill="x", expand=True)
        ttk.Button(row, text="Browse…", command=self._browse_output_dir).pack(side="left")
        ttk.Label(row, text="(blank = same folder as source, gzip mode only)").pack(side="left", padx=6)

        bottom = ttk.Frame(self)
        bottom.pack(fill="x", padx=8, pady=6)
        self.start_btn = ttk.Button(bottom, text="Compress", command=self._start)
        self.start_btn.pack(side="left")
        self.cancel_btn = ttk.Button(bottom, text="Cancel", command=self._cancel, state="disabled")
        self.cancel_btn.pack(side="left", padx=4)
        self.status_var = tk.StringVar(value="")
        ttk.Label(bottom, textvariable=self.status_var, wraplength=600).pack(side="left", padx=12)

    def _on_mode_changed(self) -> None:
        state = "normal" if self.mode_var.get() == "bundle" else "disabled"
        for child in self.bundle_options.winfo_children():
            child.configure(state=state if not isinstance(child, ttk.Label) else "normal")

    # -- queue management -------------------------------------------------
    def _add_files(self) -> None:
        paths = filedialog.askopenfilenames()
        self._add_paths(paths)

    def _add_folder(self) -> None:
        folder = filedialog.askdirectory()
        if folder:
            self._add_paths([folder])

    def _add_paths(self, paths) -> None:
        for p in paths:
            if p not in self._items:
                self._items.append(p)
                label = p + ("/" if os.path.isdir(p) else "")
                self.listbox.insert("end", label)

    def _remove_selected(self) -> None:
        for i in reversed(self.listbox.curselection()):
            del self._items[i]
            self.listbox.delete(i)

    def _clear_queue(self) -> None:
        self._items.clear()
        self.listbox.delete(0, "end")

    def _browse_output_dir(self) -> None:
        chosen = filedialog.askdirectory()
        if chosen:
            self.output_dir_var.set(chosen)

    # -- compression --------------------------------------------------------
    # Both modes run on a background thread via CancellableTask (same helper
    # Dissect's tabs use) so a big batch never freezes the window and Cancel
    # actually works. CancellableTask itself has no progress-callback slot,
    # so `_progress_text` is written from the worker thread and read back by
    # a separate `.after()` poll loop — a plain string reference swap is
    # atomic under the GIL, so no lock is needed for this one-writer/
    # one-reader string handoff.
    def _start(self) -> None:
        if not self._items:
            messagebox.showinfo("Squeeze", "Add at least one file or folder first.")
            return

        mode = self.mode_var.get()
        try:
            if mode == "bundle":
                fmt = ARCHIVE_FORMATS[self.format_var.get()]
                out_dir = self.output_dir_var.get().strip() or os.path.dirname(
                    os.path.abspath(self._items[0])
                )
                target = self._next_free_path(out_dir, "archive", default_archive_extension(fmt))
            else:
                target = None
        except OSError as exc:
            messagebox.showerror("Squeeze", f"Cannot write to output folder:\n{exc}")
            return

        level = int(self.level_var.get())
        items = list(self._items)
        self._progress_text = f"Compressing {len(items)} item(s)…"
        self.status_var.set(self._progress_text)
        self.start_btn.config(state="disabled")
        self.cancel_btn.config(state="normal")
        self._task = CancellableTask()
        task = self._task

        def progress_cb(done: int, total: int, _name: str) -> None:
            self._progress_text = f"Compressing… {done}/{total}"

        if mode == "bundle":

            def do_work():
                return create_archive(
                    items, target, fmt=fmt, compression_level=level,
                    on_progress=progress_cb, should_stop=task.should_stop,
                )
        else:
            out_dir = self.output_dir_var.get().strip() or None

            def do_work():
                return gzip_files_individually(
                    items, output_dir=out_dir, compression_level=level,
                    on_progress=progress_cb, should_stop=task.should_stop,
                )

        def on_done(result, error) -> None:
            self._task_running = False
            self.start_btn.config(state="normal")
            self.cancel_btn.config(state="disabled")
            if error is not None:
                self.status_var.set(f"Failed: {error}")
                messagebox.showerror("Squeeze", f"Compression failed:\n{error}")
                return
            if mode == "bundle":
                self._report_bundle_result(result, target)
            else:
                self._report_gzip_result(result, task.should_stop())

        self._task_running = True
        task.run(self, do_work, on_done)
        self._poll_progress_label()

    def _poll_progress_label(self) -> None:
        if not getattr(self, "_task_running", False):
            return
        self.status_var.set(self._progress_text)
        self.after(150, self._poll_progress_label)

    def _report_bundle_result(self, result, target: str) -> None:
        if not result.success:
            if result.message == "Cancelled":
                self.status_var.set("Cancelled.")
            else:
                self.status_var.set(f"Failed: {result.message}")
                messagebox.showerror("Squeeze", f"Could not create archive:\n{result.message}")
            return
        self.status_var.set(
            f"Created {target} — {human_size(result.output_size)} "
            f"(saved {result.saved_percent:.0f}% vs {human_size(result.input_size)})"
        )

    def _report_gzip_result(self, batch, was_cancelled: bool) -> None:
        failures = [p for p, r in batch.results if not r.success]
        n_ok = len(batch.results) - len(failures)
        msg = (
            f"Compressed {n_ok} file(s): {human_size(batch.total_input)} → "
            f"{human_size(batch.total_output)}"
        )
        if failures:
            msg += f"  ({len(failures)} failed)"
        if was_cancelled:
            msg += "  (cancelled — partial results shown)"
        self.status_var.set(msg)

    @staticmethod
    def _next_free_path(out_dir: str, stem: str, ext: str) -> str:
        os.makedirs(out_dir, exist_ok=True)
        candidate = os.path.join(out_dir, f"{stem}{ext}")
        n = 2
        while os.path.exists(candidate):
            candidate = os.path.join(out_dir, f"{stem}_{n}{ext}")
            n += 1
        return candidate

    def _cancel(self) -> None:
        if self._task is not None:
            self._task.cancel()
            self.cancel_btn.config(state="disabled")
