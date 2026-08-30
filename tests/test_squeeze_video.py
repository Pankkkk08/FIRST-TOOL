import os
import shutil

import pytest

from squeeze.core.ffmpeg_util import find_ffmpeg, find_ffprobe, probe, is_video_file
from squeeze.core.video import VideoOptions, build_ffmpeg_command, compress_video

pytestmark = pytest.mark.skipif(
    find_ffmpeg() is None or find_ffprobe() is None, reason="ffmpeg/ffprobe not installed"
)


def _make_test_clip(path: str, duration: float = 1.0) -> None:
    """Generate a tiny synthetic video with ffmpeg's built-in test source."""
    import subprocess

    cmd = [
        find_ffmpeg(), "-y",
        "-f", "lavfi", "-i", f"testsrc=duration={duration}:size=320x240:rate=15",
        "-f", "lavfi", "-i", f"sine=duration={duration}",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "18",
        "-c:a", "aac",
        path,
    ]
    subprocess.run(cmd, capture_output=True, text=True, timeout=30, check=True)


def test_is_video_file():
    assert is_video_file("movie.MP4")
    assert is_video_file("clip.mkv")
    assert not is_video_file("photo.jpg")
    assert not is_video_file("notes.txt")


def test_build_ffmpeg_command_basics():
    opts = VideoOptions(codec="libx264", crf=23, preset="medium", target_height=480, audio_mode="aac_128")
    cmd = build_ffmpeg_command("ffmpeg", "in.mov", "out.mp4", opts)

    assert cmd[0] == "ffmpeg"
    assert "-i" in cmd and cmd[cmd.index("-i") + 1] == "in.mov"
    assert "libx264" in cmd
    assert "23" in cmd
    assert "scale=-2:480" in cmd
    assert "aac" in cmd and "128k" in cmd
    assert "+faststart" in cmd  # because output is .mp4
    assert cmd[-1] == "out.mp4"


def test_build_ffmpeg_command_audio_modes():
    copy_cmd = build_ffmpeg_command(
        "ffmpeg", "in.mp4", "out.mp4", VideoOptions(audio_mode="copy")
    )
    assert "-c:a" in copy_cmd and copy_cmd[copy_cmd.index("-c:a") + 1] == "copy"

    none_cmd = build_ffmpeg_command(
        "ffmpeg", "in.mp4", "out.mp4", VideoOptions(audio_mode="none")
    )
    assert "-an" in none_cmd


def test_probe_and_compress_roundtrip(tmp_path):
    src = str(tmp_path / "source.mp4")
    _make_test_clip(src, duration=1.0)

    info = probe(src)
    assert info.width == 320
    assert info.height == 240
    assert info.duration_sec == pytest.approx(1.0, abs=0.3)
    assert info.size_bytes > 0

    out = str(tmp_path / "compressed.mp4")
    progress_updates = []

    def on_progress(fraction, speed):
        progress_updates.append((fraction, speed))

    result = compress_video(
        src, out, VideoOptions(codec="libx264", crf=30, preset="ultrafast"),
        duration_sec=info.duration_sec, on_progress=on_progress,
    )

    assert result.success, result.message
    assert os.path.isfile(out)
    assert result.output_size > 0
    assert result.input_size == info.size_bytes
    # We should have received at least one real fraction update (not just speed pings).
    assert any(f >= 0 for f, _ in progress_updates)


def test_compress_video_missing_ffmpeg_reports_error(tmp_path, monkeypatch):
    src = str(tmp_path / "source.mp4")
    _make_test_clip(src, duration=1.0)
    out = str(tmp_path / "out.mp4")

    result = compress_video(src, out, VideoOptions(), ffmpeg_bin="/nonexistent/ffmpeg")
    assert not result.success
    assert "ffmpeg" in result.message.lower() or result.message


def test_compress_video_cancellation_removes_partial_output(tmp_path):
    src = str(tmp_path / "source.mp4")
    _make_test_clip(src, duration=3.0)  # long enough that cancel definitely lands mid-encode
    out = str(tmp_path / "out.mp4")

    result = compress_video(
        src, out, VideoOptions(codec="libx264", crf=30, preset="veryslow"),
        duration_sec=3.0, should_stop=lambda: True,  # cancel immediately
    )

    assert not result.success
    assert result.message == "Cancelled"
    assert not os.path.isfile(out)
