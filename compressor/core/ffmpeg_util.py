"""Locate ffmpeg/ffprobe and probe media files for basic info.

Everything here shells out to local binaries — no bundled ffmpeg build,
so the app depends on the user having ffmpeg installed (README explains
how). We detect that up front and surface a clear message instead of
letting every video operation fail with a confusing traceback.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from typing import Optional

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
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
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
    import os

    return os.path.splitext(path)[1].lower() in VIDEO_EXTENSIONS
