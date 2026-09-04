"""Locate ffmpeg/ffprobe and probe media files for basic info.

Everything here shells out to local binaries — no bundled ffmpeg build,
so the app depends on the user having ffmpeg installed (README explains
how). We detect that up front and surface a clear message instead of
letting every video operation fail with a confusing traceback.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from typing import Optional

# Squeeze is a windowed app (PyInstaller console=False), so on Windows any
# console subprocess it spawns (ffmpeg/ffprobe) gets a brand-new black
# console window popped up over the UI unless CREATE_NO_WINDOW is passed.
# 0 is a no-op everywhere else (and on Pythons where the constant is absent).
SUBPROCESS_CREATION_FLAGS = (
    getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
)


def _nice_preexec() -> None:
    os.nice(10)


# Long ffmpeg encodes saturate every CPU core; at normal priority that
# starves the UI thread of CPU time and Windows flags the window
# "(Not responding)". HandBrake's fix, mirrored here: run the encoder at
# below-normal priority — identical speed on an otherwise-idle machine,
# but the UI (and the rest of the system) always gets scheduled first.
# Windows: an extra creationflag. POSIX: os.nice via preexec_fn — safe
# despite the general preexec_fn-with-threads caveat because the hook
# makes exactly one async-signal-safe syscall. Short-lived, latency-
# sensitive calls (ffprobe) deliberately stay at normal priority.
ENCODE_CREATION_FLAGS = SUBPROCESS_CREATION_FLAGS | (
    getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0) if os.name == "nt" else 0
)
ENCODE_PREEXEC_FN = None if os.name == "nt" else _nice_preexec

VIDEO_EXTENSIONS = {
    ".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".wmv", ".flv", ".mpg", ".mpeg", ".3gp",
}


def find_ffmpeg() -> Optional[str]:
    return shutil.which("ffmpeg")


def find_ffprobe() -> Optional[str]:
    return shutil.which("ffprobe")


@dataclass
class MediaInfo:
    path: str
    duration_sec: float
    width: int
    height: int
    video_codec: str
    audio_codec: str
    bitrate: int  # bits/sec, 0 if unknown
    size_bytes: int


class ProbeError(RuntimeError):
    pass


def probe(path: str, ffprobe_bin: Optional[str] = None) -> MediaInfo:
    """Run ffprobe and extract the fields the compression UI needs."""
    exe = ffprobe_bin or find_ffprobe()
    if not exe:
        raise ProbeError("ffprobe was not found on PATH")

    cmd = [
        exe, "-v", "error", "-print_format", "json",
        "-show_format", "-show_streams", path,
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
            creationflags=SUBPROCESS_CREATION_FLAGS,
        )
    except subprocess.TimeoutExpired as exc:
        raise ProbeError(f"ffprobe timed out on {path}") from exc

    if proc.returncode != 0:
        raise ProbeError(proc.stderr.strip() or f"ffprobe failed on {path}")

    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise ProbeError(f"could not parse ffprobe output for {path}") from exc

    fmt = data.get("format", {})
    streams = data.get("streams", [])
    video_stream = next((s for s in streams if s.get("codec_type") == "video"), {})
    audio_stream = next((s for s in streams if s.get("codec_type") == "audio"), {})

    duration = float(fmt.get("duration") or video_stream.get("duration") or 0.0)
    bitrate = int(fmt.get("bit_rate") or 0)
    size_bytes = int(fmt.get("size") or 0)

    return MediaInfo(
        path=path,
        duration_sec=duration,
        width=int(video_stream.get("width") or 0),
        height=int(video_stream.get("height") or 0),
        video_codec=video_stream.get("codec_name", ""),
        audio_codec=audio_stream.get("codec_name", ""),
        bitrate=bitrate,
        size_bytes=size_bytes,
    )


def is_video_file(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in VIDEO_EXTENSIONS
