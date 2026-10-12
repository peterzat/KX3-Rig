"""Smartscan in the Radio view: the toggle, the band view, and what was heard.

Layout: the toggle sits in a Scan row under Band and Mode. While it runs:

* above the waterfall, the outlook: one sentence on where the bands are open,
  one line of context (the band buttons gain a colored dot each)
* the waterfall outlines what was found as it scrolls past
* below it, the band view: the whole sweep left to right, how well the antenna hears
  each part (a faint curve), calling frequencies (ticks), where the
  receiver is now (a highlight), and the stations heard (marks, brighter
  when recent). Click a mark to listen.
* the heard list: newest first, each with a replay button and Tune.
"""

from __future__ import annotations

import time

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, GLib, Graphene, Gsk, Gtk  # noqa: E402

from .. import cat  # noqa: E402
from ..smartscan import conditions  # noqa: E402
from ..smartscan.heard import FORGET_S  # noqa: E402

NOISE_RANGE_DB = 18.0


def _label(text: str, *classes: str, **kw) -> Gtk.Label:
    lbl = Gtk.Label(label=text, **kw)
    for c in classes:
        lbl.add_css_class(c)
    return lbl


def _rgba(base: Gdk.RGBA, alpha: float) -> Gdk.RGBA:
    c = Gdk.RGBA()
    c.red, c.green, c.blue, c.alpha = base.red, base.green, base.blue, alpha
    return c


def _rounded(rect: Graphene.Rect, radius: float) -> Gsk.RoundedRect:
    # Keep the struct referenced: init_from_rect on a temporary returns a copy
    # of memory that PyGObject may already have freed (the clip came out empty).
    rr = Gsk.RoundedRect()
    rr.init_from_rect(rect, radius)
    return rr


def frequency_text(hz: int, kind: str) -> str:
    if kind == "cw":
        return f"{hz / 1e6:.4f} MHz"
    return f"{hz / 1e6:.3f} MHz" if hz % 1000 == 0 else f"{hz / 1e6:.4f} MHz"


def heard_subtitle(entry, now: float) -> str:
    parts = ["CW" if entry.kind == "cw" else "Voice"]
    if entry.spot:
        parts.append("SSTV pictures" if entry.is_sstv else entry.spot)
    parts.append(cat.smeter_label(entry.smeter_db))
    parts.append(entry.age_text(now))
    if entry.times > 1:
        parts.append(f"heard {entry.times} times")
    return " · ".join(parts)


class BandScope(Gtk.Widget):
    """The sweep at a glance (see the module docstring)."""

    __gtype_name__ = "KX3BandScope"

    def __init__(self, scan):
        super().__init__()
        self.scan = scan
        self.add_css_class("card")
        self.add_css_class("band-scope")
        self.set_overflow(Gtk.Overflow.HIDDEN)
        self.set_size_request(300, 64)
        self.set_hexpand(True)
        self.set_has_tooltip(True)
        self.connect("query-tooltip", self._on_tooltip)
        click = Gtk.GestureClick()
        click.connect("released", self._on_click)
        self.add_controller(click)
        motion = Gtk.EventControllerMotion()
        motion.connect("motion", lambda c, x, y: self.set_cursor_from_name("pointer" if self._entry_at(x) else None))
        self.add_controller(motion)

    def _span(self) -> tuple[int, int] | None:
        plan = self.scan.plan
        return (plan.low, plan.high) if plan else None

    def x_for(self, hz: float) -> float:
        lo, hi = self._span()
        return (hz - lo) / max(1, hi - lo) * self.get_width()

    def hz_for(self, x: float) -> float:
        lo, hi = self._span()
        return lo + x / max(1, self.get_width()) * (hi - lo)

    def _color(self, name: str, fallback: str) -> Gdk.RGBA:
        found, rgba = self.get_style_context().lookup_color(name)
        if found:
            return rgba
        c = Gdk.RGBA()
        c.parse(fallback)
        return c

    def do_snapshot(self, snap: Gtk.Snapshot) -> None:
        w, h = self.get_width(), self.get_height()
        plan = self.scan.plan
        if w <= 0 or h <= 0 or plan is None:
            return
        fg = self.get_color()
        accent = self._color("accent_bg_color", "#3584e4")

        # How well the antenna hears each step: the noise floor, relative to the best.
        noise = sorted((d, v) for d, v in self.scan.noise.items() if d in plan.steps or d in plan.hot_steps)
        if len(noise) >= 2:
            top = max(v for _, v in noise)
            builder = Gsk.PathBuilder.new()
            pts = [(self.x_for(sum(plan.audio_window(d)) / 2), v) for d, v in noise]
            builder.move_to(pts[0][0], h)
            for x, v in pts:
                frac = max(0.0, min(1.0, 1 - (top - v) / NOISE_RANGE_DB))
                builder.line_to(x, h - 4 - frac * (h - 14))
            builder.line_to(pts[-1][0], h)
            builder.close()
            path = builder.to_path()
            snap.append_fill(path, Gsk.FillRule.WINDING, _rgba(fg, 0.06))
            snap.append_stroke(path, Gsk.Stroke.new(1.0), _rgba(fg, 0.22))

        # Gaps between ranges (none on most bands) are shaded out.
        for (_, a), (b, _) in zip(plan.ranges, plan.ranges[1:]):
            snap.append_color(_rgba(fg, 0.05), Graphene.Rect().init(self.x_for(a), 0, self.x_for(b) - self.x_for(a), h))

        # Calling frequencies.
        for spot in plan.spots:
            if plan.low <= spot.hz <= plan.high and spot.kind != "sstv":
                x = self.x_for(spot.hz)
                snap.append_color(_rgba(fg, 0.35), Graphene.Rect().init(x - 0.5, 0, 1, 6))

        # Where the receiver is listening now.
        if self.scan.active and self.scan.position:
            a, b = plan.audio_window(self.scan.position)
            x0, x1 = self.x_for(a), self.x_for(b)
            snap.append_color(_rgba(accent, 0.16), Graphene.Rect().init(x0, 0, max(2.0, x1 - x0), h))

        # Steady carriers from the last sweep: faint ticks along the bottom.
        for spans in self.scan.carriers.values():
            for lo, hi in spans:
                snap.append_color(_rgba(fg, 0.25), Graphene.Rect().init(self.x_for((lo + hi) / 2) - 0.5, h - 6, 1, 6))

        # Stations heard, brighter when recent.
        now = time.time()
        for e in self.scan.heard.entries:
            age = max(0.0, min(1.0, (now - e.last_seen) / FORGET_S))
            alpha = (0.35 if e.is_sstv else 1.0) * (1.0 - 0.65 * age)
            strength = max(0.25, min(1.0, (e.snr_db - 3) / 20))
            bar_h = 12 + strength * (h - 24)
            width = 3.0 if e.kind == "cw" else 5.0
            x = self.x_for(e.tune_hz) - width / 2
            rect = Graphene.Rect().init(x, (h - bar_h) / 2, width, bar_h)
            snap.push_rounded_clip(_rounded(rect, width / 2))
            snap.append_color(_rgba(accent, alpha), rect)
            snap.pop()

    def _entry_at(self, x: float):
        if self.scan.plan is None:
            return None
        best, best_d = None, 9.0
        for e in self.scan.heard.entries:
            d = abs(self.x_for(e.tune_hz) - x)
            if d < best_d:
                best, best_d = e, d
        return best

    def _on_click(self, gesture, n_press, x, y) -> None:
        entry = self._entry_at(x)
        if entry is not None:
            self.scan.tune(entry.id)

    def _on_tooltip(self, widget, x, y, keyboard, tooltip) -> bool:
        if keyboard or self.scan.plan is None:
            return False
        entry = self._entry_at(x)
        if entry is not None:
            tooltip.set_text(f"{frequency_text(entry.tune_hz, entry.kind)} · {heard_subtitle(entry, time.time())}\n"
                             "Click to listen")
            return True
        hz = self.hz_for(x)
        text = f"{hz / 1e6:.3f} MHz"
        plan = self.scan.plan
        nearest = min(self.scan.noise.items(), key=lambda kv: abs(sum(plan.audio_window(kv[0])) / 2 - hz),
                      default=None)
        if nearest is not None and self.scan.noise:
            drop = max(self.scan.noise.values()) - nearest[1]
            text += f"\nBand noise {drop:.0f} dB below the loudest part of the sweep"
            if drop > 6:
                text += " (the antenna hears less here)"
        tooltip.set_text(text)
        return True


class HeardRow(Gtk.ListBoxRow):
    def __init__(self, panel, entry):
        super().__init__(activatable=True)
        self.entry_id = entry.id
        self.panel = panel
        self.row = Adw.ActionRow(activatable=False)
        self.row.add_css_class("heard-row")
        self.play = Gtk.Button(icon_name="media-playback-start-symbolic", valign=Gtk.Align.CENTER,
                               tooltip_text="Replay What Was Heard")
        self.play.add_css_class("flat")
        self.play.add_css_class("circular")
        self.play.connect("clicked", lambda b: panel.play(self.entry_id))
        self.row.add_prefix(self.play)
        tune = Gtk.Button(label="Tune", valign=Gtk.Align.CENTER, tooltip_text="Stop Smartscan and Listen Here")
        tune.add_css_class("flat")
        tune.connect("clicked", lambda b: panel.scan.tune(self.entry_id))
        self.row.add_suffix(tune)
        self.set_child(self.row)
        self.refresh(entry, time.time())

    def refresh(self, entry, now: float) -> None:
        self.row.set_title(frequency_text(entry.tune_hz, entry.kind))
        self.row.set_subtitle(heard_subtitle(entry, now))
        self.play.set_sensitive(entry.clip is not None)
        playing = self.panel.playing_id == self.entry_id
        self.play.set_icon_name("media-playback-stop-symbolic" if playing else "media-playback-start-symbolic")
        if entry.is_sstv:
            self.add_css_class("dim-label")
        else:
            self.remove_css_class("dim-label")


class SmartscanPanel:
    """Builds the header (toggle and status), the outlook, and the body (band
    view and heard list); the Radio view places them."""

    def __init__(self, scan, toast):
        self.scan = scan
        self.toast = toast
        self.playing_id: int | None = None
        self._syncing = False

        # --- header -------------------------------------------------------------------------
        self.header = Gtk.Box(spacing=12, valign=Gtk.Align.CENTER)
        self.toggle = Gtk.ToggleButton()
        self.toggle.set_child(Adw.ButtonContent(icon_name="system-search-symbolic", label="Smartscan"))
        self.toggle.add_css_class("pill")
        self.toggle.add_css_class("smartscan-toggle")
        self.toggle.set_tooltip_text("Sweep This Band for Stations to Talk To")
        self.toggle.connect("toggled", self._on_toggled)
        self.header.append(self.toggle)
        self.status = _label("Finds stations on this band and shows where the bands are open",
                             "caption", "dim-label", xalign=0, wrap=True, hexpand=True, max_width_chars=60)
        self.header.append(self.status)

        # --- outlook (above the waterfall) -------------------------------------------------------
        self.outlook = Gtk.Revealer(transition_type=Gtk.RevealerTransitionType.SLIDE_DOWN, transition_duration=200)
        outlook = Gtk.Box(spacing=10)
        self.outlook.set_child(outlook)
        self.spinner = Gtk.Spinner(valign=Gtk.Align.START)
        outlook.append(self.spinner)
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, hexpand=True)
        self.headline = _label("", "heading", xalign=0, wrap=True)
        self.context = _label("", "caption", "dim-label", xalign=0, wrap=True)
        text.append(self.headline)
        text.append(self.context)
        outlook.append(text)
        outlook.set_tooltip_text("From PSKReporter reception reports by stations in your grid square over the last "
                                 "15 minutes (mostly FT8), and NOAA's planetary K index. Checked every 5 minutes "
                                 "while Smartscan is on.")

        # --- band view and heard list (below the waterfall) ---------------------------------------
        self.body = Gtk.Revealer(transition_type=Gtk.RevealerTransitionType.SLIDE_DOWN, transition_duration=200)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.body.set_child(box)

        scope_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.scope = BandScope(scan)
        scope_box.append(self.scope)
        ends = Gtk.Box()
        self.scope_low = _label("", "caption", "dim-label", "numeric", xalign=0, hexpand=True)
        self.scope_mid = _label("", "caption", "dim-label")
        self.scope_high = _label("", "caption", "dim-label", "numeric", xalign=1, hexpand=True)
        for w in (self.scope_low, self.scope_mid, self.scope_high):
            ends.append(w)
        scope_box.append(ends)
        box.append(scope_box)

        self.list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.list.add_css_class("boxed-list")
        self.list.set_placeholder(_label("Stations Smartscan hears appear here, with a few seconds of audio "
                                         "to replay.", "dim-label", "caption", wrap=True,
                                         margin_top=14, margin_bottom=14, margin_start=12, margin_end=12))
        self.list.connect("row-activated", lambda lb, row: self.scan.tune(row.entry_id))
        box.append(self.list)
        self._rows: dict[int, HeardRow] = {}

        scan.connect("changed", lambda s: self.refresh())
        scan.connect("heard-changed", lambda s: self._refresh_list())
        scan.connect("conditions-changed", lambda s: self._refresh_outlook())
        scan.connect("event", lambda s, kind, msg: self.toast(msg))
        GLib.timeout_add_seconds(10, self._tick)
        self.refresh()

    # --- actions ----------------------------------------------------------------------------

    def _on_toggled(self, button) -> None:
        if self._syncing:
            return
        if button.get_active():
            reason = self.scan.start()
            if reason:
                self.toast(reason)
                self._syncing = True
                button.set_active(False)
                self._syncing = False
        else:
            self.scan.stop()

    def play(self, entry_id: int) -> None:
        station = self.scan.station
        if self.playing_id == entry_id and station.clip_playing:
            station.stop_clip()
            self.playing_id = None
            self._refresh_list()
            return

        def done():
            self.playing_id = None
            self._refresh_list()
        reason = self.scan.play(entry_id, on_done=done)
        if reason:
            self.toast(reason)
            return
        self.playing_id = entry_id
        self._refresh_list()

    # --- state ------------------------------------------------------------------------------

    def _tick(self) -> bool:
        if self.scan.active or self.scan.heard.entries:
            self._refresh_list()
            self._refresh_outlook()
        return GLib.SOURCE_CONTINUE

    def refresh(self) -> None:
        scan = self.scan
        self._syncing = True
        try:
            self.toggle.set_active(scan.active)
        finally:
            self._syncing = False
        self.body.set_reveal_child(scan.active or bool(scan.heard.entries) and scan.plan is not None)
        self.outlook.set_reveal_child(scan.active)
        if scan.active:
            self.toggle.add_css_class("suggested-action")
            plan = scan.plan
            text = f"Sweeping {plan.label()}"
            est = scan.sweep_estimate_s
            if est:
                text += f" · about {est:.0f} s per sweep"
            self.status.set_label(text)
        else:
            self.toggle.remove_css_class("suggested-action")
            self.status.set_label("Finds stations on this band and shows where the bands are open"
                                  if not scan.heard.entries else "Stopped. Stations heard stay listed for 15 minutes.")
        plan = scan.plan
        if plan is not None:
            self.scope_low.set_label(f"{plan.low / 1e6:.3f}")
            self.scope_high.set_label(f"{plan.high / 1e6:.3f} MHz")
            self.scope_mid.set_label(f"Listening on {scan.position / 1e6:.3f}" if scan.active else "")
        self.scope.queue_draw()

    def _refresh_list(self) -> None:
        now = time.time()
        entries = self.scan.heard.ordered()
        ids = [e.id for e in entries]
        if ids != [r.entry_id for r in self._ordered_rows()]:
            for row in list(self._rows.values()):
                self.list.remove(row)
            self._rows = {}
            for e in entries:
                row = HeardRow(self, e)
                self._rows[e.id] = row
                self.list.append(row)
        else:
            for e in entries:
                self._rows[e.id].refresh(e, now)
        self.scope.queue_draw()
        self.body.set_reveal_child(self.scan.active or bool(entries) and self.scan.plan is not None)

    def _ordered_rows(self) -> list[HeardRow]:
        rows = []
        child = self.list.get_first_child()
        while child is not None:
            if isinstance(child, HeardRow):
                rows.append(child)
            child = child.get_next_sibling()
        return rows

    def _refresh_outlook(self) -> None:
        scan = self.scan
        from .. import bandplan

        current = bandplan.band_for(scan.station.radio.frequency)
        head, context = conditions.summary(scan.outlook, current, scan.grid, scan.kp, scan.sun)
        if scan.conditions_error:
            head = scan.conditions_error
        self.headline.set_label(head)
        self.context.set_label(context)
        self.context.set_visible(bool(context))
        loading = scan.fetching and scan.outlook is None
        self.spinner.set_visible(loading)
        self.spinner.set_spinning(loading)
