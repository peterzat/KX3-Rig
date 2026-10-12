"""The WSPR view: the loop's report card.

Left: setup strip (band, cycle), a map of who is heard, by direction and
distance from this station, and the list of spots. Right: the beacon (on for a
set time, how often, at what power) and sharing spots on wsprnet.org.
"""

from __future__ import annotations

import math
import time
from datetime import datetime, timezone

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, GLib, Graphene, Gsk, Gtk, Pango  # noqa: E402

from .. import bandplan  # noqa: E402
from ..cat import DataSubmode, Mode  # noqa: E402
from ..ft8 import grid as grids  # noqa: E402
from ..radio import Link  # noqa: E402
from ..wspr import protocol as wspr  # noqa: E402
from ..wspr.engine import BEACON_MINUTES, Heard, WsprEngine, wsprd_available  # noqa: E402

MAX_ROWS = 300
MAP_KM = 20_000          # the outer ring: the far side of the world


def _label(text: str = "", *classes: str, **kw) -> Gtk.Label:
    lbl = Gtk.Label(label=text, **kw)
    for c in classes:
        lbl.add_css_class(c)
    return lbl


def map_position(km: float, bearing: float, radius: float) -> tuple[float, float]:
    """Azimuthal position (x right, y down) for a distance and bearing: a square-root
    radius keeps nearby stations from piling up in the middle."""
    r = radius * math.sqrt(min(km, MAP_KM) / MAP_KM)
    a = math.radians(bearing)
    return r * math.sin(a), -r * math.cos(a)


class SpotMap(Gtk.Widget):
    """Who is heard, by direction and distance: a compass with rings at 1,000,
    5,000, and 10,000 km. Recent spots are brighter."""

    __gtype_name__ = "KX3SpotMap"

    def __init__(self):
        super().__init__()
        self.heard: list[Heard] = []
        self.set_size_request(240, 240)
        self.set_hexpand(True)
        self.set_vexpand(True)

    def set_heard(self, heard: list[Heard]) -> None:
        self.heard = heard
        self.queue_draw()

    def _color(self, name: str, fallback: str) -> Gdk.RGBA:
        found, rgba = self.get_style_context().lookup_color(name)
        if found:
            return rgba
        c = Gdk.RGBA()
        c.parse(fallback)
        return c

    def do_snapshot(self, snap: Gtk.Snapshot) -> None:
        w, h = self.get_width(), self.get_height()
        if w <= 0 or h <= 0:
            return
        fg = self.get_color()
        accent = self._color("accent_bg_color", "#3584e4")
        cx, cy = w / 2, h / 2
        radius = min(w, h) / 2 - 22
        layout = self.create_pango_layout("")

        def rgba(c: Gdk.RGBA, alpha: float) -> Gdk.RGBA:
            out = Gdk.RGBA()
            out.red, out.green, out.blue, out.alpha = c.red, c.green, c.blue, alpha
            return out

        def text_at(x: float, y: float, text: str, color: Gdk.RGBA, small: bool = True) -> None:
            layout.set_markup(f"<small>{GLib.markup_escape_text(text)}</small>" if small else text, -1)
            tw, th = layout.get_pixel_size()
            snap.save()
            point = Graphene.Point()
            point.x, point.y = x - tw / 2, y - th / 2
            snap.translate(point)
            snap.append_layout(layout, color)
            snap.restore()

        for km in (1_000, 5_000, 10_000, MAP_KM):
            r = radius * math.sqrt(km / MAP_KM)
            builder = Gsk.PathBuilder.new()
            builder.add_circle(Graphene.Point().init(cx, cy), r)
            snap.append_stroke(builder.to_path(), Gsk.Stroke.new(1.0), rgba(fg, 0.12 if km != MAP_KM else 0.22))
            if km != MAP_KM:
                text_at(cx + r * 0.71 + 6, cy - r * 0.71 - 6, f"{km // 1000}k km", rgba(fg, 0.45))
        for bearing, name in ((0, "N"), (90, "E"), (180, "S"), (270, "W")):
            x, y = map_position(MAP_KM, bearing, radius + 12)
            text_at(cx + x, cy + y, name, rgba(fg, 0.6))
            builder = Gsk.PathBuilder.new()
            builder.move_to(cx, cy)
            ex, ey = map_position(MAP_KM, bearing, radius)
            builder.line_to(cx + ex, cy + ey)
            snap.append_stroke(builder.to_path(), Gsk.Stroke.new(1.0), rgba(fg, 0.06))
        # Home.
        builder = Gsk.PathBuilder.new()
        builder.add_circle(Graphene.Point().init(cx, cy), 3.5)
        snap.append_fill(builder.to_path(), Gsk.FillRule.WINDING, rgba(fg, 0.8))

        now = time.time()
        latest: dict[str, Heard] = {}
        for item in self.heard:
            if item.km is not None and item.bearing is not None:
                latest[item.spot.call or item.spot.message] = item
        for item in latest.values():
            age = now - item.time
            alpha = 0.95 if age < 600 else 0.6 if age < 3600 else 0.3
            x, y = map_position(item.km, item.bearing, radius)
            # Stronger spots are bigger: -30 dB small, -5 dB large.
            size = 3.0 + max(0.0, min(5.0, (item.spot.snr + 30) / 5))
            builder = Gsk.PathBuilder.new()
            builder.add_circle(Graphene.Point().init(cx + x, cy + y), size)
            snap.append_fill(builder.to_path(), Gsk.FillRule.WINDING, rgba(accent, alpha))
            if age < 3600:
                text_at(cx + x, cy + y - size - 7, item.spot.call, rgba(fg, alpha))


class WsprPage(Gtk.Box):
    __gtype_name__ = "KX3WsprPage"

    def __init__(self, station, engine: WsprEngine, toast, confirm_tx):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.station = station
        self.engine = engine
        self.toast = toast
        self.confirm_tx = confirm_tx
        self._rows = 0
        self.split = Adw.OverlaySplitView(sidebar_position=Gtk.PackType.END, max_sidebar_width=380,
                                          min_sidebar_width=300, sidebar_width_fraction=0.34)
        self.split.set_content(self._build_main())
        self.split.set_sidebar(self._build_panel())
        self.split.set_vexpand(True)
        self.append(self.split)

        engine.connect("spots", lambda e, slot, heard: self._on_spots(slot, heard))
        engine.connect("changed", lambda e: self._refresh())
        engine.connect("transmitting", lambda e, on: self._refresh())
        engine.connect("event", lambda e, kind, msg: self.toast(msg))
        station.connect("radio-changed", lambda s, st: self._refresh())
        station.connect("audio-changed", lambda s, a: self._refresh())
        GLib.timeout_add(500, self._tick)
        self._refresh()

    # --- construction ------------------------------------------------------------------

    def _build_main(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin_top=12, margin_bottom=12,
                      margin_start=12, margin_end=12)
        strip = Gtk.Box(spacing=12)
        self.bands = [b for b in bandplan.BANDS if b.name in wspr.DIALS]
        self.band_dd = Gtk.DropDown.new_from_strings([f"{b.label}  ·  {wspr.DIALS[b.name] / 1e6:.4f} MHz"
                                                      for b in self.bands])
        self.band_dd.set_tooltip_text("Band")
        self.band_dd.set_selected(next(i for i, b in enumerate(self.bands) if b.name == "20m"))
        strip.append(self.band_dd)
        self.tune_button = Gtk.Button(label="Tune Radio to WSPR")
        self.tune_button.add_css_class("suggested-action")
        self.tune_button.add_css_class("pill")
        self.tune_button.connect("clicked", lambda b: self._tune())
        strip.append(self.tune_button)
        self.status = _label("", "dim-label", xalign=0, hexpand=True, ellipsize=Pango.EllipsizeMode.END)
        strip.append(self.status)
        clock = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, valign=Gtk.Align.CENTER)
        self.clock = _label("--:--:--", "heading", "numeric", xalign=1)
        self.cycle = Gtk.ProgressBar(valign=Gtk.Align.CENTER)
        self.cycle.add_css_class("cycle")
        self.cycle.set_size_request(120, -1)
        clock.append(self.clock)
        clock.append(self.cycle)
        strip.append(clock)
        self.panel_toggle = Gtk.ToggleButton(icon_name="sidebar-show-right-symbolic", valign=Gtk.Align.CENTER,
                                             tooltip_text="Show Beacon Panel", visible=False)
        self.panel_toggle.add_css_class("flat")
        from gi.repository import GObject
        self.split.bind_property("show-sidebar", self.panel_toggle, "active",
                                 GObject.BindingFlags.BIDIRECTIONAL | GObject.BindingFlags.SYNC_CREATE)
        strip.append(self.panel_toggle)
        box.append(strip)

        if not wsprd_available() and not self.engine.demo:
            banner = Adw.Banner(title="WSJT-X's wsprd isn't installed, so WSPR can't be decoded.", revealed=True)
            box.append(banner)

        body = Gtk.Box(spacing=12, vexpand=True)
        map_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        map_card.add_css_class("card")
        map_card.set_size_request(320, -1)
        self.summary = _label("Listening…", "heading", xalign=0, wrap=True, margin_top=12, margin_start=12,
                              margin_end=12)
        self.summary_sub = _label("Stations appear every two minutes", "caption", "dim-label", xalign=0,
                                  wrap=True, margin_start=12, margin_end=12)
        map_card.append(self.summary)
        map_card.append(self.summary_sub)
        self.map = SpotMap()
        self.map.set_margin_start(6)
        self.map.set_margin_end(6)
        self.map.set_margin_bottom(6)
        map_card.append(self.map)
        body.append(map_card)

        list_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, hexpand=True)
        header = Gtk.Box(spacing=12, margin_start=12, margin_end=12)
        for text, width, expand in (("UTC", 5, False), ("dB", 3, False), ("Call", 8, False), ("Grid", 4, False),
                                    ("Distance", 10, True)):
            header.append(_label(text, "caption-heading", "dim-label", xalign=0, width_chars=width, hexpand=expand))
        list_box.append(header)
        self.list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.list.add_css_class("decode-list")
        empty = Adw.StatusPage(icon_name="kx3rig-beacon-symbolic", title="Listening…",
                               description="Decodes appear after each two-minute cycle")
        empty.add_css_class("compact")
        self.empty = empty
        self.list.set_placeholder(empty)
        self.scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        self.scroller.set_child(self.list)
        card = Gtk.Frame()
        card.add_css_class("view")
        card.set_child(self.scroller)
        card.set_vexpand(True)
        list_box.append(card)
        body.append(list_box)
        box.append(body)
        return box

    def _build_panel(self) -> Gtk.Widget:
        scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18, margin_top=18, margin_bottom=18,
                        margin_start=18, margin_end=18)
        scroller.set_child(panel)
        panel.append(_label("Beacon", "title-3", xalign=0))
        panel.append(_label("Send a short WSPR signal now and then, and see who hears you on wsprnet.org. "
                            "It shows how well the loop is getting out.", "dim-label", xalign=0, wrap=True))
        group = Adw.PreferencesGroup()
        self.length_row = Adw.ComboRow(title="Run For", model=Gtk.StringList.new(
            [f"{m} minutes" if m < 60 else f"{m // 60} hour{'s' if m > 60 else ''}" for m in BEACON_MINUTES]))
        self.length_row.set_selected(1)
        group.add(self.length_row)
        self.pct_values = (10, 20, 33)
        self.pct_row = Adw.ComboRow(title="Transmit", subtitle="Share of two-minute periods",
                                    model=Gtk.StringList.new(["1 in 10", "1 in 5", "1 in 3"]))
        self.pct_row.set_selected(1)
        self.pct_row.connect("notify::selected", lambda r, p: self.engine.set_percent(
            self.pct_values[r.get_selected()]))
        group.add(self.pct_row)
        self.power_row = Adw.ActionRow(title="Power", subtitle="The KX3's power setting, sent in the message")
        self.power_value = _label("", "numeric", "dim-label")
        self.power_row.add_suffix(self.power_value)
        group.add(self.power_row)
        panel.append(group)
        self.beacon_button = Gtk.Button(label="Start Beacon", halign=Gtk.Align.START)
        self.beacon_button.add_css_class("pill")
        self.beacon_button.add_css_class("suggested-action")
        self.beacon_button.connect("clicked", lambda b: self._toggle_beacon())
        panel.append(self.beacon_button)
        self.beacon_status = _label("", "heading", xalign=0, wrap=True)
        panel.append(self.beacon_status)
        self.tx_block = _label("", "caption", "warning", xalign=0, wrap=True, visible=False)
        panel.append(self.tx_block)

        share = Adw.PreferencesGroup(title="Sharing")
        self.share_row = Adw.SwitchRow(title="Share Spots on WSPRnet",
                                       subtitle="Sends your callsign, 4-character grid, and the stations you hear "
                                                "to wsprnet.org, so others can see the band too")
        self.share_row.set_active(self.station.settings.wspr_upload)
        self.share_row.connect("notify::active", lambda r, p: setattr(self.station.settings, "wspr_upload",
                                                                      r.get_active()))
        share.add(self.share_row)
        panel.append(share)
        return scroller

    # --- actions --------------------------------------------------------------------------

    def _tune(self) -> None:
        if self.engine.busy:
            self.toast("Stop the beacon before changing band")
            return
        other = self.station.auto_keying(exclude=self.engine)
        if other:
            self.toast(other)
            return
        band = self.bands[self.band_dd.get_selected()]
        self.station.go_dial(wspr.DIALS[band.name])

    def _toggle_beacon(self) -> None:
        if self.engine.busy:
            self.engine.stop_beacon()
            return
        minutes = BEACON_MINUTES[self.length_row.get_selected()]
        pct = self.pct_values[self.pct_row.get_selected()]

        def go():
            check = self.engine.start_beacon(minutes, pct)
            if not check.allowed:
                self.toast(check.reason)
        self.confirm_tx(go)

    # --- updates ----------------------------------------------------------------------------

    def _on_spots(self, slot: int, heard: list[Heard]) -> None:
        when = datetime.fromtimestamp(slot * wspr.PERIOD, timezone.utc).strftime("%H:%M")
        for h in sorted(heard, key=lambda x: -(x.km or 0)):
            row = Gtk.ListBoxRow(activatable=False)
            box = Gtk.Box(spacing=12, margin_top=6, margin_bottom=6, margin_start=12, margin_end=12)
            box.append(_label(when, "numeric", "dim-label", width_chars=5, xalign=0))
            box.append(_label(f"{h.spot.snr:+d}", "numeric", width_chars=3, xalign=0))
            box.append(_label(h.spot.call or h.spot.message, "monospace", width_chars=8, xalign=0))
            box.append(_label(h.spot.grid, "monospace", "dim-label", width_chars=4, xalign=0))
            where = f"{h.km:,.0f} km {grids.compass(h.bearing)}" if h.km is not None else ""
            box.append(_label(where, "numeric", "dim-label", xalign=0, hexpand=True))
            row.set_child(box)
            self.list.prepend(row)
            self._rows += 1
        while self._rows > MAX_ROWS:
            last = self.list.get_row_at_index(self._rows - 1)
            if last is None:
                break
            self.list.remove(last)
            self._rows -= 1
        self.map.set_heard(self.engine.heard)
        self._refresh_summary()

    def _refresh_summary(self) -> None:
        n, far = self.engine.summary(1.0)
        if not n:
            self.summary.set_label("Listening…")
            self.summary_sub.set_label("Stations appear every two minutes")
            return
        self.summary.set_label(f"{n} station{'s' if n != 1 else ''} heard in the last hour")
        if far is not None:
            self.summary_sub.set_label(f"Farthest: {far.spot.call or far.spot.message}, "
                                       f"{far.km:,.0f} km {grids.compass(far.bearing)}")

    def _refresh(self) -> None:
        st = self.station.radio
        connected = st.link is Link.CONNECTED
        band = self.engine.band
        data_a = st.mode is Mode.DATA and st.data_submode is DataSubmode.DATA_A
        self.tune_button.set_visible(connected and (band is None or not data_a))
        self.band_dd.set_sensitive(connected and not self.engine.busy)
        if band is not None:
            idx = next((i for i, b in enumerate(self.bands) if b.name == band.name), None)
            if idx is not None and idx != self.band_dd.get_selected():
                self.band_dd.set_selected(idx)
        if not connected:
            self.status.set_label("The radio isn't connected")
        elif not self.station.audio.rx:
            self.status.set_label("Waiting for radio audio")
        elif band is None:
            self.status.set_label("Not on a WSPR frequency")
        else:
            self.status.set_label(f"Listening on {band.label}")
        dbm = self.engine.dbm()
        self.power_value.set_label(f"{st.power_set:g} W  ·  {dbm} dBm" if dbm is not None else "–")
        busy = self.engine.busy
        self.beacon_button.set_label("Stop Beacon" if busy else "Start Beacon")
        for cls in ("suggested-action", "destructive-action"):
            self.beacon_button.remove_css_class(cls)
        self.beacon_button.add_css_class("destructive-action" if busy else "suggested-action")
        check = self.engine.check_tx()
        self.beacon_button.set_sensitive(busy or check.allowed)
        self.tx_block.set_visible(not busy and not check.allowed and connected)
        self.tx_block.set_label(check.reason)
        self.length_row.set_sensitive(not busy)
        self._tick()

    def _tick(self) -> bool:
        now = time.time()
        slot = wspr.slot_of(now)
        t_in = now - slot * wspr.PERIOD
        self.clock.set_label(datetime.fromtimestamp(now, timezone.utc).strftime("%H:%M:%S UTC"))
        self.cycle.set_fraction(t_in / wspr.PERIOD)
        if self.engine.transmitting:
            self.cycle.add_css_class("tx")
        else:
            self.cycle.remove_css_class("tx")
        if self.engine.transmitting:
            self.beacon_status.set_label(f"Transmitting · {max(0, wspr.TX_START_S + wspr.DURATION_S - t_in):.0f} s left")
        elif self.engine.beacon_on:
            nxt = self.engine.next_tx_slot(now)
            left = max(0.0, self.engine.beacon_until - now)
            ends = f"Ends in {int(left // 60)} min"
            if nxt is None:
                self.beacon_status.set_label(f"Beacon on · no more transmissions before it ends · {ends}")
            else:
                wait = nxt * wspr.PERIOD + wspr.TX_START_S - now
                self.beacon_status.set_label(f"Next transmission in {int(wait // 60)}:{int(wait % 60):02d}"
                                             f" · {self.engine.tx_count} sent · {ends}")
        else:
            self.beacon_status.set_label("")
        return GLib.SOURCE_CONTINUE

    def halt(self) -> None:
        self.engine.stop_beacon()
