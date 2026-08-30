"""Pillow-backed photo compression: re-encode, resize, optionally convert
format and strip metadata.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

from PIL import Image, ImageOps

from compressor.core.common import CompressResult

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff", ".tif"}

# Formats Pillow can write with a "quality" knob worth exposing.
LOSSY_FORMATS = {"JPEG", "WEBP"}


@dataclass
class PhotoOptions:
    quality: int = 80  # 1-100, only meaningful for JPEG/WEBP output
    max_dimension: Optional[int] = None  # longest side, in px; None = keep original
    output_format: str = "same"  # "same" | "JPEG" | "PNG" | "WEBP"
    strip_metadata: bool = True
    optimize: bool = True


def is_image_file(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in IMAGE_EXTENSIONS


def _resolve_output_format(input_path: str, opts: PhotoOptions) -> str:
    if opts.output_format != "same":
        return opts.output_format
    ext = os.path.splitext(input_path)[1].lower().lstrip(".")
    return {"jpg": "JPEG", "jpeg": "JPEG", "png": "PNG", "webp": "WEBP",
            "bmp": "BMP", "tif": "TIFF", "tiff": "TIFF"}.get(ext, "JPEG")


def default_output_extension(fmt: str) -> str:
    return {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp", "BMP": ".bmp", "TIFF": ".tiff"}.get(
        fmt, ".jpg"
    )


def compress_photo(input_path: str, output_path: str, opts: PhotoOptions) -> CompressResult:
    input_size = os.path.getsize(input_path) if os.path.isfile(input_path) else 0

    try:
        with Image.open(input_path) as img:
            # Bake the EXIF orientation tag into the pixels before we
            # (possibly) strip metadata, so photos taken on their side
            # don't come out sideways once the orientation tag is gone.
            img = ImageOps.exif_transpose(img)

            out_format = _resolve_output_format(input_path, opts)

            if out_format == "JPEG" and img.mode in ("RGBA", "P", "LA"):
                img = img.convert("RGB")

            if opts.max_dimension and max(img.width, img.height) > opts.max_dimension:
                img.thumbnail((opts.max_dimension, opts.max_dimension), Image.LANCZOS)

            save_kwargs = {"optimize": opts.optimize}
            if out_format in LOSSY_FORMATS:
                save_kwargs["quality"] = max(1, min(100, opts.quality))
            if out_format == "JPEG":
                save_kwargs["progressive"] = True

            if not opts.strip_metadata:
                exif = img.info.get("exif")
                if exif:
                    save_kwargs["exif"] = exif

            os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
            img.save(output_path, format=out_format, **save_kwargs)
    except Exception as exc:  # noqa: BLE001 - surfaced to the UI, not swallowed
        return CompressResult(success=False, message=str(exc), input_size=input_size)

    output_size = os.path.getsize(output_path) if os.path.isfile(output_path) else 0
    return CompressResult(
        success=True, message="OK", input_size=input_size, output_size=output_size
    )
