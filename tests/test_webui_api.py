import os
import subprocess
import time

import pytest
from PIL import Image

from squeeze.core.common import CompressResult
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


def test_get_capabilities_includes_hw_fields_and_caches_detection(monkeypatch):
    import squeeze.webui.api as api_module

    calls = {"n": 0}

    def fake_detect(*args, **kwargs):
        calls["n"] += 1
        return {"hevc_nvenc", "h264_qsv"}

    monkeypatch.setattr(api_module, "detect_hw_encoders", fake_detect)
    monkeypatch.setattr(api_module, "find_ffmpeg", lambda: "/usr/bin/ffmpeg")
    monkeypatch.setattr(api_module, "find_ffprobe", lambda: "/usr/bin/ffprobe")

    api = Api()
    caps = api.get_capabilities()
    assert caps["hw_encoders"] == ["h264_qsv", "hevc_nvenc"]  # sorted, JSON-safe
    assert caps["hw_available_for"] == {"libx264": True, "libx265": True}

    api.get_capabilities()
    assert calls["n"] == 1  # detection ran once, then cached


def _install_fake_video_pipeline(monkeypatch, api, encode_log, fail_hw_with="hw init failed"):
    """Fake probe + compress_video for hw-fallback tests: records each
    attempt's hw_encoder, fails hardware attempts, succeeds software ones.
    """
    import squeeze.webui.api as api_module
    from squeeze.core.ffmpeg_util import MediaInfo

    monkeypatch.setattr(
        api_module, "probe",
        lambda path: MediaInfo(path, 1.0, 1280, 720, "h264", "aac", 1000, 1000),
    )

    def fake_compress(item, out_path, opts, duration_sec=0.0, on_progress=None, should_stop=None, ffmpeg_bin=None):
        encode_log.append((item, opts.hw_encoder))
        if opts.hw_encoder is not None:
            return CompressResult(success=False, message=fail_hw_with)
        return CompressResult(success=True, message="OK", input_size=1000, output_size=400)

    monkeypatch.setattr(api_module, "compress_video", fake_compress)


def test_video_job_hw_failure_falls_back_to_software(monkeypatch):
    api = Api()
    api._hw_encoders = {"hevc_nvenc"}
    encode_log = []
    _install_fake_video_pipeline(monkeypatch, api, encode_log)

    res = api.start_video_job(
        ["/a.mp4", "/b.mp4"],
        {"codec": "libx265", "crf": 26, "preset": "medium", "use_hw": True},
    )
    assert res["ok"], res
    _wait_until(lambda: not api.get_video_status()["running"])

    # File 1: hw attempt then software retry; file 2 skips straight to
    # software because the broken encoder is remembered for the session.
    assert encode_log == [("/a.mp4", "hevc_nvenc"), ("/a.mp4", None), ("/b.mp4", None)]
    assert api._hw_failed == {"hevc_nvenc"}

    rows = {r["key"]: r for r in api.get_video_status()["rows"]}
    assert rows["/a.mp4"]["status"] == "Done (software fallback)"
    assert rows["/b.mp4"]["status"] == "Done"


def test_video_job_cancel_during_hw_does_not_fall_back(monkeypatch):
    api = Api()
    api._hw_encoders = {"hevc_nvenc"}
    encode_log = []
    _install_fake_video_pipeline(monkeypatch, api, encode_log, fail_hw_with="Cancelled")

    res = api.start_video_job(
        ["/a.mp4"], {"codec": "libx265", "crf": 26, "preset": "medium", "use_hw": True}
    )
    assert res["ok"], res
    _wait_until(lambda: not api.get_video_status()["running"])

    # A cancelled hw encode is a cancel, not a broken encoder.
    assert encode_log == [("/a.mp4", "hevc_nvenc")]
    assert api._hw_failed == set()
    assert api.get_video_status()["rows"][0]["status"] == "Cancelled"


def test_video_job_without_use_hw_never_touches_hw(monkeypatch):
    api = Api()
    api._hw_encoders = {"hevc_nvenc"}
    encode_log = []
    _install_fake_video_pipeline(monkeypatch, api, encode_log)

    res = api.start_video_job(["/a.mp4"], {"codec": "libx265", "crf": 26, "preset": "medium"})
    assert res["ok"], res
    _wait_until(lambda: not api.get_video_status()["running"])
    assert encode_log == [("/a.mp4", None)]


def test_get_file_sizes(tmp_path):
    api = Api()
    f = tmp_path / "a.bin"
    f.write_bytes(b"x" * 2048)
    folder = tmp_path / "sub"
    folder.mkdir()

    sizes = api.get_file_sizes([str(f), str(folder), "/no/such/file"])
    assert sizes == {str(f): 2048, str(folder): 0, "/no/such/file": 0}


def test_expand_dropped_paths_filters_by_tab(tmp_path):
    api = Api()
    (tmp_path / "movie.mp4").write_bytes(b"v")
    (tmp_path / "photo.jpg").write_bytes(b"p")
    (tmp_path / "notes.txt").write_bytes(b"t")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "clip.mkv").write_bytes(b"v")
    dropped = [str(tmp_path / "movie.mp4"), str(tmp_path / "photo.jpg"),
               str(tmp_path / "notes.txt"), str(sub)]

    videos = api.expand_dropped_paths(dropped, "video")
    assert sorted(os.path.basename(p) for p in videos) == ["clip.mkv", "movie.mp4"]

    photos = api.expand_dropped_paths(dropped, "photo")
    assert [os.path.basename(p) for p in photos] == ["photo.jpg"]

    # The archive tab takes anything, and keeps folders whole (they get
    # archived as folders, not walked into loose files).
    everything = api.expand_dropped_paths(dropped, "archive")
    assert everything == dropped


def test_expand_dropped_paths_ignores_nonexistent():
    api = Api()
    assert api.expand_dropped_paths(["/no/such/file.mp4"], "video") == []
    assert api.expand_dropped_paths(["/no/such/file.mp4"], "archive") == []


def test_on_drop_forwards_resolved_paths_to_frontend():
    api = Api()

    class FakeWindow:
        def __init__(self):
            self.scripts = []

        def evaluate_js(self, script):
            self.scripts.append(script)

    api.window = FakeWindow()
    # Shape matches what pywebview hands a DOM drop handler: the browser
    # event serialized to a dict, with pywebviewFullPath added per file.
    api._on_drop(
        {
            "dataTransfer": {
                "files": [
                    {"name": "a.mp4", "pywebviewFullPath": "/home/u/a.mp4"},
                    {"name": "no-path.mp4"},  # unresolved file: skipped
                ]
            }
        }
    )
    assert len(api.window.scripts) == 1
    assert 'window.squeezeHandleDrop(["/home/u/a.mp4"])' == api.window.scripts[0]

    # No resolvable paths at all -> no JS round-trip.
    api.window.scripts.clear()
    api._on_drop({"dataTransfer": {"files": [{"name": "x"}]}})
    api._on_drop({})
    assert api.window.scripts == []


def test_unique_path_avoids_collisions(tmp_path):
    from squeeze.webui.api import _unique_path

    (tmp_path / "archive.zip").write_bytes(b"x")
    (tmp_path / "archive_2.zip").write_bytes(b"x")

    result = _unique_path(str(tmp_path), "archive", ".zip")
    assert result == os.path.join(str(tmp_path), "archive_3.zip")
