import os
import subprocess
import time

import pytest
from PIL import Image

from squeeze.core.ffmpeg_util import find_ffmpeg, find_ffprobe
from squeeze.webui.api import Api

needs_ffmpeg = pytest.mark.skipif(
    find_ffmpeg() is None or find_ffprobe() is None, reason="ffmpeg/ffprobe not installed"
)


def _wait_until(predicate, timeout=20.0):
    end = time.time() + timeout
    while time.time() < end:
        if predicate():
            return
        time.sleep(0.05)
    raise AssertionError("condition not met in time")


def _make_test_clip(path: str, duration: float = 1.0) -> None:
    cmd = [
        find_ffmpeg(), "-y",
        "-f", "lavfi", "-i", f"testsrc=duration={duration}:size=320x240:rate=15",
        "-f", "lavfi", "-i", f"sine=duration={duration}",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "18", "-c:a", "aac",
        path,
    ]
    subprocess.run(cmd, capture_output=True, text=True, timeout=30, check=True)


def _make_test_image(path: str) -> None:
    img = Image.new("RGB", (800, 600), (10, 20, 30))
    for x in range(0, 800, 6):
        for y in range(0, 600, 9):
            img.putpixel((x, y), ((x * 13) % 256, (y * 7) % 256, (x + y) % 256))
    img.save(path)


def test_get_capabilities_shape():
    api = Api()
    caps = api.get_capabilities()
    assert "video_codecs" in caps
    assert "quality_presets" in caps
    assert "Fast (H.264)" in caps["quality_presets"]
    assert caps["quality_presets"]["Fast (H.264)"]["crf"] == 22
    assert "archive_formats" in caps
    assert isinstance(caps["ffmpeg_available"], bool)


@needs_ffmpeg
def test_video_job_real_encode(tmp_path):
    api = Api()
    src = str(tmp_path / "clip.mp4")
    _make_test_clip(src)

    res = api.start_video_job(
        [src],
        {"codec": "libx264", "crf": 30, "preset": "ultrafast", "profile": None, "audio_mode": "copy", "container": "mp4"},
    )
    assert res["ok"], res

    _wait_until(lambda: not api.get_video_status()["running"])
    status = api.get_video_status()
    row = status["rows"][0]
    assert row["status"] == "Done", status
    assert "%" in row["saved"]

    expected_out = os.path.join(str(tmp_path), "clip_compressed.mp4")
    assert os.path.isfile(expected_out)


@needs_ffmpeg
def test_video_job_rejects_when_already_running(tmp_path):
    api = Api()
    src = str(tmp_path / "clip.mp4")
    _make_test_clip(src, duration=2.0)

    first = api.start_video_job([src], {"codec": "libx264", "crf": 35, "preset": "veryslow"})
    assert first["ok"]
    second = api.start_video_job([src], {"codec": "libx264", "crf": 35, "preset": "veryslow"})
    assert not second["ok"]
    assert "already running" in second["error"]

    api.cancel_video_job()
    _wait_until(lambda: not api.get_video_status()["running"])


def test_video_job_rejects_empty_queue():
    api = Api()
    res = api.start_video_job([], {"codec": "libx264", "crf": 23, "preset": "medium"})
    assert not res["ok"]


def test_photo_job_real_compress(tmp_path):
    api = Api()
    src = str(tmp_path / "photo.png")
    _make_test_image(src)

    res = api.start_photo_job(
        [src],
        {"quality": 50, "resize": "Keep original size", "output_format": "JPEG", "strip_metadata": True},
    )
    assert res["ok"], res

    _wait_until(lambda: not api.get_photo_status()["running"])
    status = api.get_photo_status()
    row = status["rows"][0]
    assert row["status"] == "Done", status

    expected_out = os.path.join(str(tmp_path), "photo_compressed.jpg")
    assert os.path.isfile(expected_out)
    with Image.open(expected_out) as img:
        assert img.format == "JPEG"


def test_archive_bundle_job_real_zip(tmp_path):
    api = Api()
    a = tmp_path / "a.txt"
    a.write_text("hello world " * 500)
    b = tmp_path / "b.txt"
    b.write_text("more content " * 500)

    res = api.start_archive_bundle_job(
        [str(a), str(b)], {"format_label": "ZIP (.zip)", "level": 6, "output_dir": str(tmp_path)}
    )
    assert res["ok"], res

    _wait_until(lambda: not api.get_archive_bundle_status()["running"])
    status = api.get_archive_bundle_status()
    assert "Created" in status["overall"], status
    assert os.path.isfile(os.path.join(str(tmp_path), "archive.zip"))


def test_archive_gzip_job_real_gzip(tmp_path):
    api = Api()
    a = tmp_path / "a.log"
    a.write_text("log line\n" * 500)

    res = api.start_archive_gzip_job([str(a)], {"level": 6})
    assert res["ok"], res

    _wait_until(lambda: not api.get_archive_gzip_status()["running"])
    status = api.get_archive_gzip_status()
    assert status["rows"][0]["status"] == "Done", status
    assert os.path.isfile(str(a) + ".gz")


def test_unique_path_avoids_collisions(tmp_path):
    from squeeze.webui.api import _unique_path

    (tmp_path / "archive.zip").write_bytes(b"x")
    (tmp_path / "archive_2.zip").write_bytes(b"x")

    result = _unique_path(str(tmp_path), "archive", ".zip")
    assert result == os.path.join(str(tmp_path), "archive_3.zip")
