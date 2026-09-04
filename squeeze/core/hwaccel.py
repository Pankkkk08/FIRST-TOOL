"""Hardware-accelerated video encoding: detection + ffmpeg arg mapping.

Every popular compressor (HandBrake, VidCoder, Compresto, ...) offers the
GPU's built-in H.264/H.265 encoder — typically 5-15x faster than software
and it moves the work off the CPU entirely, which keeps the UI responsive.
This module holds everything about that except the encode itself:

- which ffmpeg hw encoders map to which software codec family,
- parsing `ffmpeg -encoders` output to see what this build ships,
- picking one for a given codec,
- translating the app's CRF quality into each hw encoder's own quality
  knob (they don't speak CRF), anchored to the quality numbers
  HandBrake's built-in hardware presets use.

Testability note: a listed encoder is no guarantee of a working GPU or
driver — full ffmpeg builds list nvenc/qsv/amf on machines without the
matching hardware, and neither this dev sandbox nor CI has a GPU at all.
So everything here is a pure function (or takes an injectable `runner`),
fully unit-tested without hardware, and the ONE thing that can't be —
whether the actual GPU encode works — is handled at encode time instead:
the caller (squeeze/webui/api.py) retries a failed hardware attempt in
software automatically and remembers the broken encoder for the session.
"""

from __future__ import annotations

import re
import subprocess
from typing import Optional

from squeeze.core.ffmpeg_util import SUBPROCESS_CREATION_FLAGS, find_ffmpeg

# Per software codec family, the hw encoders that produce the same
# bitstream, in selection-preference order. videotoolbox only ever
# appears on macOS builds (where the others don't), so ordering it last
# costs nothing; on Windows a listed-but-driverless nvenc is exactly
# what the runtime software fallback exists for. AV1 (libsvtav1) stays
# software-only for now.
HW_ENCODER_CANDIDATES: dict[str, list[str]] = {
    "libx264": ["h264_nvenc", "h264_qsv", "h264_amf", "h264_videotoolbox"],
    "libx265": ["hevc_nvenc", "hevc_qsv", "hevc_amf", "hevc_videotoolbox"],
}

_ALL_CANDIDATES = {name for names in HW_ENCODER_CANDIDATES.values() for name in names}

# `ffmpeg -encoders` lists one encoder per line after a header, e.g.
# ` V....D h264_nvenc           NVIDIA NVENC H.264 encoder (codec h264)`
# — a 6-character capability column whose first letter is V for video.
_ENCODER_LINE = re.compile(r"^\s*V\S{5}\s+(\S+)", re.MULTILINE)


def parse_hw_encoders(encoders_output: str) -> set[str]:
    """The hardware encoders we can use, from `ffmpeg -encoders` output."""
    return set(_ENCODER_LINE.findall(encoders_output)) & _ALL_CANDIDATES


def detect_hw_encoders(
    ffmpeg_bin: Optional[str] = None, runner=subprocess.run
) -> set[str]:
    """What this machine's ffmpeg build *lists* (see module docstring for
    why listed != working, and how that gap is closed at encode time).
    Any failure here just means "no hardware acceleration offered".
    """
    exe = ffmpeg_bin or find_ffmpeg()
    if not exe:
        return set()
    try:
        proc = runner(
            [exe, "-hide_banner", "-encoders"],
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=SUBPROCESS_CREATION_FLAGS,
        )
    except (OSError, subprocess.SubprocessError):
        return set()
    if proc.returncode != 0:
        return set()
    return parse_hw_encoders(proc.stdout)


def select_hw_encoder(codec: str, detected: set[str]) -> Optional[str]:
    """First preferred hw encoder for the codec that's actually listed."""
    for candidate in HW_ENCODER_CANDIDATES.get(codec, []):
        if candidate in detected:
            return candidate
    return None


def _clamp(value: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, value))


def hw_encode_args(encoder: str, crf: int) -> list[str]:
    """The `-c:v ...` argument block for a hardware encoder, replacing
    the software `-c:v/-crf/-preset/-profile` block entirely.

    Hardware encoders need a few more quality points than x264/x265 for
    comparable output, so each family maps the app's CRF with the offset
    HandBrake's own hardware presets use relative to its software ones
    (preset_builtin.json: e.g. H.265 4K — x265 CRF ~24 vs NVENC 30,
    QSV/VCE 28). The trailing `-pix_fmt yuv420p` mirrors the software
    path's profile handling: hw encoders reject 4:2:2/4:4:4 input, so
    normalize chroma instead of failing on unusual sources.
    """
    if encoder.endswith("_nvenc"):
        quality = ["-rc", "vbr", "-cq", str(_clamp(crf + 4, 1, 51)), "-b:v", "0"]
        preset = ["-preset", "p4", "-tune", "hq"]
    elif encoder.endswith("_qsv"):
        quality = ["-global_quality", str(_clamp(crf + 2, 1, 51))]
        preset = ["-preset", "medium"]
    elif encoder.endswith("_amf"):
        q = str(_clamp(crf + 2, 0, 51))
        quality = ["-rc", "cqp", "-qp_i", q, "-qp_p", q, "-qp_b", q]
        preset = ["-quality", "balanced"]
    elif encoder.endswith("_videotoolbox"):
        # videotoolbox quality is 1-100, higher = better — invert CRF.
        quality = ["-q:v", str(_clamp(round((51 - crf) * 100 / 51), 1, 100))]
        preset = []
    else:
        raise ValueError(f"unknown hardware encoder family: {encoder}")

    return ["-c:v", encoder, *preset, *quality, "-pix_fmt", "yuv420p"]
