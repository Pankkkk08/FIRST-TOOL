"""Files/folders archive tab: bundle into one archive, or gzip each file
individually — two different shapes of "compress my files", both offered
since they solve different problems (one shareable file vs. many smaller
individual files). Glass-canvas presentation.
"""

from __future__ import annotations

import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from squeeze.core.archive import (
    ARCHIVE_FORMATS,
    create_archive,
    default_archive_extension,
    gzip_files_individually,
)
from squeeze.core.format import human_size
from squeeze.gui.glass import FONT_CAPTION, FONT_HEADING, GlassCanvas, TEXT_FAINT, TEXT_MUTED
from squeeze.gui.layout import RowBuilder
from squeeze.gui.workers import CancellableTask


class ArchiveTab(GlassCanvas):
    def __init__(self, master):
        super().__init__(master)
        self._items: list[str] = []
        self._task: CancellableTask | None = None
        self._task_running = False

    def draw(self) -> None:
        w, h = self.winfo_width(), self.winfo_height()

        # -- Files panel --------------------------------------------------
        queue_top, queue_h = 16, 280
        self.panel(20, queue_top, w - 40, queue_h)
        self.text(40, queue_top + 22, "Files & Folders", font=FONT_HEADING)

        bx = w - 40
        self.clear_btn = self.button(0, 0, 90, 32, "Clear", self._clear_queue, style="ghost", font=FONT_CAPTION)
        self.remove_btn = self.button(0, 0, 130, 32, "Remove Selected", self._remove_selected, style="ghost", font=FONT_CAPTION)
        self.add_folder_btn = self.button(0, 0, 110, 32, "Add Folder…", self._add_folder, style="ghost", font=FONT_CAPTION)
        self.add_files_btn = self.button(0, 0, 100, 32, "Add Files…", self._add_files, style="primary", font=FONT_CAPTION)
        for btn, bw in [(self.clear_btn, 90), (self.remove_btn, 130), (self.add_folder_btn, 110), (self.add_files_btn, 100)]:
            bx -= bw
            self._move_button(btn, bx, queue_top + 16)
            bx -= 10

        self.listbox = tk.Listbox(
            self, selectmode="extended", background="#1c1e30", foreground="#f4f4f8",
            selectbackground="#8b7cf6", selectforeground="#151221", borderwidth=0,
            highlightthickness=0, font=("Helvetica", 10), activestyle="none",
        )
        self.embed(40, queue_top + 60, self.listbox, width=w - 80, height=queue_h - 76)

        # -- Mode & options panel --------------------------------------------------
        opts_top = queue_top + queue_h + 16
        opts_h = h - opts_top - 16
        self.panel(20, opts_top, w - 40, opts_h)

        self.mode_var = tk.StringVar(value="bundle")
        self.text(40, opts_top + 20, "Mode:", font=FONT_CAPTION, fill=TEXT_MUTED)
        self.bundle_btn = self.button(
            110, opts_top + 8, 220, 32, "Bundle into one archive",
            lambda: self._set_mode("bundle"), style="primary", font=FONT_CAPTION,
        )
        self.gzip_btn = self.button(
            340, opts_top + 8, 230, 32, "Compress each file (.gz)",
            lambda: self._set_mode("gzip"), style="ghost", font=FONT_CAPTION,
        )

        row = RowBuilder(self, 40, opts_top + 68)
        row.label("Archive format:", 112)
        self.format_var = tk.StringVar(value=next(iter(ARCHIVE_FORMATS)))
        self.format_combo = ttk.Combobox(
            self, textvariable=self.format_var, values=list(ARCHIVE_FORMATS.keys()),
            state="readonly", style="Glass.TCombobox", width=39,
        )
        row.field(self.format_combo, 340)
        row.label("Compression level:", 138)
        self.level_var = tk.IntVar(value=6)
        self.level_scale = ttk.Scale(
            self, from_=0, to=9, orient="horizontal", variable=self.level_var, length=140,
            style="Glass.Horizontal.TScale",
        )
        row.field(self.level_scale, 150)
        self.text(row.x, row.y + 13, "0 = fastest, 9 = smallest", font=FONT_CAPTION, fill=TEXT_MUTED)

        row.newline(40, dy=44)
        row.label("Output folder:", 108)
        self.output_dir_var = tk.StringVar(value="")
        out_entry = ttk.Entry(self, textvariable=self.output_dir_var, style="Glass.TEntry")
        row.field(out_entry, 560)
        browse_btn = self.button(0, 0, 90, 30, "Browse…", self._browse_output_dir, style="ghost", font=FONT_CAPTION)
        self._move_button(browse_btn, row.x, row.y - 2)

        row.newline(40, dy=40)
        self.text(row.x, row.y, "blank = same folder as source (gzip mode only)", font=FONT_CAPTION, fill=TEXT_MUTED)

        row.newline(40, dy=44)
        self.start_btn = self.button(row.x, row.y - 4, 150, 38, "Compress", self._start, style="primary")
        self.cancel_btn = self.button(row.x + 162, row.y - 4, 110, 38, "Cancel", self._cancel, style="danger")
        self.cancel_btn.set_enabled(False)
        self.status_var = tk.StringVar(value="")
        self.status_text_id = self.text(
            row.x + 290, row.y + 8, "", font=FONT_CAPTION, fill=TEXT_MUTED, anchor="nw", width=w - 40 - (row.x + 290)
        )

    def _move_button(self, btn, x, y) -> None:
        btn.x, btn.y = x, y
        self.coords(btn.image_id, x, y)
        self.coords(btn.text_id, x + btn.w / 2, y + btn.h / 2)

    def _refresh_status_text(self) -> None:
        self.itemconfig(self.status_text_id, text=self.status_var.get())

    def _set_mode(self, mode: str) -> None:
        self.mode_var.set(mode)
        self.bundle_btn.set_style("primary" if mode == "bundle" else "ghost")
        self.gzip_btn.set_style("primary" if mode == "gzip" else "ghost")
        state = "readonly" if mode == "bundle" else "disabled"
        self.format_combo.config(state=state)
        self.level_scale.config(state="normal" if mode == "bundle" else "disabled")

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
    # Both modes run on a background thread via CancellableTask so a big
    # batch never freezes the window and Cancel actually works.
    # CancellableTask itself has no progress-callback slot,
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
        self._refresh_status_text()
        self.start_btn.set_enabled(False)
        self.cancel_btn.set_enabled(True)
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
            self.start_btn.set_enabled(True)
            self.cancel_btn.set_enabled(False)
            if error is not None:
                self.status_var.set(f"Failed: {error}")
                self._refresh_status_text()
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
        if not self._task_running:
            return
        self.status_var.set(self._progress_text)
        self._refresh_status_text()
        self.after(150, self._poll_progress_label)

    def _report_bundle_result(self, result, target: str) -> None:
        if not result.success:
            if result.message == "Cancelled":
                self.status_var.set("Cancelled.")
            else:
                self.status_var.set(f"Failed: {result.message}")
                messagebox.showerror("Squeeze", f"Could not create archive:\n{result.message}")
            self._refresh_status_text()
            return
        self.status_var.set(
            f"Created {target} — {human_size(result.output_size)} "
            f"(saved {result.saved_percent:.0f}% vs {human_size(result.input_size)})"
        )
        self._refresh_status_text()

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
        self._refresh_status_text()

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
            self.cancel_btn.set_enabled(False)
