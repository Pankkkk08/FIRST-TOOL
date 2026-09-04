#!/usr/bin/env python3
"""Regenerate the app icons in packaging/ from packaging/icon-source.png.

The source is the full logo render (a dark rounded-square tile on a
solid black canvas). This script:
1. crops away the black canvas around the tile,
2. makes the corners outside the tile's rounded square transparent
   (an app icon with baked-in black corners looks broken on light
   desktops / the Start Menu),
3. writes the formats each platform wants:
     packaging/icon.png   — 512px master (Linux, docs, anything else)
     packaging/icon.ico   — multi-size Windows icon (exe + installer)
     packaging/icon.icns  — macOS bundle icon

Only needs re-running when the logo itself changes; the outputs are
committed so builds don't depend on this script.
"""

from __future__ import annotations

import os
import sys

from PIL import Image, ImageDraw

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACKAGING = os.path.join(REPO, "packaging")

# The tile's corner radius as a fraction of its side — measured from the
# source render (a macOS-style squircle-ish rounded square).
CORNER_RADIUS_FRACTION = 0.225


def find_tile_bbox(img: Image.Image) -> tuple[int, int, int, int]:
    """Bounding box of the icon tile: everything brighter than the pure
    black canvas (the tile itself is dark, but not #000)."""
    gray = img.convert("L")
    mask = gray.point(lambda v: 255 if v > 10 else 0)
    bbox = mask.getbbox()
    if not bbox:
        raise SystemExit("could not find the icon tile in the source image")
    return bbox


def rounded_square(img: Image.Image) -> Image.Image:
    side = min(img.size)
    img = img.resize((side, side), Image.LANCZOS).convert("RGBA")
    radius = int(side * CORNER_RADIUS_FRACTION)
    mask = Image.new("L", (side, side), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, side - 1, side - 1), radius=radius, fill=255)
    img.putalpha(mask)
    return img


def main() -> None:
    source = os.path.join(PACKAGING, "icon-source.png")
    if not os.path.isfile(source):
        sys.exit(f"missing {source}")

    img = Image.open(source)
    tile = rounded_square(img.crop(find_tile_bbox(img)))

    master = tile.resize((512, 512), Image.LANCZOS)
    master.save(os.path.join(PACKAGING, "icon.png"))

    master.save(
        os.path.join(PACKAGING, "icon.ico"),
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )

    tile.resize((1024, 1024), Image.LANCZOS).save(os.path.join(PACKAGING, "icon.icns"))

    for name in ("icon.png", "icon.ico", "icon.icns"):
        path = os.path.join(PACKAGING, name)
        print(f"wrote {path} ({os.path.getsize(path)} bytes)")


if __name__ == "__main__":
    main()
