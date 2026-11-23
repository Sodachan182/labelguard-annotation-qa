"""Server-side annotation overlay rendering with Pillow.

Coordinates flow through one transform, :class:`ViewTransform`, so what is
drawn is exactly what the source declares:

    canvas_x = (source_x − window_x0) × scale
    canvas_y = (source_y − window_y0) × scale

The window is the image frame, widened when geometry lies outside it so
out-of-bounds defects stay visible, or a padded crop around the selection when
"zoom to selection" is on.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal

from PIL import Image, ImageDraw, ImageFont

from labelguard.models import Annotation, GeometryType, ImageRecord, Severity

OverlayMode = Literal["all", "flagged", "selected", "none"]
MAX_ZOOM = 5.0

CATEGORY_PALETTE = [
    (121, 168, 222),  # steel blue
    (108, 195, 169),  # teal
    (196, 160, 230),  # lilac
    (222, 176, 120),  # sand
    (150, 200, 110),  # moss
    (230, 140, 175),  # rose
    (120, 200, 220),  # cyan
    (200, 190, 140),  # khaki
]

THEMES = {
    "dark": {
        "accent": (139, 152, 249),
        "critical": (232, 128, 128),
        "warning": (229, 181, 103),
        "info": (127, 172, 227),
        "frame_bg": (28, 31, 37),
        "outside_bg": (17, 19, 23),
        "grid": (44, 49, 58),
        "frame_line": (110, 118, 130),
        "veil": (8, 9, 11, 120),
        "tag_text": (13, 15, 18),
    },
    "light": {
        "accent": (79, 91, 213),
        "critical": (185, 58, 58),
        "warning": (154, 106, 18),
        "info": (47, 109, 176),
        "frame_bg": (250, 249, 246),
        "outside_bg": (232, 229, 223),
        "grid": (222, 218, 210),
        "frame_line": (140, 136, 128),
        "veil": (246, 245, 242, 120),
        "tag_text": (255, 255, 255),
    },
}


@dataclass(frozen=True)
class OverlayOptions:
    mode: OverlayMode = "all"
    show_labels: bool = True
    show_ids: bool = False
    zoom_to_selection: bool = False
    target_width: int = 1600
    theme: str = "dark"


@dataclass(frozen=True)
class ViewTransform:
    x0: float
    y0: float
    x1: float
    y1: float
    scale: float

    @property
    def size(self) -> tuple[int, int]:
        return (
            max(1, round((self.x1 - self.x0) * self.scale)),
            max(1, round((self.y1 - self.y0) * self.scale)),
        )

    def to_canvas(self, x: float, y: float) -> tuple[float, float]:
        return (x - self.x0) * self.scale, (y - self.y0) * self.scale

    def to_source(self, cx: float, cy: float) -> tuple[float, float]:
        return cx / self.scale + self.x0, cy / self.scale + self.y0


@dataclass
class RenderResult:
    image: Image.Image
    transform: ViewTransform
    has_pixels: bool
    pixel_size: tuple[int, int] | None
    declared_size: tuple[float, float]
    size_mismatch: bool
    drawn: int


def category_color(name: str, categories: Sequence[str]) -> tuple[int, int, int]:
    try:
        idx = list(categories).index(name)
    except ValueError:
        idx = sum(map(ord, name or "?"))
    return CATEGORY_PALETTE[idx % len(CATEGORY_PALETTE)]


def _finite_pts(pts: Iterable[Sequence[float]]) -> list[tuple[float, float]]:
    return [(float(p[0]), float(p[1])) for p in pts if len(p) >= 2 and math.isfinite(p[0]) and math.isfinite(p[1])]


def compute_window(
    width: float,
    height: float,
    annotations: Sequence[Annotation],
    selected: Annotation | None,
    zoom: bool,
    max_extra: float = 0.5,
) -> tuple[float, float, float, float]:
    """Source-space window to draw. Pure function, unit tested."""
    if zoom and selected is not None and selected.extent() is not None:
        x0, y0, x1, y1 = selected.extent()  # type: ignore[misc]
        w, h = max(x1 - x0, 24.0), max(y1 - y0, 24.0)
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        side_w, side_h = w * 1.8, h * 1.8
        # Keep the image aspect ratio so the canvas does not jump in size.
        aspect = width / height
        # Never magnify more than MAX_ZOOM× relative to the full frame: tiny objects
        # stay readable in context instead of becoming a blur.
        side_w = max(side_w, width / MAX_ZOOM)
        side_h = max(side_h, height / MAX_ZOOM)
        if side_w / side_h < aspect:
            side_w = side_h * aspect
        else:
            side_h = side_w / aspect
        return cx - side_w / 2, cy - side_h / 2, cx + side_w / 2, cy + side_h / 2
    x0, y0, x1, y1 = 0.0, 0.0, float(width), float(height)
    for ann in annotations:
        ext = ann.extent()
        if ext is None:
            continue
        x0, y0 = min(x0, ext[0]), min(y0, ext[1])
        x1, y1 = max(x1, ext[2]), max(y1, ext[3])
    lim_x, lim_y = width * max_extra, height * max_extra
    x0, y0 = max(x0, -lim_x), max(y0, -lim_y)
    x1, y1 = min(x1, width + lim_x), min(y1, height + lim_y)
    if (x0, y0, x1, y1) != (0.0, 0.0, float(width), float(height)):
        pad = 0.02 * max(width, height)
        x0, y0, x1, y1 = (
            x0 - pad if x0 < 0 else x0,
            y0 - pad if y0 < 0 else y0,
            x1 + pad if x1 > width else x1,
            y1 + pad if y1 > height else y1,
        )
    return x0, y0, x1, y1


@lru_cache(maxsize=8)
def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for name in ("DejaVuSans.ttf", "segoeui.ttf", "arial.ttf", "Arial.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def _corner_ticks(draw: ImageDraw.ImageDraw, box: tuple[float, float, float, float], color, w: int, off: int):
    """The LabelGuard selection mark: four L-shaped corner ticks."""
    x0, y0, x1, y1 = box[0] - off, box[1] - off, box[2] + off, box[3] + off
    ln = max(8 * w, min((x1 - x0), (y1 - y0)) * 0.22)
    for cx, cy, dx, dy in ((x0, y0, 1, 1), (x1, y0, -1, 1), (x0, y1, 1, -1), (x1, y1, -1, -1)):
        draw.line([(cx, cy), (cx + dx * ln, cy)], fill=color, width=w + 1)
        draw.line([(cx, cy), (cx, cy + dy * ln)], fill=color, width=w + 1)


def render_overlay(
    record: ImageRecord,
    annotations: Sequence[Annotation],
    *,
    image_path: str | None = None,
    severities: dict[str, Severity] | None = None,
    selected_id: str | None = None,
    categories: Sequence[str] = (),
    options: OverlayOptions = OverlayOptions(),
) -> RenderResult:
    severities = severities or {}
    pal = THEMES.get(options.theme, THEMES["dark"])
    width = float(record.width) if record.has_valid_size else 0.0
    height = float(record.height) if record.has_valid_size else 0.0

    pixels: Image.Image | None = None
    if image_path and Path(image_path).is_file():
        try:
            pixels = Image.open(image_path)
            pixels.load()
            pixels = pixels.convert("RGB")
        except (OSError, ValueError, Image.DecompressionBombError):
            # Unreadable or oversized (decompression-bomb guard) files fall back to
            # the annotation-only canvas instead of crashing the Inspector.
            pixels = None
    if not (width > 0 and height > 0):
        if pixels is not None:
            width, height = float(pixels.width), float(pixels.height)
        else:
            exts = [a.extent() for a in annotations if a.extent()]
            width = max([e[2] for e in exts] + [640.0])  # type: ignore[index]
            height = max([e[3] for e in exts] + [400.0])  # type: ignore[index]

    selected = next((a for a in annotations if a.id == selected_id), None)
    if options.mode == "none":
        visible: list[Annotation] = []
    elif options.mode == "selected":
        visible = [selected] if selected else []
    elif options.mode == "flagged":
        visible = [a for a in annotations if a.id in severities or a.id == selected_id]
    else:
        visible = [a for a in annotations if not a.outside or a.id == selected_id]

    window = compute_window(width, height, visible, selected, options.zoom_to_selection)
    scale = options.target_width / (window[2] - window[0])
    tf = ViewTransform(*window, scale=scale)
    cw, ch = tf.size
    px = max(1, round(options.target_width / 800))

    canvas = Image.new("RGB", (cw, ch), pal["outside_bg"])
    fx0, fy0 = tf.to_canvas(0, 0)
    fx1, fy1 = tf.to_canvas(width, height)
    if pixels is not None:
        sx = pixels.width / width
        sy = pixels.height / height
        crop = (max(0.0, window[0]), max(0.0, window[1]), min(width, window[2]), min(height, window[3]))
        if crop[2] > crop[0] and crop[3] > crop[1]:
            region = pixels.crop((round(crop[0] * sx), round(crop[1] * sy), round(crop[2] * sx), round(crop[3] * sy)))
            dx0, dy0 = tf.to_canvas(crop[0], crop[1])
            dx1, dy1 = tf.to_canvas(crop[2], crop[3])
            size = (max(1, round(dx1 - dx0)), max(1, round(dy1 - dy0)))
            canvas.paste(region.resize(size, Image.Resampling.LANCZOS), (round(dx0), round(dy0)))
    else:
        d = ImageDraw.Draw(canvas)
        d.rectangle([fx0, fy0, fx1, fy1], fill=pal["frame_bg"])
        step = max(width, height) / 10
        gx = 0.0
        while gx <= width:
            x, _ = tf.to_canvas(gx, 0)
            d.line([(x, fy0), (x, fy1)], fill=pal["grid"], width=1)
            gx += step
        gy = 0.0
        while gy <= height:
            _, y = tf.to_canvas(0, gy)
            d.line([(fx0, y), (fx1, y)], fill=pal["grid"], width=1)
            gy += step

    layer = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    if window != (0.0, 0.0, width, height):
        draw.rectangle([fx0, fy0, fx1, fy1], outline=pal["frame_line"] + (255,), width=px)

    font = _font(11 * px)
    dense = len(visible) > 60
    line_w = px if dense else 2 * px

    def style(ann: Annotation) -> tuple[tuple[int, int, int], int]:
        sev = severities.get(ann.id)
        if sev is not None:
            return pal[sev.value], line_w + (px if not dense else 0)
        return category_color(ann.category, categories), line_w

    def draw_shape(ann: Annotation, color, width_px: int, alpha: int) -> None:
        c = (*color, alpha)
        if ann.bbox is not None:
            pts = _finite_pts([ann.bbox[:2], ann.bbox[2:]])
            if len(pts) == 2:
                (a0, b0), (a1, b1) = tf.to_canvas(*pts[0]), tf.to_canvas(*pts[1])
                draw.rectangle([min(a0, a1), min(b0, b1), max(a0, a1), max(b0, b1)], outline=c, width=width_px)
        for ring in ann.polygons:
            pts = [tf.to_canvas(*p) for p in _finite_pts(ring)]
            if len(pts) >= 2:
                draw.polygon(pts, fill=(*color, 28), outline=c, width=width_px)
            for p in pts:
                draw.ellipse([p[0] - px, p[1] - px, p[0] + px, p[1] + px], fill=c)
        if ann.geometry_type == GeometryType.POLYLINE:
            pts = [tf.to_canvas(*p) for p in _finite_pts(ann.points)]
            if len(pts) >= 2:
                draw.line(pts, fill=c, width=width_px, joint="curve")
        elif ann.points:
            r = 3 * px
            for i, p in enumerate(ann.points):
                if len(p) < 2 or not (math.isfinite(p[0]) and math.isfinite(p[1])):
                    continue
                v = ann.keypoint_visibility[i] if i < len(ann.keypoint_visibility) else 2
                if v == 0:
                    continue
                x, y = tf.to_canvas(p[0], p[1])
                x, y = min(max(x, r), cw - r), min(max(y, r), ch - r)
                if v == 1:
                    draw.ellipse([x - r, y - r, x + r, y + r], outline=c, width=max(1, px))
                else:
                    draw.ellipse([x - r, y - r, x + r, y + r], fill=c, outline=(0, 0, 0, 160))

    def tag(ann: Annotation, color) -> None:
        parts = []
        if options.show_labels and ann.category:
            parts.append(ann.category)
        if options.show_ids:
            parts.append(f"#{ann.id}")
        ext = ann.extent()
        if not parts or ext is None:
            return
        text = "  ".join(parts)
        x, y = tf.to_canvas(ext[0], ext[1])
        x_end, y_end = tf.to_canvas(ext[2], ext[3])
        if x_end < 0 or y_end < 0 or x > cw or y > ch:
            return  # object is outside the current view (zoomed); no edge-clamped tag clutter
        tb = draw.textbbox((0, 0), text, font=font)
        tw, th = tb[2] - tb[0] + 8 * px, tb[3] - tb[1] + 6 * px
        x = min(max(x, 0), cw - tw)
        y = y - th - px if y - th - px >= 0 else min(max(y + px, 0), ch - th)
        draw.rectangle([x, y, x + tw, y + th], fill=(*color, 235))
        draw.text((x + 4 * px, y + 3 * px - tb[1]), text, fill=pal["tag_text"], font=font)

    for ann in visible:
        if ann.id == selected_id:
            continue
        color, w = style(ann)
        draw_shape(ann, color, w, 230)
    for ann in visible:
        if ann.id != selected_id:
            tag(ann, style(ann)[0])

    if selected is not None:
        ext = selected.extent()
        if ext is not None:
            veil = Image.new("RGBA", (cw, ch), pal["veil"])
            vd = ImageDraw.Draw(veil)
            a0, b0 = tf.to_canvas(ext[0], ext[1])
            a1, b1 = tf.to_canvas(ext[2], ext[3])
            pad = 10 * px
            vd.rectangle([a0 - pad, b0 - pad, a1 + pad, b1 + pad], fill=(0, 0, 0, 0))
            layer = Image.alpha_composite(layer, veil)  # dim the other objects too
            draw = ImageDraw.Draw(layer)
            draw_shape(selected, pal["accent"], 2 * px, 255)
            _corner_ticks(draw, (a0, b0, a1, b1), (*pal["accent"], 255), 2 * px, 7 * px)
            tag(selected, pal["accent"])

    out = Image.alpha_composite(canvas.convert("RGBA"), layer).convert("RGB")
    pixel_size = (pixels.width, pixels.height) if pixels is not None else None
    mismatch = bool(
        pixel_size and record.has_valid_size and (abs(pixel_size[0] - width) > 0.5 or abs(pixel_size[1] - height) > 0.5)
    )
    return RenderResult(
        image=out,
        transform=tf,
        has_pixels=pixels is not None,
        pixel_size=pixel_size,
        declared_size=(width, height),
        size_mismatch=mismatch,
        drawn=len(visible),
    )
