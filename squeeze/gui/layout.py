"""Small layout helpers shared by every tab, so row-building code doesn't
repeat the same label+field positioning arithmetic three times over.
"""

from __future__ import annotations

from squeeze.gui.glass import FONT_BODY, TEXT_MUTED


class RowBuilder:
    """Lays out a sequence of "label: field" pairs left-to-right on a
    GlassCanvas starting at a fixed (x, y), wrapping style decisions
    (label font/color, vertical centering against the field) in one place.
    """

    def __init__(self, canvas, x: int, y: int, field_height: int = 34):
        self.canvas = canvas
        self.x = x
        self.y = y
        self.field_height = field_height

    def label(self, text: str, width: int = 0) -> int:
        """Draw a label at the current cursor, advance past it (plus
        `width` if given, else the label's own rendered width), return the
        new cursor x.
        """
        self.canvas.text(
            self.x, self.y + self.field_height // 2, text, font=FONT_BODY, fill=TEXT_MUTED, anchor="w"
        )
        advance = width or (8 * len(text) + 10)
        self.x += advance
        return self.x

    def field(self, widget, width: int, height: int = 0, gap: int = 20) -> int:
        """Embed a widget at the current cursor, advance past it + `gap`."""
        h = height or self.field_height
        self.canvas.embed(self.x, self.y + (self.field_height - h) // 2, widget, width=width, height=h)
        self.x += width + gap
        return self.x

    def newline(self, x: int, dy: int = 38) -> None:
        self.x = x
        self.y += dy
