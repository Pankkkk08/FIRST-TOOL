"""Video compression tab: batch queue + ffmpeg options + progress, on a
glass canvas.
"""

from __future__ import annotations

import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from squeeze.core.format import human_size
from squeeze.core.ffmpeg_util import (
    VIDEO_EXTENSIONS,
    find_ffmpeg,
    find_ffprobe,
    is_video_file,
    probe,
)
from squeeze.core.video import (
    DEFAULT_CRF,
    QUALITY_PRESETS,
    VIDEO_CODECS,
    VideoOptions,
    compress_video,
    default_preset_for_codec,
)
from squeeze.gui.batch import BatchRunner
from squeeze.gui.glass import (
    DANGER,
    FONT_CAPTION,
    FONT_HEADING,
    GlassCanvas,
    TEXT_FAINT,
    TEXT_MUTED,
)
from squeeze.gui.layout import RowBuilder

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

NO_PROFILE = "(default)"
PROFILES_BY_CODEC = {
    "libx264": [NO_PROFILE, "main", "high"],
    "libx265": [NO_PROFILE, "main", "main10"],
    "libsvtav1": [NO_PROFILE],
}

CUSTOM_PRESET = "Custom (set below)"


class VideoTab(GlassCanvas):
    def __init__(self, master):
        super().__init__(master)
        self._items: list[str] = []
        self._runner: BatchRunner | None = None

    # -- layout -----------------------------------------------------------
    def draw(self) -> None:
        w, h = self.winfo_width(), self.winfo_height()

        # -- Queue panel --------------------------------------------------
        queue_top, queue_h = 16, 260
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

        self.warning_id = self.text(40, queue_top + queue_h - 4, "", font=FONT_CAPTION, fill=DANGER, anchor="sw")

        # -- Options panel --------------------------------------------------
        opts_top = queue_top + queue_h + 16
        opts_h = h - opts_top - 16
        self.panel(20, opts_top, w - 40, opts_h)

        row = RowBuilder(self, 40, opts_top + 22)
        row.label("Quality preset:", 120)
        self.quality_preset_var = tk.StringVar(value=CUSTOM_PRESET)
        preset_names = [CUSTOM_PRESET] + list(QUALITY_PRESETS.keys())
        preset_combo = ttk.Combobox(
            self, textvariable=self.quality_preset_var, values=preset_names,
            state="readonly", style="Glass.TCombobox", width=26,
        )
        preset_combo.bind("<<ComboboxSelected>>", lambda e: self._on_quality_preset_changed())
        row.field(preset_combo, 210)
        self.text(
            row.x, row.y + 13, "picks Codec/Quality/Speed/Profile below — HandBrake's own numbers",
            font=FONT_CAPTION, fill=TEXT_MUTED,
        )

        row.newline(40)
        row.label("Codec:", 60)
        self.codec_var = tk.StringVar(value=next(iter(VIDEO_CODECS)))
        codec_combo = ttk.Combobox(
            self, textvariable=self.codec_var, values=list(VIDEO_CODECS.keys()),
            state="readonly", style="Glass.TCombobox", width=48,
        )
        codec_combo.bind("<<ComboboxSelected>>", lambda e: self._on_codec_changed())
        row.field(codec_combo, 400)
        row.label("Speed:", 55)
        self.preset_var = tk.StringVar(value="medium")
        self.preset_combo = ttk.Combobox(
            self, textvariable=self.preset_var, values=PRESETS_X26X,
            state="readonly", style="Glass.TCombobox", width=11,
        )
        row.field(self.preset_combo, 100)

        row.newline(40)
        row.label("Quality (CRF):", 108)
        self.crf_var = tk.IntVar(value=DEFAULT_CRF["libx264"])
        crf_spin = ttk.Spinbox(self, from_=0, to=51, textvariable=self.crf_var, style="Glass.TSpinbox", width=5)
        row.field(crf_spin, 55)
        row.label("Profile:", 58)
        self.profile_var = tk.StringVar(value=NO_PROFILE)
        self.profile_combo = ttk.Combobox(
            self, textvariable=self.profile_var, values=PROFILES_BY_CODEC["libx264"],
            state="readonly", style="Glass.TCombobox", width=11,
        )
        row.field(self.profile_combo, 90)
        row.label("Resolution:", 82)
        self.resolution_var = tk.StringVar(value="Keep original")
        resolution_combo = ttk.Combobox(
            self, textvariable=self.resolution_var, values=list(RESOLUTIONS.keys()),
            state="readonly", style="Glass.TCombobox", width=15,
        )
        row.field(resolution_combo, 135)

        row.newline(40)
        row.label("Audio:", 58)
        self.audio_var = tk.StringVar(value="Copy (no re-encode)")
        audio_combo = ttk.Combobox(
            self, textvariable=self.audio_var, values=list(AUDIO_MODES.keys()),
            state="readonly", style="Glass.TCombobox", width=22,
        )
        row.field(audio_combo, 190)
        row.label("Container:", 78)
        self.container_var = tk.StringVar(value="mp4")
        container_combo = ttk.Combobox(
            self, textvariable=self.container_var, values=CONTAINERS,
            state="readonly", style="Glass.TCombobox", width=6,
        )
        row.field(container_combo, 65)
        self.deinterlace_var = tk.BooleanVar(value=False)
        self.deinterlace_toggle = self.toggle(row.x, row.y + 2, False, self._on_deinterlace_toggled)
        self.text(row.x + 50, row.y + 13, "Deinterlace (old/DVD)", font=FONT_CAPTION, fill=TEXT_MUTED)

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

        self._refresh_status_text()
        self._check_ffmpeg()

    def _move_button(self, btn, x, y) -> None:
        btn.x, btn.y = x, y
        self.coords(btn.image_id, x, y)
        self.coords(btn.text_id, x + btn.w / 2, y + btn.h / 2)

    def _refresh_status_text(self, *_args) -> None:
        self.itemconfig(self.status_text_id, text=self.status_var.get())

    def _check_ffmpeg(self) -> None:
        if not find_ffmpeg() or not find_ffprobe():
            self.itemconfig(
                self.warning_id,
                text="ffmpeg/ffprobe not found on PATH — install ffmpeg to use this tab "
                "(sudo apt install ffmpeg / brew install ffmpeg / ffmpeg.org)",
            )
            self.add_files_btn.set_enabled(False)
            self.start_btn.set_enabled(False)

    def _on_codec_changed(self) -> None:
        codec = VIDEO_CODECS[self.codec_var.get()]
        self.crf_var.set(DEFAULT_CRF[codec])
        self.preset_var.set(default_preset_for_codec(codec))
        self.preset_combo.config(values=PRESETS_AV1 if codec == "libsvtav1" else PRESETS_X26X)
        profiles = PROFILES_BY_CODEC[codec]
        self.profile_combo.config(values=profiles)
        if self.profile_var.get() not in profiles:
            self.profile_var.set(NO_PROFILE)

    def _on_quality_preset_changed(self) -> None:
        name = self.quality_preset_var.get()
        if name == CUSTOM_PRESET:
            return
        preset = QUALITY_PRESETS[name]
        codec_label = next(k for k, v in VIDEO_CODECS.items() if v == preset.codec)
        self.codec_var.set(codec_label)
        self._on_codec_changed()
        self.crf_var.set(preset.crf)
        self.preset_var.set(preset.speed)
        self.profile_var.set(preset.profile or NO_PROFILE)

    def _on_deinterlace_toggled(self, on: bool) -> None:
        self.deinterlace_var.set(on)

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
        profile = self.profile_var.get()
        return VideoOptions(
            codec=codec,
            crf=self.crf_var.get(),
            preset=self.preset_var.get(),
            profile=None if profile == NO_PROFILE else profile,
            target_height=RESOLUTIONS[self.resolution_var.get()],
            audio_mode=AUDIO_MODES[self.audio_var.get()],
            deinterlace=self.deinterlace_var.get(),
        )

    def _output_path_for(self, input_path: str) -> str:
        out_dir = self.output_dir_var.get().strip() or os.path.dirname(input_path)
        stem = os.path.splitext(os.path.basename(input_path))[0]
        ext = "." + self.container_var.get()
        candidate = os.path.join(out_dir, f"{stem}_compressed{ext}")
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

        self.start_btn.set_enabled(False)
        self.cancel_btn.set_enabled(True)
        self._runner = BatchRunner()
        runner = self._runner

        def job(item: str, should_stop, report):
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
    columns = ("name", "status", "progress", "saved")
    tree = ttk.Treeview(
        frame, columns=columns, show="headings", selectmode="extended", style="Glass.Treeview"
    )
    for col, label, width, anchor in [
        ("name", "File", 380, "w"),
        ("status", "Status", 150, "w"),
        ("progress", "Progress", 150, "center"),
        ("saved", "Saved", 120, "e"),
    ]:
        tree.heading(col, text=label)
        tree.column(col, width=width, anchor=anchor)
    scrollbar = ttk.Scrollbar(frame, orient="vertical", command=tree.yview, style="Glass.Vertical.TScrollbar")
    tree.configure(yscrollcommand=scrollbar.set)
    tree.pack(side="left", fill="both", expand=True)
    scrollbar.pack(side="right", fill="y")
    return frame, tree
