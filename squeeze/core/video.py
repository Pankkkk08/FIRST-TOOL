"""ffmpeg-backed video compression with progress reporting and cancellation.

Design notes:
- Progress comes from ffmpeg's own `-progress pipe:1` machinery (key=value
  lines on stdout), matched against the source duration from ffprobe.
- stderr is merged into the same stream (`stderr=STDOUT`) and read on the
  same thread as stdout instead of left unread, so ffmpeg can never block
  on a full OS pipe buffer while writing log output nobody is draining.
- Cancellation is cooperative: a reader thread feeds lines into a Queue;
  the main loop polls that queue with a timeout so it can also check
  `should_stop()` regularly and `terminate()` the subprocess promptly,
  rather than blocking forever on a blocking readline().
"""

from __future__ import annotations

import os
import queue
import subprocess
import threading
from dataclasses import dataclass
from typing import Callable, Optional

from squeeze.core.common import CompressResult
from squeeze.core.ffmpeg_util import SUBPROCESS_CREATION_FLAGS, find_ffmpeg

VIDEO_CODECS = {
    "H.264 (libx264) — widest compatibility": "libx264",
    "H.265 / HEVC (libx265) — smaller files": "libx265",
    "AV1 (libsvtav1) — smallest, needs newer players": "libsvtav1",
}

# CRF ranges differ conceptually per encoder but ffmpeg accepts 0-51 for all
# three of these; lower = higher quality/bigger file. These are the values
# HandBrake itself ships as "sane default" for each family.
DEFAULT_CRF = {"libx264": 23, "libx265": 26, "libsvtav1": 30}


def default_preset_for_codec(codec: str) -> str:
    if codec == "libsvtav1":
        return "6"  # 0 (slowest/best) .. 13 (fastest); 6 is a balanced default
    return "medium"  # x264/x265 preset scale: ultrafast..veryslow


@dataclass(frozen=True)
class QualityPreset:
    """One row of a named quality ladder: codec + CRF + encoder speed +
    (optionally) an H.264/H.265 profile, bundled together like a HandBrake
    preset — see QUALITY_PRESETS below for where the numbers come from.
    """

    codec: str
    crf: int
    speed: str  # x264/x265 -preset value, or SVT-AV1's numeric preset as a string
    profile: Optional[str] = None


# HandBrake ships a Fast/HQ/Super HQ quality ladder per codec as its own
# built-in presets, tuned by its maintainers over many releases. Rather than
# guess at "reasonable" CRF/speed/profile combinations, these are lifted
# directly from HandBrake's own preset definitions —
# https://github.com/HandBrake/HandBrake/blob/master/preset/preset_builtin.json
# (x264: "Fast/HQ/Super HQ 1080p30"; x265: "Fast/HQ/Super HQ 2160p60 4K HEVC";
# AV1: "Fast/HQ/Super HQ 2160p60 4K AV1", CRF rounded to the nearest int since
# this app's CRF field is integer-only). "Custom" leaves whatever is already
# selected below alone — picking a preset just seeds sensible starting values
# that stay fully editable afterward, the same way HandBrake's own preset
# picker works.
QUALITY_PRESETS: dict[str, QualityPreset] = {
    "Fast (H.264)": QualityPreset("libx264", 22, "fast", "main"),
    "HQ (H.264)": QualityPreset("libx264", 20, "slow", "high"),
    "Super HQ (H.264)": QualityPreset("libx264", 18, "veryslow", "high"),
    "Fast (H.265/HEVC)": QualityPreset("libx265", 24, "faster", "main"),
    "HQ (H.265/HEVC)": QualityPreset("libx265", 22, "medium", "main"),
    "Super HQ (H.265/HEVC)": QualityPreset("libx265", 20, "slow", "main"),
    "Fast (AV1)": QualityPreset("libsvtav1", 34, "6", None),
    "HQ (AV1)": QualityPreset("libsvtav1", 30, "4", None),
    "Super HQ (AV1)": QualityPreset("libsvtav1", 25, "3", None),
}


@dataclass
class VideoOptions:
    codec: str = "libx264"
    crf: int = 23
    preset: str = "medium"
    profile: Optional[str] = None  # e.g. "main"/"high" (x264/x265 only)
    target_height: Optional[int] = None  # None = keep source resolution
    audio_mode: str = "copy"  # "copy" | "none" | "aac_96" | "aac_128" | "aac_192"
    deinterlace: bool = False  # yadif filter, for old interlaced sources


# H.264/H.265 profiles each require a specific pixel format (main/high need
# 4:2:0 8-bit, main10 needs 4:2:0 10-bit) — HandBrake normalizes color
# format internally whenever a profile is selected. Without this, setting
# -profile:v on a source ffmpeg would otherwise encode at a different chroma
# subsampling (e.g. some screen recordings, or ffmpeg's own lavfi test
# sources, default to 4:4:4) makes the encoder fail outright rather than
# silently do the wrong thing.
_PROFILE_PIX_FMT = {
    ("libx264", "main"): "yuv420p",
    ("libx264", "high"): "yuv420p",
    ("libx265", "main"): "yuv420p",
    ("libx265", "main10"): "yuv420p10le",
}


def build_ffmpeg_command(
    ffmpeg_bin: str, input_path: str, output_path: str, opts: VideoOptions
) -> list[str]:
    cmd = [ffmpeg_bin, "-y", "-i", input_path]

    cmd += ["-c:v", opts.codec, "-crf", str(opts.crf), "-preset", opts.preset]
    if opts.profile:
        cmd += ["-profile:v", opts.profile]
        pix_fmt = _PROFILE_PIX_FMT.get((opts.codec, opts.profile))
        if pix_fmt:
            cmd += ["-pix_fmt", pix_fmt]

    vf_parts = []
    if opts.deinterlace:
        vf_parts.append("yadif")
    if opts.target_height:
        # -2 keeps width even and preserves aspect ratio automatically.
        vf_parts.append(f"scale=-2:{opts.target_height}")
    if vf_parts:
        cmd += ["-vf", ",".join(vf_parts)]

    if opts.audio_mode == "copy":
        cmd += ["-c:a", "copy"]
    elif opts.audio_mode == "none":
        cmd += ["-an"]
    else:
        bitrate_k = opts.audio_mode.split("_")[-1]
        cmd += ["-c:a", "aac", "-b:a", f"{bitrate_k}k"]

    ext = os.path.splitext(output_path)[1].lower()
    if ext == ".mp4":
        cmd += ["-movflags", "+faststart"]

    cmd += ["-progress", "pipe:1", "-nostats", "-loglevel", "error", output_path]
    return cmd


def compress_video(
    input_path: str,
    output_path: str,
    opts: VideoOptions,
    duration_sec: float = 0.0,
    on_progress: Optional[Callable[[float, str], None]] = None,
    should_stop: Optional[Callable[[], bool]] = None,
    ffmpeg_bin: Optional[str] = None,
) -> CompressResult:
    exe = ffmpeg_bin or find_ffmpeg()
    if not exe:
        return CompressResult(success=False, message="ffmpeg was not found on PATH")

    input_size = os.path.getsize(input_path) if os.path.isfile(input_path) else 0
    cmd = build_ffmpeg_command(exe, input_path, output_path, opts)

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            creationflags=SUBPROCESS_CREATION_FLAGS,
        )
    except OSError as exc:
        return CompressResult(success=False, message=f"could not start ffmpeg: {exc}")

    line_queue: "queue.Queue[Optional[str]]" = queue.Queue()

    def reader() -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            line_queue.put(line)
        line_queue.put(None)  # sentinel: stdout closed, process is finishing

    reader_thread = threading.Thread(target=reader, daemon=True)
    reader_thread.start()

    error_lines: list[str] = []
    cancelled = False

    while True:
        if should_stop is not None and should_stop():
            proc.terminate()
            cancelled = True
            break
        try:
            line = line_queue.get(timeout=0.2)
        except queue.Empty:
            continue
        if line is None:
            break
        line = line.strip()
        if not line:
            continue
        if "=" in line and line.split("=", 1)[0].isidentifier():
            key, _, value = line.partition("=")
            if key == "out_time_ms" and on_progress is not None and duration_sec > 0:
                try:
                    out_us = int(value)
                except ValueError:
                    out_us = 0
                fraction = min(1.0, (out_us / 1_000_000) / duration_sec)
                on_progress(fraction, "")
            elif key == "speed" and on_progress is not None:
                on_progress(-1.0, value)  # -1 = "don't change fraction, just update speed text"
        else:
            error_lines.append(line)

    reader_thread.join(timeout=5)
    try:
        returncode = proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        returncode = proc.wait()

    if cancelled:
        if os.path.isfile(output_path):
            try:
                os.remove(output_path)  # don't leave a half-written file behind
            except OSError:
                pass
        return CompressResult(success=False, message="Cancelled", input_size=input_size)

    if returncode != 0:
        detail = "\n".join(error_lines[-10:]) or f"ffmpeg exited with code {returncode}"
        return CompressResult(success=False, message=detail, input_size=input_size)

    output_size = os.path.getsize(output_path) if os.path.isfile(output_path) else 0
    return CompressResult(
        success=True, message="OK", input_size=input_size, output_size=output_size
    )
