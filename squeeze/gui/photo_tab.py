"""Photo compression tab: batch queue + Pillow options + progress."""

from __future__ import annotations

import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from squeeze.core.format import human_size
from squeeze.core.photo import (
    IMAGE_EXTENSIONS,
    PhotoOptions,
    compress_photo,
    default_output_extension,
    is_image_file,
)
from squeeze.gui.batch import BatchRunner

FORMATS = ["same", "JPEG", "PNG", "WEBP"]

MAX_DIMENSION_CHOICES = {
    "Keep original size": None,
    "Max 3840px (4K)": 3840,
    "Max 1920px (Full HD)": 1920,
    "Max 1280px (HD)": 1280,
    "Max 800px": 800,
}


class PhotoTab(ttk.Frame):
    def __init__(self, master):
        super().__init__(master)
        self._items: list[str] = []
        self._runner: BatchRunner | None = None
        self._build_widgets()

    def _build_widgets(self) -> None:
        queue_btns = ttk.Frame(self)
        queue_btns.pack(fill="x", padx=8, pady=6)
        ttk.Button(queue_btns, text="Add Files…", command=self._add_files).pack(side="left")
        ttk.Button(queue_btns, text="Add Folder…", command=self._add_folder).pack(side="left", padx=4)
        ttk.Button(queue_btns, text="Remove Selected", command=self._remove_selected).pack(side="left", padx=4)
        ttk.Button(queue_btns, text="Clear", command=self._clear_queue).pack(side="left", padx=4)

        columns = ("name", "status", "saved")
        self.tree = ttk.Treeview(self, columns=columns, show="headings", selectmode="extended", height=10)
        for col, label, width, anchor in [
            ("name", "File", 440, "w"),
            ("status", "Status", 160, "w"),
            ("saved", "Saved", 160, "e"),
        ]:
            self.tree.heading(col, text=label)
            self.tree.column(col, width=width, anchor=anchor)
        self.tree.pack(fill="both", expand=True, padx=8, pady=4)

        options = ttk.LabelFrame(self, text="Options")
        options.pack(fill="x", padx=8, pady=6)

        row1 = ttk.Frame(options)
        row1.pack(fill="x", padx=6, pady=3)
        ttk.Label(row1, text="Quality:").pack(side="left")
        self.quality_var = tk.IntVar(value=80)
        ttk.Spinbox(row1, from_=1, to=100, textvariable=self.quality_var, width=6).pack(side="left", padx=4)
        ttk.Label(row1, text="(JPEG/WEBP only; PNG is always lossless)").pack(side="left", padx=(4, 16))

        ttk.Label(row1, text="Resize:").pack(side="left")
        self.resize_var = tk.StringVar(value="Keep original size")
        ttk.Combobox(
            row1, textvariable=self.resize_var, values=list(MAX_DIMENSION_CHOICES.keys()),
            state="readonly", width=22,
        ).pack(side="left", padx=4)

        row2 = ttk.Frame(options)
        row2.pack(fill="x", padx=6, pady=3)
        ttk.Label(row2, text="Output format:").pack(side="left")
        self.format_var = tk.StringVar(value="same")
        ttk.Combobox(row2, textvariable=self.format_var, values=FORMATS, state="readonly", width=10).pack(
            side="left", padx=4
        )

        self.strip_meta_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(row2, text="Strip EXIF/metadata", variable=self.strip_meta_var).pack(
            side="left", padx=(16, 0)
        )

        row3 = ttk.Frame(options)
        row3.pack(fill="x", padx=6, pady=3)
        ttk.Label(row3, text="Output folder:").pack(side="left")
        self.output_dir_var = tk.StringVar(value="")
        ttk.Entry(row3, textvariable=self.output_dir_var).pack(side="left", padx=4, fill="x", expand=True)
        ttk.Button(row3, text="Browse…", command=self._browse_output_dir).pack(side="left")

        row3b = ttk.Frame(options)
        row3b.pack(fill="x", padx=6)
        ttk.Label(row3b, text="(blank = same folder as each source file)", foreground="#666666").pack(
            anchor="w"
        )

        bottom = ttk.Frame(self)
        bottom.pack(fill="x", padx=8, pady=6)
        self.start_btn = ttk.Button(bottom, text="Start Compressing", command=self._start)
        self.start_btn.pack(side="left")
        self.cancel_btn = ttk.Button(bottom, text="Cancel", command=self._cancel, state="disabled")
        self.cancel_btn.pack(side="left", padx=4)
        self.overall_var = tk.StringVar(value="")
        ttk.Label(bottom, textvariable=self.overall_var).pack(side="left", padx=12)

    # -- queue management -------------------------------------------------
    def _add_files(self) -> None:
        exts = " ".join(f"*{e}" for e in sorted(IMAGE_EXTENSIONS))
        paths = filedialog.askopenfilenames(filetypes=[("Image files", exts), ("All files", "*.*")])
        self._add_paths(paths)

    def _add_folder(self) -> None:
        folder = filedialog.askdirectory()
        if not folder:
            return
        found = []
        for dirpath, _dirnames, filenames in os.walk(folder):
            for name in filenames:
                if is_image_file(name):
                    found.append(os.path.join(dirpath, name))
        self._add_paths(found)

    def _add_paths(self, paths) -> None:
        for p in paths:
            if p not in self._items:
                self._items.append(p)
                self.tree.insert("", "end", iid=p, values=(os.path.basename(p), "Queued", ""))

    def _remove_selected(self) -> None:
        for iid in self.tree.selection():
            if iid in self._items:
                self._items.remove(iid)
            self.tree.delete(iid)

    def _clear_queue(self) -> None:
        self._items.clear()
        self.tree.delete(*self.tree.get_children())

    def _browse_output_dir(self) -> None:
        chosen = filedialog.askdirectory()
        if chosen:
            self.output_dir_var.set(chosen)

    # -- compression -------------------------------------------------------
    def _current_options(self) -> PhotoOptions:
        return PhotoOptions(
            quality=self.quality_var.get(),
            max_dimension=MAX_DIMENSION_CHOICES[self.resize_var.get()],
            output_format=self.format_var.get(),
            strip_metadata=self.strip_meta_var.get(),
        )

    def _output_path_for(self, input_path: str, opts: PhotoOptions) -> str:
        out_dir = self.output_dir_var.get().strip() or os.path.dirname(input_path)
        stem = os.path.splitext(os.path.basename(input_path))[0]
        if opts.output_format == "same":
            ext = os.path.splitext(input_path)[1].lower()
        else:
            ext = default_output_extension(opts.output_format)
        candidate = os.path.join(out_dir, f"{stem}_compressed{ext}")
        n = 2
        while os.path.exists(candidate):
            candidate = os.path.join(out_dir, f"{stem}_compressed_{n}{ext}")
            n += 1
        return candidate

    def _start(self) -> None:
        if not self._items:
            messagebox.showinfo("Squeeze", "Add at least one photo first.")
            return
        opts = self._current_options()
        out_paths = {p: self._output_path_for(p, opts) for p in self._items}

        for p in self._items:
            self.tree.set(p, "status", "Queued")
            self.tree.set(p, "saved", "")

        self.start_btn.config(state="disabled")
        self.cancel_btn.config(state="normal")
        self._runner = BatchRunner()
        runner = self._runner

        def job(item: str, should_stop, report):
            report(-2, "Compressing…")
            return compress_photo(item, out_paths[item], opts)

        def on_progress(item, fraction, speed):
            if fraction == -2:
                self.tree.set(item, "status", speed)

        def on_item_done(item, result):
            if isinstance(result, Exception):
                self.tree.set(item, "status", "Failed")
                self.tree.set(item, "saved", str(result)[:60])
                return
            if not result.success:
                self.tree.set(item, "status", "Failed")
                self.tree.set(item, "saved", result.message[:60])
                return
            self.tree.set(item, "status", "Done")
            self.tree.set(
                item, "saved", f"{human_size(result.saved_bytes)} ({result.saved_percent:.0f}%)"
            )

        def on_all_done():
            self.start_btn.config(state="normal")
            self.cancel_btn.config(state="disabled")
            self.overall_var.set("Done." if not runner.should_stop() else "Cancelled.")

        self.overall_var.set(f"Processing {len(self._items)} file(s)…")
        runner.start(self, list(self._items), job, on_progress, on_item_done, on_all_done)

    def _cancel(self) -> None:
        if self._runner is not None:
            self._runner.cancel()
            self.cancel_btn.config(state="disabled")
