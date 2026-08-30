"""A small glassmorphism toolkit for Tkinter.

Stock Tkinter/ttk widgets cannot do real background blur — there is no
compositor hook for it. This module fakes it the way every "glass UI in
Tkinter" implementation has to: render a colorful gradient "wallpaper"
once with Pillow, and for each panel, crop the wallpaper region behind
that panel, Gaussian-blur it, tint it, mask it to a rounded rect, and
draw the result as a Canvas image. The blur is real (it's the actual
backdrop content, blurred) — it just isn't *live*; a panel over moving
content behind it won't update in real time. For a desktop utility where
nothing moves behind the panels, that's not a visible difference.

Everything here draws onto `tk.Canvas` — actual interactive widgets
(Entry, Combobox, Treeview, ...) are layered on top via
`canvas.create_window(...)`, styled separately via `apply_ttk_theme()`
so they read as part of the same design system instead of native chrome
dropped onto a colorful background.

`GlassCanvas.draw()` is only ever called once per tab in this app,
because the window is fixed-size (see squeeze/app.py) — a resize would
otherwise re-trigger it and rebuild every widget from scratch, losing
queue contents, button enabled/disabled state, and Treeview selection.
If the app ever needs to become resizable, `draw()` needs to be split
into a one-time `build()` (construct widgets/buttons once) and a
`layout()` that only repositions them — do not just let `redraw()` call
a monolithic `draw()` again on every `<Configure>` event.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable, Optional

from PIL import Image, ImageDraw, ImageFilter, ImageTk

# ---------------------------------------------------------------------------
# Palette — a dark "aurora" gradient wallpaper with light glass cards on top,
# the same family of look as Raycast/Arc/macOS Big Sur+ vibrancy panels.
# ---------------------------------------------------------------------------

BG_BASE = (13, 15, 26)  # deep navy-charcoal, the wallpaper's base color
BLOB_COLORS = [
    (124, 108, 246),  # violet
    (45, 212, 191),  # teal
    (236, 111, 240),  # magenta
]

TEXT_PRIMARY = "#f4f4f8"
TEXT_MUTED = "#a6a6c2"
TEXT_FAINT = "#7a7a97"
ACCENT = "#8b7cf6"
ACCENT_HOVER = "#a599f8"
ACCENT_PRESS = "#7566e0"
SUCCESS = "#2dd4bf"
DANGER = "#f87171"
DANGER_HOVER = "#fb9a9a"

PANEL_TINT = (255, 255, 255, 30)
PANEL_BORDER = (255, 255, 255, 55)
PANEL_BLUR = 26
PANEL_RADIUS = 18

# Solid (non-blurred) fill for widgets that can't be transparent themselves
# (Treeview, ttk Entry/Combobox internals) — picked to sit visually flush
# inside a glass card rather than punching a flat hole in it.
SURFACE = "#1c1e30"
SURFACE_LIGHT = "#262842"

FONT_FAMILY = "Helvetica"
FONT_HEADING = (FONT_FAMILY, 15, "bold")
FONT_SUBHEAD = (FONT_FAMILY, 11, "bold")
FONT_BODY = (FONT_FAMILY, 10)
FONT_CAPTION = (FONT_FAMILY, 9)
FONT_MONO_ISH = (FONT_FAMILY, 10)


# ---------------------------------------------------------------------------
# Wallpaper generation
# ---------------------------------------------------------------------------


def build_wallpaper(width: int, height: int) -> Image.Image:
    """A soft, dark aurora-gradient background: a handful of large,
    heavily-blurred color blobs over a near-black base. Deterministic
    (fixed blob positions as fractions of size) so the app looks the same
    on every launch and every window size.
    """
    width, height = max(width, 1), max(height, 1)
    img = Image.new("RGB", (width, height), BG_BASE)

    # Blob positions/radii as fractions of the canvas so they scale with
    # the window instead of looking tiny on a large monitor.
    blobs = [
        (0.12, 0.10, 0.55, BLOB_COLORS[0]),
        (0.85, 0.15, 0.45, BLOB_COLORS[1]),
        (0.50, 0.95, 0.60, BLOB_COLORS[2]),
    ]

    overlay = Image.new("RGB", img.size, BG_BASE)
    for fx, fy, fr, color in blobs:
        blob_layer = Image.new("RGB", img.size, BG_BASE)
        draw = ImageDraw.Draw(blob_layer)
        cx, cy = fx * width, fy * height
        r = fr * max(width, height)
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=color)
        blob_layer = blob_layer.filter(ImageFilter.GaussianBlur(radius=max(width, height) * 0.12))
        overlay = Image.blend(overlay, blob_layer, alpha=0.55)

    img = Image.blend(img, overlay, alpha=0.9)
    return img.convert("RGB")


def _rounded_mask(size: tuple[int, int], radius: int, supersample: int = 4) -> Image.Image:
    """An antialiased rounded-rect alpha mask, rendered at `supersample`x
    and downscaled — Pillow's rounded_rectangle has no native antialiasing.
    """
    w, h = size
    big = (max(w * supersample, 1), max(h * supersample, 1))
    mask = Image.new("L", big, 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle([0, 0, big[0] - 1, big[1] - 1], radius=radius * supersample, fill=255)
    return mask.resize((max(w, 1), max(h, 1)), Image.LANCZOS)


def render_glass_panel(
    wallpaper: Image.Image,
    box: tuple[int, int, int, int],
    radius: int = PANEL_RADIUS,
    tint: tuple[int, int, int, int] = PANEL_TINT,
    border: Optional[tuple[int, int, int, int]] = PANEL_BORDER,
    blur: int = PANEL_BLUR,
) -> Image.Image:
    """Crop `box` out of `wallpaper`, blur it, tint it, and mask it to a
    rounded rect with a subtle light border — the actual "glass" image
    for one panel. `box` may extend past the wallpaper's edges; missing
    area is padded with the wallpaper's own edge color rather than left
    blank, so a panel near the window edge doesn't show a seam.
    """
    x0, y0, x1, y1 = box
    w, h = max(x1 - x0, 1), max(y1 - y0, 1)

    # Pad the crop by the blur radius so edge pixels don't sample outside
    # the wallpaper (which would otherwise show as a dark ring after blur).
    # Clamp the requested region to the wallpaper's actual bounds, then
    # paste it at the right offset into a BG_BASE-filled canvas so a panel
    # near the window edge still gets a full-size crop to blur.
    pad = blur
    crop_x0, crop_y0 = x0 - pad, y0 - pad
    crop_x1, crop_y1 = x1 + pad, y1 + pad
    clamped = (
        max(crop_x0, 0), max(crop_y0, 0),
        min(crop_x1, wallpaper.width), min(crop_y1, wallpaper.height),
    )
    padded = Image.new("RGB", (w + 2 * pad, h + 2 * pad), BG_BASE)
    if clamped[2] > clamped[0] and clamped[3] > clamped[1]:
        src = wallpaper.crop(clamped)
        paste_x = max(-crop_x0, 0)
        paste_y = max(-crop_y0, 0)
        padded.paste(src, (paste_x, paste_y))

    blurred = padded.filter(ImageFilter.GaussianBlur(radius=blur))
    blurred = blurred.crop((pad, pad, pad + w, pad + h)).convert("RGBA")

    tint_layer = Image.new("RGBA", (w, h), tint)
    glass = Image.alpha_composite(blurred, tint_layer)

    mask = _rounded_mask((w, h), radius)
    glass.putalpha(mask)

    if border:
        border_layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        bd = ImageDraw.Draw(border_layer)
        bd.rounded_rectangle([1, 1, w - 2, h - 2], radius=radius, outline=border, width=1)
        glass = Image.alpha_composite(glass, border_layer)

    return glass


# ---------------------------------------------------------------------------
# GlassCanvas: a Canvas that owns a wallpaper and knows how to draw panels,
# buttons, and toggles on top of it — the building block every tab uses.
# ---------------------------------------------------------------------------


class GlassCanvas(tk.Canvas):
    def __init__(self, master, **kwargs):
        kwargs.setdefault("highlightthickness", 0)
        kwargs.setdefault("background", "#0d0f1a")
        super().__init__(master, **kwargs)
        self._wallpaper: Optional[Image.Image] = None
        self._wallpaper_photo: Optional[ImageTk.PhotoImage] = None
        self._image_refs: list[ImageTk.PhotoImage] = []  # prevents GC of panel/button images
        self._buttons: list["GlassButton"] = []
        self._toggles: list["GlassToggle"] = []
        self.bind("<Configure>", self._on_configure, add="+")
        self._configure_after_id: Optional[str] = None

    def _on_configure(self, _event) -> None:
        # Debounce: a live drag-resize fires many <Configure> events; only
        # regenerate the (moderately expensive) blurred wallpaper once the
        # size has settled for a moment.
        if self._configure_after_id is not None:
            self.after_cancel(self._configure_after_id)
        self._configure_after_id = self.after(120, self.redraw)

    def redraw(self) -> None:
        """Subclasses (each tab) override `draw()` to lay out their panels
        and widgets; this regenerates the wallpaper and calls it.
        """
        w, h = self.winfo_width(), self.winfo_height()
        if w <= 1 or h <= 1:
            return
        self._wallpaper = build_wallpaper(w, h)
        self.delete("all")
        self._image_refs.clear()
        self._buttons.clear()
        self._toggles.clear()
        self._wallpaper_photo = ImageTk.PhotoImage(self._wallpaper)
        self.create_image(0, 0, image=self._wallpaper_photo, anchor="nw")
        self.draw()

    def draw(self) -> None:  # pragma: no cover - overridden by each tab
        pass

    # -- panels -----------------------------------------------------------
    def panel(self, x: int, y: int, w: int, h: int, **kwargs) -> None:
        if self._wallpaper is None:
            return
        img = render_glass_panel(self._wallpaper, (x, y, x + w, y + h), **kwargs)
        photo = ImageTk.PhotoImage(img)
        self._image_refs.append(photo)
        self.create_image(x, y, image=photo, anchor="nw")

    # -- widget embedding ---------------------------------------------------
    def embed(self, x: int, y: int, widget, **kwargs) -> int:
        return self.create_window(x, y, window=widget, anchor=kwargs.pop("anchor", "nw"), **kwargs)

    # -- text ---------------------------------------------------------------
    def text(self, x, y, text, font=FONT_BODY, fill=TEXT_PRIMARY, anchor="nw", **kwargs):
        return self.create_text(x, y, text=text, font=font, fill=fill, anchor=anchor, **kwargs)

    # -- buttons/toggles ------------------------------------------------------
    def button(self, x, y, w, h, text, command, style="primary", font=FONT_SUBHEAD) -> "GlassButton":
        btn = GlassButton(self, x, y, w, h, text, command, style=style, font=font)
        self._buttons.append(btn)
        return btn

    def toggle(self, x, y, on: bool, command: Callable[[bool], None]) -> "GlassToggle":
        tog = GlassToggle(self, x, y, on, command)
        self._toggles.append(tog)
        return tog


# ---------------------------------------------------------------------------
# GlassButton / GlassToggle: small canvas-drawn controls with hover/press
# feedback, styled to match the glass panels instead of native OS chrome.
# ---------------------------------------------------------------------------

_BUTTON_STYLES = {
    "primary": {"fill": ACCENT, "hover": ACCENT_HOVER, "press": ACCENT_PRESS, "text": "#151221", "disabled": "#4a4570"},
    "danger": {"fill": DANGER, "hover": DANGER_HOVER, "press": "#e05555", "text": "#2a0f0f", "disabled": "#7a4a4a"},
    "ghost": {"fill": (255, 255, 255, 24), "hover": (255, 255, 255, 40), "press": (255, 255, 255, 55), "text": TEXT_PRIMARY, "disabled": (255, 255, 255, 10)},
}


class GlassButton:
    def __init__(self, canvas: GlassCanvas, x, y, w, h, text, command, style="primary", font=FONT_SUBHEAD):
        self.canvas = canvas
        self.x, self.y, self.w, self.h = x, y, w, h
        self.command = command
        self.style_name = style
        self.spec = _BUTTON_STYLES[style]
        self.enabled = True
        self._photo_normal: Optional[ImageTk.PhotoImage] = None
        self._photo_hover: Optional[ImageTk.PhotoImage] = None
        self._photo_press: Optional[ImageTk.PhotoImage] = None
        self._photo_disabled: Optional[ImageTk.PhotoImage] = None
        self._render_states()
        self.image_id = canvas.create_image(x, y, image=self._photo_normal, anchor="nw")
        self.text_id = canvas.create_text(
            x + w / 2, y + h / 2, text=text, font=font, fill=self.spec["text"], anchor="center"
        )
        canvas._image_refs.extend(
            [self._photo_normal, self._photo_hover, self._photo_press, self._photo_disabled]
        )
        for item in (self.image_id, self.text_id):
            canvas.tag_bind(item, "<Enter>", self._on_enter)
            canvas.tag_bind(item, "<Leave>", self._on_leave)
            canvas.tag_bind(item, "<ButtonPress-1>", self._on_press)
            canvas.tag_bind(item, "<ButtonRelease-1>", self._on_release)

    def _fill_image(self, color) -> ImageTk.PhotoImage:
        img = Image.new("RGBA", (self.w, self.h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.rounded_rectangle([0, 0, self.w - 1, self.h - 1], radius=min(self.h // 2, 12), fill=_as_rgba(color))
        return ImageTk.PhotoImage(img)

    def _render_states(self) -> None:
        self._photo_normal = self._fill_image(self.spec["fill"])
        self._photo_hover = self._fill_image(self.spec["hover"])
        self._photo_press = self._fill_image(self.spec["press"])
        self._photo_disabled = self._fill_image(self.spec["disabled"])

    def _on_enter(self, _e):
        if self.enabled:
            self.canvas.itemconfig(self.image_id, image=self._photo_hover)
            self.canvas.config(cursor="hand2")

    def _on_leave(self, _e):
        if self.enabled:
            self.canvas.itemconfig(self.image_id, image=self._photo_normal)
            self.canvas.config(cursor="")

    def _on_press(self, _e):
        if self.enabled:
            self.canvas.itemconfig(self.image_id, image=self._photo_press)

    def _on_release(self, _e):
        if self.enabled:
            self.canvas.itemconfig(self.image_id, image=self._photo_hover)
            self.command()

    def set_enabled(self, enabled: bool) -> None:
        self.enabled = enabled
        img = self._photo_normal if enabled else self._photo_disabled
        self.canvas.itemconfig(self.image_id, image=img)
        self.canvas.itemconfig(self.text_id, fill=self.spec["text"] if enabled else TEXT_FAINT)

    def set_text(self, text: str) -> None:
        self.canvas.itemconfig(self.text_id, text=text)

    def set_style(self, style: str) -> None:
        """Re-skin this button to a different named style — used for
        radio-pill groups (e.g. Archive tab's mode selector) where the
        "selected" option is drawn as primary and the rest as ghost.
        """
        if style == self.style_name:
            return
        self.style_name = style
        self.spec = _BUTTON_STYLES[style]
        old_refs = (self._photo_normal, self._photo_hover, self._photo_press, self._photo_disabled)
        self._render_states()
        self.canvas._image_refs.extend(
            [self._photo_normal, self._photo_hover, self._photo_press, self._photo_disabled]
        )
        for ref in old_refs:
            if ref in self.canvas._image_refs:
                self.canvas._image_refs.remove(ref)
        img = self._photo_normal if self.enabled else self._photo_disabled
        self.canvas.itemconfig(self.image_id, image=img)
        self.canvas.itemconfig(self.text_id, fill=self.spec["text"] if self.enabled else TEXT_FAINT)


def _as_rgba(color) -> tuple[int, int, int, int]:
    """Normalize a color to an (r, g, b, a) tuple — colors in this module
    are written either as "#rrggbb" hex strings or (r, g, b[, a]) tuples,
    whichever reads more naturally at each call site.
    """
    if isinstance(color, str):
        return (*_hex_to_rgb(color), 255)
    if len(color) == 3:
        return (*color, 255)
    return color


class GlassToggle:
    """A small sliding on/off switch, the modern-UX replacement for a
    ttk.Checkbutton that would otherwise look like native OS chrome
    dropped onto a colorful background.
    """

    WIDTH, HEIGHT = 40, 22

    def __init__(self, canvas: GlassCanvas, x, y, on: bool, command: Callable[[bool], None]):
        self.canvas = canvas
        self.x, self.y = x, y
        self.on = on
        self.command = command
        self._track_on = self._track_image(True)
        self._track_off = self._track_image(False)
        canvas._image_refs.extend([self._track_on, self._track_off])
        self.image_id = canvas.create_image(x, y, image=self._image(), anchor="nw")
        canvas.tag_bind(self.image_id, "<Button-1>", self._on_click)
        canvas.tag_bind(self.image_id, "<Enter>", lambda e: canvas.config(cursor="hand2"))
        canvas.tag_bind(self.image_id, "<Leave>", lambda e: canvas.config(cursor=""))

    def _track_image(self, on: bool) -> ImageTk.PhotoImage:
        w, h = self.WIDTH, self.HEIGHT
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        # Off-state needs to read clearly against a *light* glass panel, so
        # a dark, fairly opaque track (not a near-invisible white wash) —
        # a translucent white only works as an "off" affordance on a dark
        # background, which these panels usually aren't.
        fill = (*_hex_to_rgb(ACCENT), 255) if on else (35, 33, 58, 200)
        draw.rounded_rectangle([0, 0, w - 1, h - 1], radius=h // 2, fill=fill)
        knob_d = h - 6
        knob_x = w - knob_d - 3 if on else 3
        draw.ellipse([knob_x, 3, knob_x + knob_d, 3 + knob_d], fill=(255, 255, 255, 255))
        return ImageTk.PhotoImage(img)

    def _image(self):
        return self._track_on if self.on else self._track_off

    def _on_click(self, _e):
        self.on = not self.on
        self.canvas.itemconfig(self.image_id, image=self._image())
        self.command(self.on)

    def set(self, on: bool) -> None:
        self.on = on
        self.canvas.itemconfig(self.image_id, image=self._image())


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    hex_color = hex_color.lstrip("#")
    return tuple(int(hex_color[i : i + 2], 16) for i in (0, 2, 4))


# ---------------------------------------------------------------------------
# ttk theming for the widgets that stay native (Entry, Combobox, Treeview,
# Spinbox, Scrollbar) — themed to sit flush inside a glass card instead of
# reading as native OS chrome.
# ---------------------------------------------------------------------------


def apply_ttk_theme(root: tk.Misc) -> None:
    style = ttk.Style(root)
    # 'clam' is the most reliably themable built-in across platforms —
    # unlike native themes (aqua/vista/xpnative) it actually honors color
    # overrides instead of drawing platform chrome regardless of settings.
    style.theme_use("clam")

    style.configure(
        "Glass.TEntry",
        fieldbackground=SURFACE,
        background=SURFACE,
        foreground=TEXT_PRIMARY,
        bordercolor=SURFACE_LIGHT,
        lightcolor=SURFACE_LIGHT,
        darkcolor=SURFACE_LIGHT,
        insertcolor=TEXT_PRIMARY,
        borderwidth=1,
        padding=6,
    )
    style.map("Glass.TEntry", fieldbackground=[("readonly", SURFACE)])

    style.configure(
        "Glass.TCombobox",
        fieldbackground=SURFACE,
        background=SURFACE,
        foreground=TEXT_PRIMARY,
        arrowcolor=TEXT_MUTED,
        bordercolor=SURFACE_LIGHT,
        lightcolor=SURFACE_LIGHT,
        darkcolor=SURFACE_LIGHT,
        borderwidth=1,
        padding=6,
    )
    style.map(
        "Glass.TCombobox",
        fieldbackground=[("readonly", SURFACE)],
        foreground=[("readonly", TEXT_PRIMARY)],
        selectbackground=[("readonly", SURFACE)],
        selectforeground=[("readonly", TEXT_PRIMARY)],
    )
    root.option_add("*TCombobox*Listbox.background", SURFACE)
    root.option_add("*TCombobox*Listbox.foreground", TEXT_PRIMARY)
    root.option_add("*TCombobox*Listbox.selectBackground", ACCENT)
    root.option_add("*TCombobox*Listbox.font", FONT_BODY)

    style.configure(
        "Glass.TSpinbox",
        fieldbackground=SURFACE,
        background=SURFACE,
        foreground=TEXT_PRIMARY,
        arrowcolor=TEXT_MUTED,
        bordercolor=SURFACE_LIGHT,
        borderwidth=1,
        padding=6,
    )

    style.configure(
        "Glass.Treeview",
        background=SURFACE,
        fieldbackground=SURFACE,
        foreground=TEXT_PRIMARY,
        rowheight=26,
        borderwidth=0,
        font=FONT_BODY,
    )
    style.map(
        "Glass.Treeview",
        background=[("selected", ACCENT)],
        foreground=[("selected", "#151221")],
    )
    style.configure(
        "Glass.Treeview.Heading",
        background=SURFACE_LIGHT,
        foreground=TEXT_MUTED,
        font=FONT_CAPTION,
        borderwidth=0,
        relief="flat",
    )
    style.map("Glass.Treeview.Heading", background=[("active", SURFACE_LIGHT)])

    style.configure(
        "Glass.Vertical.TScrollbar",
        background=SURFACE_LIGHT,
        troughcolor=SURFACE,
        bordercolor=SURFACE,
        arrowcolor=TEXT_MUTED,
        relief="flat",
    )

    style.configure(
        "Glass.Horizontal.TScale",
        background=SURFACE_LIGHT,  # the frame around the trough, not visible once themed below
        troughcolor=SURFACE,
        bordercolor=SURFACE,
        lightcolor=ACCENT,
        darkcolor=ACCENT,
    )
