import os

import pytest
from PIL import Image

from squeeze.core.photo import (
    PhotoOptions,
    compress_photo,
    default_output_extension,
    is_image_file,
)


def _make_test_image(path: str, size=(800, 600), mode="RGB", color=(200, 60, 60)) -> None:
    img = Image.new(mode, size, color)
    # Add some noise-ish content so JPEG compression actually has something
    # to do (a flat color compresses to almost nothing regardless of quality).
    for x in range(0, size[0], 7):
        for y in range(0, size[1], 11):
            img.putpixel((x, y), ((x * 13) % 256, (y * 7) % 256, (x + y) % 256))
    img.save(path)


def test_is_image_file():
    assert is_image_file("photo.JPG")
    assert is_image_file("scan.png")
    assert not is_image_file("clip.mp4")


def test_default_output_extension():
    assert default_output_extension("JPEG") == ".jpg"
    assert default_output_extension("PNG") == ".png"
    assert default_output_extension("WEBP") == ".webp"


def test_compress_photo_jpeg_quality_reduces_size(tmp_path):
    src = str(tmp_path / "in.png")
    _make_test_image(src)

    high_q = str(tmp_path / "high.jpg")
    low_q = str(tmp_path / "low.jpg")

    r_high = compress_photo(src, high_q, PhotoOptions(quality=95, output_format="JPEG"))
    r_low = compress_photo(src, low_q, PhotoOptions(quality=20, output_format="JPEG"))

    assert r_high.success, r_high.message
    assert r_low.success, r_low.message
    assert r_low.output_size < r_high.output_size


def test_compress_photo_resizes_to_max_dimension(tmp_path):
    src = str(tmp_path / "in.jpg")
    _make_test_image(src, size=(2000, 1000))
    out = str(tmp_path / "out.jpg")

    result = compress_photo(src, out, PhotoOptions(max_dimension=500, output_format="JPEG"))

    assert result.success, result.message
    with Image.open(out) as img:
        assert max(img.width, img.height) == 500
        assert img.width == 500 and img.height == 250  # aspect ratio preserved


def test_compress_photo_does_not_upscale_smaller_images(tmp_path):
    src = str(tmp_path / "in.jpg")
    _make_test_image(src, size=(300, 200))
    out = str(tmp_path / "out.jpg")

    result = compress_photo(src, out, PhotoOptions(max_dimension=2000, output_format="JPEG"))

    assert result.success
    with Image.open(out) as img:
        assert (img.width, img.height) == (300, 200)


def test_compress_photo_format_conversion(tmp_path):
    src = str(tmp_path / "in.png")
    _make_test_image(src)
    out = str(tmp_path / "out.webp")

    result = compress_photo(src, out, PhotoOptions(output_format="WEBP", quality=80))

    assert result.success, result.message
    with Image.open(out) as img:
        assert img.format == "WEBP"


def test_compress_photo_rgba_png_to_jpeg_flattens_alpha(tmp_path):
    src = str(tmp_path / "in.png")
    img = Image.new("RGBA", (100, 100), (255, 0, 0, 128))
    img.save(src)
    out = str(tmp_path / "out.jpg")

    result = compress_photo(src, out, PhotoOptions(output_format="JPEG"))

    assert result.success, result.message
    with Image.open(out) as saved:
        assert saved.mode == "RGB"


def test_compress_photo_missing_input_reports_error(tmp_path):
    result = compress_photo(
        str(tmp_path / "does_not_exist.jpg"), str(tmp_path / "out.jpg"), PhotoOptions()
    )
    assert not result.success
    assert result.message
