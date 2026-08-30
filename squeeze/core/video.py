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
from squeeze.core.ffmpeg_util import find_ffmpeg

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


@dataclass
class VideoOptions:
    codec: str = "libx264"
    crf: int = 23
    preset: str = "medium"
    target_height: Optional[int] = None  # None = keep source resolution
    audio_mode: str = "copy"  # "copy" | "none" | "aac_96" | "aac_128" | "aac_192"


def build_ffmpeg_command(
    ffmpeg_bin: str, input_path: str, output_path: str, opts: VideoOptions
) -> list[str]:
    cmd = [ffmpeg_bin, "-y", "-i", input_path]

    cmd += ["-c:v", opts.codec, "-crf", str(opts.crf), "-preset", opts.preset]

    if opts.target_height:
        # -2 keeps width even and preserves aspect ratio automatically.
        cmd += ["-vf", f"scale=-2:{opts.target_height}"]

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
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1
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
