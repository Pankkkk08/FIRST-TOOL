"""Photo compression tab: batch queue + Pillow options + progress, on a
glass canvas.
"""

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
from squeeze.gui.glass import FONT_CAPTION, FONT_HEADING, GlassCanvas, TEXT_FAINT, TEXT_MUTED
from squeeze.gui.layout import RowBuilder

FORMATS = ["same", "JPEG", "PNG", "WEBP"]

MAX_DIMENSION_CHOICES = {
    "Keep original size": None,
    "Max 3840px (4K)": 3840,
    "Max 1920px (Full HD)": 1920,
    "Max 1280px (HD)": 1280,
    "Max 800px": 800,
}


class PhotoTab(GlassCanvas):
    def __init__(self, master):
        super().__init__(master)
        self._items: list[str] = []
        self._runner: BatchRunner | None = None

    def draw(self) -> None:
        w, h = self.winfo_width(), self.winfo_height()

        # -- Queue panel --------------------------------------------------
        queue_top, queue_h = 16, 280
        self.panel(20, queue_top, w - 40, queue_h)
        self.text(40, queue_top + 22, "Queue", font=FONT_HEADING)

        bx = w - 40
        self.clear_btn = self.button(0, 0, 90, 32, "Clear", self._clear_queue, style="ghost", font=FONT_CAPTION)
        self.remove_btn = self.button(0, 0, 130, 32, "Remove Selected", self._remove_selected, style="ghost", font=FONT_CAPTION)
        self.add_folder_btn = self.button(0, 0, 110, 32, "Add Folder…", self._add_folder, style="ghost", font=FONT_CAPTION)
        self.add_files_btn = self.button(0, 0, 100, 32, "Add Files…", self._add_files, style="primary", font=FONT_CAPTION)
        for btn, bw in [(self.clear_btn, 90), (self.remove_btn, 130), (self.add_folder_btn, 110), (self.add_files_btn, 100)]:
            bx -= bw
            self._move_button(btn, bx, queue_top + 16)
            bx -= 10

        tree_frame, self.tree = _build_queue_treeview(self)
        self.embed(40, queue_top + 60, tree_frame, width=w - 80, height=queue_h - 76)

        # -- Options panel --------------------------------------------------
        opts_top = queue_top + queue_h + 16
        opts_h = h - opts_top - 16
        self.panel(20, opts_top, w - 40, opts_h)

        row = RowBuilder(self, 40, opts_top + 22)
        row.label("Quality:", 62)
        self.quality_var = tk.IntVar(value=80)
        quality_spin = ttk.Spinbox(self, from_=1, to=100, textvariable=self.quality_var, style="Glass.TSpinbox", width=5)
        row.field(quality_spin, 55)
        row.label("Resize:", 58)
        self.resize_var = tk.StringVar(value="Keep original size")
        resize_combo = ttk.Combobox(
            self, textvariable=self.resize_var, values=list(MAX_DIMENSION_CHOICES.keys()),
            state="readonly", style="Glass.TCombobox", width=24,
        )
        row.field(resize_combo, 210)
        self.text(row.x, row.y + 13, "JPEG/WEBP only — PNG is always lossless", font=FONT_CAPTION, fill=TEXT_MUTED)

        row.newline(40)
        row.label("Output format:", 108)
        self.format_var = tk.StringVar(value="same")
        format_combo = ttk.Combobox(
            self, textvariable=self.format_var, values=FORMATS, state="readonly", style="Glass.TCombobox", width=9,
        )
        row.field(format_combo, 90)
        self.strip_meta_var = tk.BooleanVar(value=True)
        self.strip_meta_toggle = self.toggle(row.x, row.y + 2, True, self._on_strip_meta_toggled)
        self.text(row.x + 50, row.y + 13, "Strip EXIF/metadata", font=FONT_CAPTION, fill=TEXT_MUTED)

        row.newline(40, dy=44)
        row.label("Output folder:", 108)
        self.output_dir_var = tk.StringVar(value="")
        out_entry = ttk.Entry(self, textvariable=self.output_dir_var, style="Glass.TEntry")
        row.field(out_entry, 560)
        browse_btn = self.button(0, 0, 90, 30, "Browse…", self._browse_output_dir, style="ghost", font=FONT_CAPTION)
        self._move_button(browse_btn, row.x, row.y - 2)

        row.newline(40, dy=40)
        self.text(row.x, row.y, "blank = same folder as each source file", font=FONT_CAPTION, fill=TEXT_MUTED)

        row.newline(40, dy=44)
        self.start_btn = self.button(row.x, row.y - 4, 170, 38, "Start Compressing", self._start, style="primary")
        self.cancel_btn = self.button(row.x + 182, row.y - 4, 110, 38, "Cancel", self._cancel, style="danger")
        self.cancel_btn.set_enabled(False)
        self.status_var = tk.StringVar(value="")
        self.status_text_id = self.text(row.x + 310, row.y + 15, "", font=FONT_CAPTION, fill=TEXT_MUTED, anchor="w")

    def _move_button(self, btn, x, y) -> None:
        btn.x, btn.y = x, y
        self.coords(btn.image_id, x, y)
        self.coords(btn.text_id, x + btn.w / 2, y + btn.h / 2)

    def _refresh_status_text(self) -> None:
        self.itemconfig(self.status_text_id, text=self.status_var.get())

    def _on_strip_meta_toggled(self, on: bool) -> None:
        self.strip_meta_var.set(on)

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

        self.start_btn.set_enabled(False)
        self.cancel_btn.set_enabled(True)
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
            self.start_btn.set_enabled(True)
            self.cancel_btn.set_enabled(False)
            self.status_var.set("Done." if not runner.should_stop() else "Cancelled.")
            self._refresh_status_text()

        self.status_var.set(f"Processing {len(self._items)} file(s)…")
        self._refresh_status_text()
        runner.start(self, list(self._items), job, on_progress, on_item_done, on_all_done)

    def _cancel(self) -> None:
        if self._runner is not None:
            self._runner.cancel()
            self.cancel_btn.set_enabled(False)


def _build_queue_treeview(parent) -> tuple[tk.Frame, ttk.Treeview]:
    frame = tk.Frame(parent, background="#1c1e30")
    columns = ("name", "status", "saved")
    tree = ttk.Treeview(
        frame, columns=columns, show="headings", selectmode="extended", style="Glass.Treeview"
    )
    for col, label, width, anchor in [
        ("name", "File", 500, "w"),
        ("status", "Status", 200, "w"),
        ("saved", "Saved", 200, "e"),
    ]:
        tree.heading(col, text=label)
        tree.column(col, width=width, anchor=anchor)
    scrollbar = ttk.Scrollbar(frame, orient="vertical", command=tree.yview, style="Glass.Vertical.TScrollbar")
    tree.configure(yscrollcommand=scrollbar.set)
    tree.pack(side="left", fill="both", expand=True)
    scrollbar.pack(side="right", fill="y")
    return frame, tree
