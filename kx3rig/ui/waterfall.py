"""Waterfall: the receiver's audio passband as a scrolling spectrogram.

Rows come from Station.rows (already noise-floor normalized to 0..1). They are
written into a ring image, colored through a 256-entry lookup table, uploaded
as one texture per frame, and drawn scaled with linear filtering inside a
rounded card. A thin spectrum trace sits on top.

The default palette is a single Adwaita-blue ramp whose floor matches the
view background, interpolated in OKLab so brightness rises evenly; it is
rebuilt when the system switches between light and dark.
"""

from __future__ import annotations

import gi
import numpy as np

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Gsk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, GLib, GObject, Graphene, Gsk, Gtk  # noqa: E402

HISTORY_ROWS = 320
TRACE_FRACTION = 0.22

PALETTES = {
    "blue": {
        "dark": [(0.0, "#1e1e1e"), (0.2, "#132a4f"), (0.45, "#1a5fb4"), (0.65, "#3584e4"), (0.85, "#99c1f1"), (1.0, "#ffffff")],
        "light": [(0.0, "#ffffff"), (0.2, "#dbe9fb"), (0.45, "#99c1f1"), (0.65, "#3584e4"), (0.85, "#1a5fb4"), (1.0, "#0b2a55")],
    },
    "heat": {
        "dark": [(0.0, "#1e1e1e"), (0.2, "#3b0f70"), (0.45, "#8c2981"), (0.65, "#de4968"), (0.85, "#fe9f6d"), (1.0, "#fcfdbf")],
        "light": [(0.0, "#ffffff"), (0.2, "#fcfdbf"), (0.45, "#fe9f6d"), (0.65, "#de4968"), (0.85, "#8c2981"), (1.0, "#3b0f70")],
    },
}


def _srgb_to_linear(c: np.ndarray) -> np.ndarray:
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def _linear_to_srgb(c: np.ndarray) -> np.ndarray:
    c = np.clip(c, 0.0, 1.0)
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * np.power(c, 1 / 2.4) - 0.055)


def _to_oklab(rgb: np.ndarray) -> np.ndarray:
    lin = _srgb_to_linear(rgb)
    m1 = np.array([[0.4122214708, 0.5363325363, 0.0514459929],
                   [0.2119034982, 0.6806995451, 0.1073969566],
                   [0.0883024619, 0.2817188376, 0.6299787005]])
    m2 = np.array([[0.2104542553, 0.7936177850, -0.0040720468],
                   [1.9779984951, -2.4285922050, 0.4505937099],
                   [0.0259040371, 0.7827717662, -0.8086757660]])
    return (m2 @ np.cbrt(m1 @ lin))


def _from_oklab(lab: np.ndarray) -> np.ndarray:
    m2i = np.array([[1.0, 0.3963377774, 0.2158037573],
                    [1.0, -0.1055613458, -0.0638541728],
                    [1.0, -0.0894841775, -1.2914855480]])
    m1i = np.array([[4.0767416621, -3.3077115913, 0.2309699292],
                    [-1.2684380046, 2.6097574011, -0.3413193965],
                    [-0.0041960863, -0.7034186147, 1.7076147010]])
    return _linear_to_srgb(m1i @ (m2i @ lab) ** 3)


def _hex(color: str) -> np.ndarray:
    return np.array([int(color[i:i + 2], 16) / 255.0 for i in (1, 3, 5)])


def build_lut(stops: list[tuple[float, str]]) -> np.ndarray:
    """256 x 4 uint8 RGBA, interpolated between stops in OKLab."""
    lut = np.zeros((256, 4), np.uint8)
    lut[:, 3] = 255
    labs = [(_to_oklab(_hex(c)), p) for p, c in stops]
    for i in range(256):
        t = i / 255.0
        for (lab0, p0), (lab1, p1) in zip(labs, labs[1:]):
            if p0 <= t <= p1:
                f = 0.0 if p1 == p0 else (t - p0) / (p1 - p0)
                rgb = _from_oklab(lab0 + (lab1 - lab0) * f)
                lut[i, :3] = np.round(rgb * 255).astype(np.uint8)
                break
    return lut


class Waterfall(Gtk.Widget):
    __gtype_name__ = "KX3Waterfall"

    __gsignals__ = {
        # Audio offset in Hz that was clicked (Shift held -> second arg True).
        "offset-clicked": (GObject.SignalFlags.RUN_FIRST, None, (float, bool)),
        # Scroll over the waterfall: +1 / -1 steps.
        "scroll-tune": (GObject.SignalFlags.RUN_FIRST, None, (int,)),
    }

    def __init__(self, station, span_hz: float = 3500.0, palette: str = "blue"):
        super().__init__()
        self.add_css_class("card")
        self.add_css_class("waterfall")
        self.set_overflow(Gtk.Overflow.HIDDEN)
        self.set_size_request(300, 160)
        self.set_hexpand(True)
        self.set_vexpand(True)
        self.station = station
        self.rows = station.subscribe_rows()
        self.span_hz = span_hz
        self.palette = palette
        self.mirror = False              # LSB: flip so RF increases to the right
        self.rx_offset: float | None = None
        self.tx_offset: float | None = None
        self.passband: tuple[float, float] | None = None
        self.marker_width_hz = 50.0
        # Smartscan findings: (t_start, t_end, low_hz, high_hz, kind), drawn
        # around the signal in the scrolling history so they move with it.
        self.marks: list[tuple[float, float, float, float, str]] = []
        self.rows_per_second = station.spectrum.sample_rate / station.spectrum.hop
        self._img: np.ndarray | None = None
        self._row = 0
        self._width = 0
        self._trace: np.ndarray | None = None
        self._texture = None
        self._lut = None
        self._hover_x: float | None = None
        self._tick = 0
        self._paused = False

        style = Adw.StyleManager.get_default()
        style.connect("notify::dark", lambda *a: self._rebuild_lut())
        self._rebuild_lut()

        click = Gtk.GestureClick()
        click.connect("released", self._on_click)
        self.add_controller(click)
        motion = Gtk.EventControllerMotion()
        motion.connect("motion", lambda c, x, y: self._set_hover(x))
        motion.connect("leave", lambda c: self._set_hover(None))
        self.add_controller(motion)
        scroll = Gtk.EventControllerScroll.new(Gtk.EventControllerScrollFlags.VERTICAL | Gtk.EventControllerScrollFlags.DISCRETE)
        scroll.connect("scroll", lambda c, dx, dy: (self.emit("scroll-tune", -1 if dy > 0 else 1), True)[1])
        self.add_controller(scroll)
        self.set_has_tooltip(True)
        self.connect("query-tooltip", self._on_tooltip)

        self.connect("map", lambda *a: self._start())
        self.connect("unmap", lambda *a: self._stop())

    # --- configuration -------------------------------------------------------------

    def set_palette(self, name: str) -> None:
        self.palette = name if name in PALETTES else "blue"
        self._rebuild_lut()

    def _rebuild_lut(self) -> None:
        dark = Adw.StyleManager.get_default().get_dark()
        self._lut = build_lut(PALETTES[self.palette]["dark" if dark else "light"])
        if self._img is not None:
            self._upload()

    def mark(self, spans: list[tuple[float, float, str]], t_start: float, t_end: float) -> None:
        """Outline signals found between two wall-clock times."""
        horizon = t_end - HISTORY_ROWS / self.rows_per_second
        self.marks = [m for m in self.marks if m[1] > horizon]
        for lo, hi, kind in spans:
            # One finding per place: a longer listen replaces the quick one.
            self.marks = [m for m in self.marks if not (m[0] == t_start and abs(m[2] - lo) < 300)]
            self.marks.append((t_start, t_end, lo, hi, kind))
        self.queue_draw()

    def clear(self) -> None:
        if self._img is not None:
            self._img[:] = 0
            self._upload()

    # --- frame pump ----------------------------------------------------------------------

    def _start(self) -> None:
        if not self._tick:
            self._tick = self.add_tick_callback(self._on_tick)

    def _stop(self) -> None:
        if self._tick:
            self.remove_tick_callback(self._tick)
            self._tick = 0

    def _on_tick(self, widget, clock) -> bool:
        rows = self.rows
        if not rows:
            return GLib.SOURCE_CONTINUE
        new = []
        while rows:
            try:
                new.append(rows.popleft())
            except IndexError:
                break
        if not new:
            return GLib.SOURCE_CONTINUE
        width = len(new[-1])
        if self._img is None or self._width != width:
            self._width = width
            self._img = np.zeros((HISTORY_ROWS, width), np.uint8)   # levels 0..255
            self._row = 0
        for row in new[-HISTORY_ROWS:]:
            if len(row) != width:
                continue
            self._row = (self._row - 1) % HISTORY_ROWS
            self._img[self._row] = np.clip(row * 255.0, 0, 255).astype(np.uint8)
        recent = np.mean(np.stack(new[-4:]), axis=0)
        self._trace = recent if self._trace is None or len(self._trace) != width else 0.6 * self._trace + 0.4 * recent
        self._upload()
        return GLib.SOURCE_CONTINUE

    def _upload(self) -> None:
        """Color the level history through the palette and upload it as a texture."""
        ordered = np.concatenate([self._img[self._row:], self._img[: self._row]])
        if self.mirror:
            ordered = ordered[:, ::-1]
        rgba = self._lut[ordered]
        data = GLib.Bytes.new(np.ascontiguousarray(rgba).tobytes())
        self._texture = Gdk.MemoryTexture.new(self._width, HISTORY_ROWS, Gdk.MemoryFormat.R8G8B8A8,
                                              data, self._width * 4)
        self.queue_draw()

    # --- geometry --------------------------------------------------------------------------

    def _x_for(self, hz: float) -> float:
        frac = hz / self.span_hz
        if self.mirror:
            frac = 1.0 - frac
        return frac * self.get_width()

    def _hz_for(self, x: float) -> float:
        frac = max(0.0, min(1.0, x / max(1, self.get_width())))
        if self.mirror:
            frac = 1.0 - frac
        return frac * self.span_hz

    # --- drawing -------------------------------------------------------------------------------

    def _color(self, name: str, fallback: str) -> Gdk.RGBA:
        ctx = self.get_style_context()
        found, rgba = ctx.lookup_color(name)
        if found:
            return rgba
        c = Gdk.RGBA()
        c.parse(fallback)
        return c

    def do_snapshot(self, snap: Gtk.Snapshot) -> None:
        w, h = self.get_width(), self.get_height()
        if w <= 0 or h <= 0:
            return
        trace_h = h * TRACE_FRACTION
        fg = self.get_color()
        if self._texture is not None:
            rect = Graphene.Rect().init(0, trace_h, w, h - trace_h)
            snap.append_scaled_texture(self._texture, Gsk.ScalingFilter.LINEAR, rect)

        # Spectrum trace across the top band.
        if self._trace is not None and len(self._trace) > 1:
            trace = self._trace[::-1] if self.mirror else self._trace
            n = len(trace)
            builder = Gsk.PathBuilder.new()
            builder.move_to(0, trace_h)
            for i in range(0, n, max(1, n // 400)):
                x = i / (n - 1) * w
                y = trace_h - 2 - float(np.clip(trace[i], 0, 1)) * (trace_h - 6)
                builder.line_to(x, y)
            builder.line_to(w, trace_h)
            builder.close()
            path = builder.to_path()
            fill = Gdk.RGBA()
            fill.red, fill.green, fill.blue, fill.alpha = fg.red, fg.green, fg.blue, 0.07
            snap.append_fill(path, Gsk.FillRule.WINDING, fill)
            line = Gdk.RGBA()
            line.red, line.green, line.blue, line.alpha = fg.red, fg.green, fg.blue, 0.7
            snap.append_stroke(path, Gsk.Stroke.new(1.2), line)

        # Separator between trace and waterfall.
        sep = Gdk.RGBA()
        sep.red, sep.green, sep.blue, sep.alpha = fg.red, fg.green, fg.blue, 0.10
        snap.append_color(sep, Graphene.Rect().init(0, trace_h, w, 1))

        # Grid every 500 Hz.
        grid = Gdk.RGBA()
        grid.red, grid.green, grid.blue, grid.alpha = fg.red, fg.green, fg.blue, 0.06
        for hz in range(500, int(self.span_hz), 500):
            x = self._x_for(hz)
            snap.append_color(grid, Graphene.Rect().init(x, 0, 1, h))

        accent = self._color("accent_bg_color", "#3584e4")
        if self.passband is not None:
            lo, hi = sorted(self._x_for(f) for f in self.passband)
            band = Gdk.RGBA()
            band.red, band.green, band.blue, band.alpha = accent.red, accent.green, accent.blue, 0.10
            snap.append_color(band, Graphene.Rect().init(lo, 0, hi - lo, trace_h))

        if self.rx_offset is not None:
            self._marker(snap, self.rx_offset, accent, h, trace_h, solid=True)
        if self.tx_offset is not None:
            self._marker(snap, self.tx_offset, self._color("error_bg_color", "#e01b24"), h, trace_h, solid=False)

        if self.marks:
            self._draw_marks(snap, w, h, trace_h, accent)

        if self._hover_x is not None:
            hover = Gdk.RGBA()
            hover.red, hover.green, hover.blue, hover.alpha = fg.red, fg.green, fg.blue, 0.35
            snap.append_color(hover, Graphene.Rect().init(self._hover_x, 0, 1, h))

    def _draw_marks(self, snap, w, h, trace_h, accent) -> None:
        import time as _time

        now = _time.time()
        scale = (h - trace_h) / HISTORY_ROWS * self.rows_per_second   # pixels per second of age
        layout = self.create_pango_layout("")
        for t0, t1, lo, hi, kind in self.marks:
            y0 = trace_h + (now - t1) * scale
            y1 = trace_h + (now - t0) * scale
            if y0 >= h:
                continue
            y1 = min(y1, h - 1)
            xa, xb = sorted((self._x_for(lo), self._x_for(hi)))
            pad = 4 if kind == "cw" else 2
            rect = Graphene.Rect().init(xa - pad, y0, xb - xa + 2 * pad, max(4.0, y1 - y0))
            outline = Gsk.RoundedRect()   # kept referenced; see ui/smartscan.py _rounded
            outline.init_from_rect(rect, 6)
            color = Gdk.RGBA()
            color.red, color.green, color.blue, color.alpha = accent.red, accent.green, accent.blue, 0.9
            fill = Gdk.RGBA()
            fill.red, fill.green, fill.blue, fill.alpha = accent.red, accent.green, accent.blue, 0.10
            snap.push_rounded_clip(outline)
            snap.append_color(fill, rect)
            snap.pop()
            snap.append_border(outline, [1.5] * 4, [color] * 4)
            layout.set_text("CW" if kind == "cw" else "Voice", -1)
            tw, th = layout.get_pixel_size()
            if rect.get_height() > th + 4:
                snap.save()
                point = Graphene.Point()
                point.x, point.y = max(2.0, min(w - tw - 2, rect.get_x() + 4)), y0 + 2
                snap.translate(point)
                snap.append_layout(layout, color)
                snap.restore()

    def _marker(self, snap, hz, color, h, trace_h, solid) -> None:
        x0 = self._x_for(hz)
        x1 = self._x_for(hz + self.marker_width_hz)
        lo, hi = min(x0, x1), max(x0, x1)
        bracket = Gdk.RGBA()
        bracket.red, bracket.green, bracket.blue, bracket.alpha = color.red, color.green, color.blue, 0.9 if solid else 0.8
        # Bracket over the trace area, showing the signal's width.
        snap.append_color(bracket, Graphene.Rect().init(lo, 2, max(2.0, hi - lo), 3))
        snap.append_color(bracket, Graphene.Rect().init(lo, 2, 2, trace_h - 2))
        snap.append_color(bracket, Graphene.Rect().init(hi - 2, 2, 2, trace_h - 2))
        if not solid:
            dash = 6
            y = trace_h
            while y < h:
                snap.append_color(bracket, Graphene.Rect().init(lo, y, 1.5, dash))
                y += dash * 2

    # --- input ----------------------------------------------------------------------------------

    def _set_hover(self, x) -> None:
        self._hover_x = x
        self.queue_draw()

    def _on_click(self, gesture, n_press, x, y) -> None:
        state = gesture.get_current_event_state()
        shift = bool(state & Gdk.ModifierType.SHIFT_MASK)
        self.emit("offset-clicked", self._hz_for(x), shift)

    def _on_tooltip(self, widget, x, y, keyboard, tooltip) -> bool:
        if keyboard:
            return False
        hz = self._hz_for(x)
        text = self.describe_offset(hz) if hasattr(self, "describe_offset") and self.describe_offset else f"{hz:.0f} Hz"
        tooltip.set_text(text)
        return True

    describe_offset = None


class FrequencyAxis(Gtk.Widget):
    """Labels under the waterfall (never drawn over the image)."""

    __gtype_name__ = "KX3FrequencyAxis"

    def __init__(self, waterfall: Waterfall):
        super().__init__()
        self.waterfall = waterfall
        self.labeler = lambda hz: f"{hz:.0f}"
        self.step_hz = 500
        self.set_size_request(-1, 18)
        self.add_css_class("axis-label")
        self.add_css_class("numeric")
        self.add_css_class("dim-label")

    def refresh(self) -> None:
        self.queue_draw()

    def do_snapshot(self, snap: Gtk.Snapshot) -> None:
        w = self.get_width()
        if w <= 0:
            return
        layout = self.create_pango_layout("")
        color = self.get_color()
        last_right = -1e9
        for hz in range(0, int(self.waterfall.span_hz) + 1, self.step_hz):
            text = self.labeler(hz)
            layout.set_text(text, -1)
            tw, th = layout.get_pixel_size()
            x = self.waterfall._x_for(hz) - tw / 2
            x = max(0, min(w - tw, x))
            if x < last_right + 8:
                continue
            snap.save()
            point = Graphene.Point()
            point.x, point.y = x, 1
            snap.translate(point)
            snap.append_layout(layout, color)
            snap.restore()
            last_right = x + tw
