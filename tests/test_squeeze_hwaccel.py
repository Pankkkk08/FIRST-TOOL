"""Tests for squeeze/core/hwaccel.py — all GPU-free by design: parsing
uses canned `ffmpeg -encoders` output, detection uses an injected fake
runner, and arg mapping is pure. The only untestable-here piece (does
the actual GPU encode work?) is covered by the runtime software-fallback
tests in test_webui_api.py.
"""

from __future__ import annotations

import subprocess

from squeeze.core import hwaccel

# Trimmed from real `ffmpeg -hide_banner -encoders` output: the header
# (whose "V..... = Video" legend line must not parse as an encoder), an
# audio encoder, software encoders, and a mix of hw encoders including
# ones we don't support (vaapi, av1_nvenc).
ENCODERS_OUTPUT = """Encoders:
 V..... = Video
 A..... = Audio
 S..... = Subtitle
 .F.... = Frame-level multithreading
 ------
 V....D libx264              libx264 H.264 / AVC / MPEG-4 AVC (codec h264)
 V....D h264_nvenc           NVIDIA NVENC H.264 encoder (codec h264)
 V..... h264_qsv             H.264 (Intel Quick Sync Video acceleration) (codec h264)
 V....D h264_vaapi           H.264/AVC (VAAPI) (codec h264)
 V....D av1_nvenc            NVIDIA NVENC av1 encoder (codec av1)
 V....D hevc_nvenc           NVIDIA NVENC hevc encoder (codec hevc)
 A....D aac                  AAC (Advanced Audio Coding)
"""


def test_parse_hw_encoders_from_real_shaped_output():
    assert hwaccel.parse_hw_encoders(ENCODERS_OUTPUT) == {
        "h264_nvenc",
        "h264_qsv",
        "hevc_nvenc",
    }


def test_parse_hw_encoders_empty_and_software_only():
    assert hwaccel.parse_hw_encoders("") == set()
    assert hwaccel.parse_hw_encoders(" V....D libx264   x264\n") == set()


class _FakeCompleted:
    def __init__(self, returncode=0, stdout=""):
        self.returncode = returncode
        self.stdout = stdout


def test_detect_hw_encoders_with_fake_runner():
    def runner(cmd, **kwargs):
        assert "-encoders" in cmd
        return _FakeCompleted(stdout=ENCODERS_OUTPUT)

    detected = hwaccel.detect_hw_encoders(ffmpeg_bin="ffmpeg", runner=runner)
    assert "hevc_nvenc" in detected


def test_detect_hw_encoders_failures_mean_empty():
    def raises(cmd, **kwargs):
        raise OSError("no ffmpeg")

    def times_out(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, 10)

    def nonzero(cmd, **kwargs):
        return _FakeCompleted(returncode=1)

    for runner in (raises, times_out, nonzero):
        assert hwaccel.detect_hw_encoders(ffmpeg_bin="ffmpeg", runner=runner) == set()


def test_select_hw_encoder_preference_order():
    assert hwaccel.select_hw_encoder("libx265", {"hevc_qsv", "hevc_nvenc"}) == "hevc_nvenc"
    assert hwaccel.select_hw_encoder("libx265", {"hevc_qsv"}) == "hevc_qsv"
    assert hwaccel.select_hw_encoder("libx264", {"hevc_nvenc"}) is None
    assert hwaccel.select_hw_encoder("libsvtav1", {"hevc_nvenc", "h264_nvenc"}) is None
    assert hwaccel.select_hw_encoder("libx264", set()) is None


def test_hw_encode_args_nvenc():
    args = hwaccel.hw_encode_args("hevc_nvenc", 26)
    assert args == [
        "-c:v", "hevc_nvenc", "-preset", "p4", "-tune", "hq",
        "-rc", "vbr", "-cq", "30", "-b:v", "0", "-pix_fmt", "yuv420p",
    ]


def test_hw_encode_args_qsv_and_amf():
    qsv = hwaccel.hw_encode_args("h264_qsv", 23)
    assert "-global_quality" in qsv and qsv[qsv.index("-global_quality") + 1] == "25"
    amf = hwaccel.hw_encode_args("hevc_amf", 26)
    for flag in ("-qp_i", "-qp_p", "-qp_b"):
        assert amf[amf.index(flag) + 1] == "28"


def test_hw_encode_args_videotoolbox_inverted_scale():
    args = hwaccel.hw_encode_args("hevc_videotoolbox", 23)
    # videotoolbox is 1-100, higher = better: crf 23 -> (51-23)*100/51 ≈ 55
    assert args[args.index("-q:v") + 1] == "55"


def test_hw_encode_args_clamped_at_both_ends():
    high = hwaccel.hw_encode_args("hevc_nvenc", 50)  # 50+4 clamps to 51
    assert high[high.index("-cq") + 1] == "51"
    vt_best = hwaccel.hw_encode_args("h264_videotoolbox", 0)
    assert vt_best[vt_best.index("-q:v") + 1] == "100"
    vt_worst = hwaccel.hw_encode_args("h264_videotoolbox", 51)
    assert vt_worst[vt_worst.index("-q:v") + 1] == "1"
