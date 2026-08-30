"""Video compression tab: batch queue + ffmpeg options + progress."""

from __future__ import annotations

import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from shared.format import human_size
from compressor.core.ffmpeg_util import (
    VIDEO_EXTENSIONS,
    find_ffmpeg,
    find_ffprobe,
    is_video_file,
    probe,
)
from compressor.core.video import (
    DEFAULT_CRF,
    VIDEO_CODECS,
    VideoOptions,
    compress_video,
    default_preset_for_codec,
)
from compressor.gui.batch import BatchRunner

RESOLUTIONS = {
    "Keep original": None,
    "1080p": 1080,
    "720p": 720,
    "480p": 480,
    "360p": 360,
}

AUDIO_MODES = {
    "Copy (no re-encode)": "copy",
    "AAC 192 kbps": "aac_192",
    "AAC 128 kbps": "aac_128",
    "AAC 96 kbps": "aac_96",
    "Remove audio": "none",
}

CONTAINERS = ["mp4", "mkv", "webm"]

PRESETS_X26X = ["ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow", "slower", "veryslow"]
PRESETS_AV1 = [str(i) for i in range(0, 14)]  # 0 = slowest/best .. 13 = fastest


class VideoTab(ttk.Frame):
    def __init__(self, master):
        super().__init__(master)
        self._items: list[str] = []
        self._runner: BatchRunner | None = None
        self._row_start_size: dict[str, int] = {}
        self._build_widgets()
        self._check_ffmpeg()

    # -- layout ---------------------------------------------------------
    def _build_widgets(self) -> None:
        self.warning_var = tk.StringVar(value="")
        ttk.Label(self, textvariable=self.warning_var, foreground="#c0392b", wraplength=820).pack(
            anchor="w", padx=8, pady=(6, 0)
        )

        queue_btns = ttk.Frame(self)
        queue_btns.pack(fill="x", padx=8, pady=6)
        ttk.Button(queue_btns, text="Add Files…", command=self._add_files).pack(side="left")
        ttk.Button(queue_btns, text="Add Folder…", command=self._add_folder).pack(side="left", padx=4)
        ttk.Button(queue_btns, text="Remove Selected", command=self._remove_selected).pack(side="left", padx=4)
        ttk.Button(queue_btns, text="Clear", command=self._clear_queue).pack(side="left", padx=4)

        columns = ("name", "status", "progress", "saved")
        self.tree = ttk.Treeview(self, columns=columns, show="headings", selectmode="extended", height=8)
        for col, label, width, anchor in [
            ("name", "File", 380, "w"),
            ("status", "Status", 140, "w"),
            ("progress", "Progress", 140, "center"),
            ("saved", "Saved", 120, "e"),
        ]:
            self.tree.heading(col, text=label)
            self.tree.column(col, width=width, anchor=anchor)
        self.tree.pack(fill="both", expand=True, padx=8, pady=4)

        options = ttk.LabelFrame(self, text="Options")
        options.pack(fill="x", padx=8, pady=6)

        row1 = ttk.Frame(options)
        row1.pack(fill="x", padx=6, pady=3)
        ttk.Label(row1, text="Codec:").pack(side="left")
        self.codec_var = tk.StringVar(value=next(iter(VIDEO_CODECS)))
        codec_combo = ttk.Combobox(
            row1, textvariable=self.codec_var, values=list(VIDEO_CODECS.keys()), state="readonly", width=42
        )
        codec_combo.pack(side="left", padx=(4, 16))
        codec_combo.bind("<<ComboboxSelected>>", lambda e: self._on_codec_changed())

        ttk.Label(row1, text="Preset:").pack(side="left")
        self.preset_var = tk.StringVar(value="medium")
        self.preset_combo = ttk.Combobox(
            row1, textvariable=self.preset_var, values=PRESETS_X26X, state="readonly", width=12
        )
        self.preset_combo.pack(side="left", padx=4)

        row2 = ttk.Frame(options)
        row2.pack(fill="x", padx=6, pady=3)
        ttk.Label(row2, text="Quality (CRF, lower = better):").pack(side="left")
        self.crf_var = tk.IntVar(value=DEFAULT_CRF["libx264"])
        ttk.Spinbox(row2, from_=0, to=51, textvariable=self.crf_var, width=6).pack(side="left", padx=4)

        ttk.Label(row2, text="  Resolution:").pack(side="left", padx=(16, 0))
        self.resolution_var = tk.StringVar(value="Keep original")
        ttk.Combobox(
            row2, textvariable=self.resolution_var, values=list(RESOLUTIONS.keys()), state="readonly", width=14
        ).pack(side="left", padx=4)

        ttk.Label(row2, text="  Audio:").pack(side="left", padx=(16, 0))
        self.audio_var = tk.StringVar(value="Copy (no re-encode)")
        ttk.Combobox(
            row2, textvariable=self.audio_var, values=list(AUDIO_MODES.keys()), state="readonly", width=20
        ).pack(side="left", padx=4)

        ttk.Label(row2, text="  Container:").pack(side="left", padx=(16, 0))
        self.container_var = tk.StringVar(value="mp4")
        ttk.Combobox(row2, textvariable=self.container_var, values=CONTAINERS, state="readonly", width=6).pack(
            side="left", padx=4
        )

        row3 = ttk.Frame(options)
        row3.pack(fill="x", padx=6, pady=3)
        ttk.Label(row3, text="Output folder:").pack(side="left")
        self.output_dir_var = tk.StringVar(value="")
        ttk.Entry(row3, textvariable=self.output_dir_var, width=50).pack(side="left", padx=4, fill="x", expand=True)
        ttk.Button(row3, text="Browse…", command=self._browse_output_dir).pack(side="left")
        ttk.Label(row3, text="(blank = same folder as each source file)").pack(side="left", padx=6)

        bottom = ttk.Frame(self)
        bottom.pack(fill="x", padx=8, pady=6)
        self.start_btn = ttk.Button(bottom, text="Start Compressing", command=self._start)
        self.start_btn.pack(side="left")
        self.cancel_btn = ttk.Button(bottom, text="Cancel", command=self._cancel, state="disabled")
        self.cancel_btn.pack(side="left", padx=4)

        self.overall_var = tk.StringVar(value="")
        ttk.Label(bottom, textvariable=self.overall_var).pack(side="left", padx=12)

    def _check_ffmpeg(self) -> None:
        if not find_ffmpeg() or not find_ffprobe():
            self.warning_var.set(
                "ffmpeg/ffprobe were not found on PATH. Install ffmpeg to use this tab "
                "(e.g. `sudo apt install ffmpeg`, `brew install ffmpeg`, or download from ffmpeg.org)."
            )
            self.start_btn.config(state="disabled")

    def _on_codec_changed(self) -> None:
        codec = VIDEO_CODECS[self.codec_var.get()]
        self.crf_var.set(DEFAULT_CRF[codec])
        self.preset_var.set(default_preset_for_codec(codec))
        self.preset_combo.config(values=PRESETS_AV1 if codec == "libsvtav1" else PRESETS_X26X)

    # -- queue management -------------------------------------------------
    def _add_files(self) -> None:
        exts = " ".join(f"*{e}" for e in sorted(VIDEO_EXTENSIONS))
        paths = filedialog.askopenfilenames(filetypes=[("Video files", exts), ("All files", "*.*")])
        self._add_paths(paths)

    def _add_folder(self) -> None:
        folder = filedialog.askdirectory()
        if not folder:
            return
        found = []
        for dirpath, _dirnames, filenames in os.walk(folder):
            for name in filenames:
                if is_video_file(name):
                    found.append(os.path.join(dirpath, name))
        self._add_paths(found)

    def _add_paths(self, paths) -> None:
        for p in paths:
            if p not in self._items:
                self._items.append(p)
                self.tree.insert("", "end", iid=p, values=(os.path.basename(p), "Queued", "", ""))

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
    def _current_options(self) -> VideoOptions:
        codec = VIDEO_CODECS[self.codec_var.get()]
        return VideoOptions(
            codec=codec,
            crf=self.crf_var.get(),
            preset=self.preset_var.get(),
            target_height=RESOLUTIONS[self.resolution_var.get()],
            audio_mode=AUDIO_MODES[self.audio_var.get()],
        )

    def _output_path_for(self, input_path: str) -> str:
        out_dir = self.output_dir_var.get().strip() or os.path.dirname(input_path)
        stem = os.path.splitext(os.path.basename(input_path))[0]
        ext = "." + self.container_var.get()
        candidate = os.path.join(out_dir, f"{stem}_compressed{ext}")
        # Never silently overwrite an existing file from a previous run.
        n = 2
        while os.path.exists(candidate):
            candidate = os.path.join(out_dir, f"{stem}_compressed_{n}{ext}")
            n += 1
        return candidate

    def _start(self) -> None:
        if not self._items:
            messagebox.showinfo("Squeeze", "Add at least one video first.")
            return
        opts = self._current_options()
        out_paths = {p: self._output_path_for(p) for p in self._items}

        for p in self._items:
            self.tree.set(p, "status", "Queued")
            self.tree.set(p, "progress", "")
            self.tree.set(p, "saved", "")

        self.start_btn.config(state="disabled")
        self.cancel_btn.config(state="normal")
        self._runner = BatchRunner()
        runner = self._runner

        def job(item: str, should_stop, report):
            # Never touch Tkinter widgets from this thread directly — route
            # every UI update through `report()`, which hands it to the main
            # thread via BatchRunner's queue. fraction=-2 is a status-text-only
            # update (see on_progress below), fraction=-1 is speed-only.
            out_path = out_paths[item]
            report(-2, "Probing…")
            try:
                info = probe(item)
            except Exception as exc:
                return exc
            report(-2, "Compressing…")
            item_opts = opts
            if opts.target_height and info.height and opts.target_height >= info.height:
                item_opts = VideoOptions(**{**opts.__dict__, "target_height": None})

            def on_progress(fraction, speed):
                report(fraction, speed)

            return compress_video(
                item, out_path, item_opts, duration_sec=info.duration_sec,
                on_progress=on_progress, should_stop=should_stop,
            )

        def on_progress(item, fraction, speed):
            if fraction == -2:
                self.tree.set(item, "status", speed)
                return
            if fraction >= 0:
                self.tree.set(item, "progress", f"{fraction * 100:.0f}%")
            if speed:
                current = self.tree.set(item, "progress")
                base = current.split(" (")[0]
                self.tree.set(item, "progress", f"{base} ({speed})" if base else speed)

        def on_item_done(item, result):
            if isinstance(result, Exception):
                self.tree.set(item, "status", "Failed")
                self.tree.set(item, "progress", str(result)[:60])
                return
            if not result.success:
                self.tree.set(item, "status", "Cancelled" if result.message == "Cancelled" else "Failed")
                self.tree.set(item, "progress", "" if result.message == "Cancelled" else result.message[:60])
                return
            self.tree.set(item, "status", "Done")
            self.tree.set(item, "progress", "100%")
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
