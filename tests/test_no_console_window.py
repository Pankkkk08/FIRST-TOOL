"""Regression tests: ffmpeg/ffprobe must be spawned with
CREATE_NO_WINDOW on Windows.

Squeeze is a windowed app (PyInstaller console=False) — on Windows,
spawning a console program like ffmpeg from it pops up a black console
window over the UI unless creationflags=CREATE_NO_WINDOW is passed
explicitly. These tests pin that the flag is passed at both subprocess
call sites (ffprobe in ffmpeg_util.probe, ffmpeg in
video.compress_video); the flag constant itself is 0 (a no-op) on
non-Windows, so the same assertion runs everywhere.
"""

from __future__ import annotations

import json
import os

from squeeze.core import ffmpeg_util, video
from squeeze.core.video import VideoOptions


def test_creation_flags_are_noop_off_windows():
    if os.name == "nt":
        import subprocess

        assert ffmpeg_util.SUBPROCESS_CREATION_FLAGS == subprocess.CREATE_NO_WINDOW
    else:
        assert ffmpeg_util.SUBPROCESS_CREATION_FLAGS == 0


def test_encode_flags_add_below_normal_priority():
    """Encodes (and only encodes) run at below-normal priority — the
    HandBrake-style fix for the UI going "(Not responding)" while ffmpeg
    saturates every core.
    """
    if os.name == "nt":
        import subprocess

        assert ffmpeg_util.ENCODE_CREATION_FLAGS == (
            subprocess.CREATE_NO_WINDOW | subprocess.BELOW_NORMAL_PRIORITY_CLASS
        )
        assert ffmpeg_util.ENCODE_PREEXEC_FN is None
    else:
        assert ffmpeg_util.ENCODE_CREATION_FLAGS == 0
        assert ffmpeg_util.ENCODE_PREEXEC_FN is ffmpeg_util._nice_preexec


def test_probe_passes_creationflags(monkeypatch):
    captured = {}

    class FakeCompleted:
        returncode = 0
        stderr = ""
        stdout = json.dumps(
            {
                "format": {"duration": "1.0", "bit_rate": "100", "size": "10"},
                "streams": [],
            }
        )

    def fake_run(cmd, **kwargs):
        captured.update(kwargs)
        return FakeCompleted()

    monkeypatch.setattr(ffmpeg_util.subprocess, "run", fake_run)
    info = ffmpeg_util.probe("whatever.mp4", ffprobe_bin="ffprobe")

    assert info.duration_sec == 1.0
    assert captured["creationflags"] == ffmpeg_util.SUBPROCESS_CREATION_FLAGS


def test_compress_video_passes_creationflags(monkeypatch, tmp_path):
    captured = {}

    class FakeProc:
        stdout = iter(())  # compress_video's reader thread iterates this
        returncode = 0

        def wait(self, timeout=None):
            return 0

        def terminate(self):
            pass

        def kill(self):
            pass

    def fake_popen(cmd, **kwargs):
        captured.update(kwargs)
        return FakeProc()

    monkeypatch.setattr(video.subprocess, "Popen", fake_popen)

    src = tmp_path / "in.mp4"
    src.write_bytes(b"not a real video")
    out = tmp_path / "out.mp4"
    out.write_bytes(b"fake encoded output")

    result = video.compress_video(str(src), str(out), VideoOptions(), ffmpeg_bin="ffmpeg")

    assert result.success
    assert captured["creationflags"] == ffmpeg_util.ENCODE_CREATION_FLAGS
    assert captured["preexec_fn"] is ffmpeg_util.ENCODE_PREEXEC_FN
