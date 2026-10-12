"""The FT8 view (FT8 or FT4): watch the band, answer a CQ, or call CQ.

Left: setup strip (mode, band, clock and cycle), waterfall with the callsigns
heard, and the decode list with distance, filters, and "New" for stations not
in the log.
Right: the contact panel, which reads like a conversation while a contact is
in progress and offers "Call CQ", transmit level, and Tune when idle.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, GLib, Gtk, Pango  # noqa: E402

from .. import bandplan  # noqa: E402
from ..cat import DataSubmode, Mode  # noqa: E402
from ..ft8 import grid as grids  # noqa: E402
from ..ft8.engine import Ft8Engine  # noqa: E402
from ..ft8.filters import DecodeFilter  # noqa: E402
from ..ft8.messages import base_call  # noqa: E402
from ..ft8.protocol import FT4, FT8  # noqa: E402
from ..ft8.sequencer import Decode, Stage  # noqa: E402
from ..radio import Link  # noqa: E402
from .waterfall import FrequencyAxis, Waterfall  # noqa: E402

MAX_ROWS = 400


def _label(text: str = "", *classes: str, **kw) -> Gtk.Label:
    lbl = Gtk.Label(label=text, **kw)
    for c in classes:
        lbl.add_css_class(c)
    return lbl


def _mhz(hz: int) -> str:
    """14.074, 7.0475: at least three decimals, no trailing zeros beyond them."""
    text = f"{hz / 1e6:.4f}"
    return text[:-1] if text.endswith("0") else text


def _utc(t: float) -> str:
    return datetime.fromtimestamp(t, timezone.utc).strftime("%H:%M:%S")


class DecodeRow(Gtk.ListBoxRow):
    def __init__(self, d: Decode, my_call: str, on_answer, where: str = "", new: bool = False, on_hide=None):
        super().__init__()
        self.decode = d
        msg = d.message
        to_me = msg.addressed_to(my_call)
        box = Gtk.Box(spacing=12)
        box.add_css_class("decode-row")
        for text, width in ((f"{d.snr:+d}", 3), (f"{d.dt:+.1f}", 4), (f"{d.freq}", 4)):
            lbl = _label(text, "numeric", "dim-label", xalign=1, width_chars=width)
            box.append(lbl)
        text = _label(d.text, "monospace", "ft8-message", xalign=0, hexpand=True,
                      ellipsize=Pango.EllipsizeMode.END)
        box.append(text)
        if msg.is_cq:
            box.add_css_class("cq")
            box.append(_label(msg.cq_modifier or "CQ", "tag", "cq", "small", "caption-heading",
                              valign=Gtk.Align.CENTER))
        if to_me:
            box.add_css_class("me")
            box.append(_label("You", "tag", "me", "small", "caption-heading", valign=Gtk.Align.CENTER))
        if new:
            box.append(_label("New", "tag", "new", "small", "caption-heading", valign=Gtk.Align.CENTER,
                              tooltip_text="Not in your log on this band"))
        if where:
            box.append(_label(where, "caption", "numeric", "dim-label", valign=Gtk.Align.CENTER))
        if d.low_confidence:
            box.append(_label("?", "dim-label", tooltip_text="Low-confidence decode"))
        self.can_answer = bool(msg.de and msg.de != "<...>" and (msg.is_cq or to_me))
        if self.can_answer:
            btn = Gtk.Button(icon_name="mail-reply-sender-symbolic", valign=Gtk.Align.CENTER)
            btn.add_css_class("flat")
            btn.set_tooltip_text(f"Answer {msg.de}")
            btn.connect("clicked", lambda b: on_answer(d))
            box.append(btn)
        else:
            spacer = Gtk.Box()
            spacer.set_size_request(34, -1)
            box.append(spacer)
        self.set_child(box)
        self.set_activatable(self.can_answer)
        if on_hide is not None and msg.de and msg.de != "<...>":
            call = base_call(msg.de)
            menu = Gtk.GestureClick(button=3)
            menu.connect("pressed", lambda g, n, x, y: self._offer_hide(call, on_hide, x, y))
            self.add_controller(menu)

    def _offer_hide(self, call: str, on_hide, x: float, y: float) -> None:
        pop = Gtk.Popover(has_arrow=True)
        pop.set_parent(self)
        rect = Gdk.Rectangle()
        rect.x, rect.y, rect.width, rect.height = int(x), int(y), 1, 1
        pop.set_pointing_to(rect)
        btn = Gtk.Button(label=f"Hide {call}")
        btn.add_css_class("flat")
        btn.connect("clicked", lambda b: (pop.popdown(), on_hide(call)))
        pop.set_child(btn)
        pop.connect("closed", lambda p: GLib.idle_add(p.unparent))
        pop.popup()


class Bubble(Gtk.Box):
    """One line of the contact conversation: ours on the right, theirs on the left."""

    def __init__(self, text: str, ours: bool, note: str = ""):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=2,
                         halign=Gtk.Align.END if ours else Gtk.Align.START)
        frame = Gtk.Box()
        frame.add_css_class("card")
        frame.add_css_class("bubble-ours" if ours else "bubble-theirs")
        inner = _label(text, "monospace", xalign=0, wrap=True, margin_top=6, margin_bottom=6,
                       margin_start=10, margin_end=10)
        frame.append(inner)
        self.append(frame)
        if note:
            self.append(_label(note, "caption", "dim-label", halign=Gtk.Align.END if ours else Gtk.Align.START))


class Ft8Page(Gtk.Box):
    __gtype_name__ = "KX3Ft8Page"

    def __init__(self, station, engine: Ft8Engine, toast, confirm_tx):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.station = station
        self.engine = engine
        self.toast = toast
        self.confirm_tx = confirm_tx       # callable(action) -> runs action after first-TX confirmation
        self._row_count = 0
        self._conversation_key = None
        self.filter = DecodeFilter()
        self.on_title = None               # set by the window: the view's title follows FT8/FT4

        self.split = Adw.OverlaySplitView(sidebar_position=Gtk.PackType.END, max_sidebar_width=380,
                                          min_sidebar_width=300, sidebar_width_fraction=0.34)
        self.split.set_content(self._build_main())
        self.split.set_sidebar(self._build_panel())
        self._panel_binding = self.split.bind_property("show-sidebar", self.panel_toggle, "active",
                                                       GObject_BIDIRECTIONAL())
        self.split.set_vexpand(True)
        self.append(self.split)

        self.list.set_filter_func(self._filter_row)
        engine.connect("decoded", lambda e, slot, ds: self._on_decoded(slot, ds))
        engine.connect("contact-changed", lambda e: self._refresh_panel())
        engine.connect("transmitting", lambda e, on, text: self._on_transmitting(on, text))
        engine.connect("logged", lambda e, entry: self._on_logged(entry))
        station.connect("radio-changed", lambda s, st: self._refresh_setup())
        station.connect("audio-changed", lambda s, a: self._refresh_setup())
        GLib.timeout_add(200, self._clock_tick)
        self._refresh_setup()
        self._refresh_panel()

    # --- main column ---------------------------------------------------------------------

    def _build_main(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin_top=12, margin_bottom=12,
                      margin_start=12, margin_end=12)

        strip = Gtk.Box(spacing=12)
        modes = Gtk.Box(valign=Gtk.Align.CENTER)
        modes.add_css_class("linked")
        self.mode_buttons = {}
        for proto, tip in ((FT8, "15-second periods: the most activity"),
                           (FT4, "7.5-second periods: faster contacts, popular in contests")):
            b = Gtk.ToggleButton(label=proto.name, tooltip_text=tip)
            if self.mode_buttons:
                b.set_group(next(iter(self.mode_buttons.values())))
            b.set_active(self.engine.proto is proto)
            b.connect("toggled", self._on_mode_toggled, proto.name)
            self.mode_buttons[proto.name] = b
            modes.append(b)
        strip.append(modes)
        self.band_model = Gtk.StringList()
        self.band_dd = Gtk.DropDown(model=self.band_model)
        self.band_dd.set_tooltip_text("Band")
        self._fill_bands()
        self.band_dd.connect("notify::selected", self._on_band_selected)
        strip.append(self.band_dd)
        self.setup_button = Gtk.Button(label="Tune Radio to FT8")
        self.setup_button.add_css_class("suggested-action")
        self.setup_button.add_css_class("pill")
        self.setup_button.connect("clicked", lambda b: self._tune_to_ft8())
        strip.append(self.setup_button)
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
                                             tooltip_text="Show Contact Panel", visible=False)
        self.panel_toggle.add_css_class("flat")
        # Sync from the split view (sidebar shown by default) to the toggle.
        self._panel_binding = None
        strip.append(self.panel_toggle)
        box.append(strip)

        self.clock_warning = Adw.Banner(title="This computer's clock isn't synchronized. "
                                              "FT8 needs the time correct to within a second.")
        self.clock_warning.set_revealed(not _clock_synchronized())
        box.append(self.clock_warning)

        wf_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.waterfall = Waterfall(self.station)
        self.waterfall.set_size_request(-1, 150)
        self.waterfall.set_vexpand(False)
        self.waterfall.marker_width_hz = 50
        self.waterfall.describe_offset = lambda hz: f"{hz:.0f} Hz  ·  click to transmit here"
        self.waterfall.connect("offset-clicked", lambda w, hz, shift: self._set_offset(hz))
        self.waterfall.connect("label-activated", lambda w, d: getattr(d, "message", None) and self._answer(d))
        axis = FrequencyAxis(self.waterfall)
        axis.labeler = lambda hz: f"{hz:.0f}"
        wf_box.append(self.waterfall)
        wf_box.append(axis)
        box.append(wf_box)

        header = Gtk.Box(spacing=12, margin_start=12, margin_end=12)
        for text, width in (("dB", 3), ("DT", 4), ("Hz", 4)):
            header.append(_label(text, "caption-heading", "dim-label", xalign=1, width_chars=width))
        header.append(_label("Message", "caption-heading", "dim-label", xalign=0, hexpand=True))
        self.decode_count = _label("", "caption", "dim-label", xalign=1)
        header.append(self.decode_count)
        header.append(self._build_filter_button())
        box.append(header)

        self.list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE, activate_on_single_click=False)
        self.list.add_css_class("decode-list")
        self.list.connect("row-activated", lambda lb, row: getattr(row, "can_answer", False) and self._answer(row.decode))
        self.empty = Adw.StatusPage(icon_name="network-receive-symbolic", title="Listening…",
                                    description="Decodes appear after each cycle")
        self.empty.add_css_class("compact")
        self.list.set_placeholder(self.empty)
        self.scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        self.scroller.set_child(self.list)

        card = Gtk.Frame()
        card.add_css_class("view")
        card.set_child(self.scroller)
        box.append(card)
        return box

    def _build_filter_button(self) -> Gtk.Widget:
        button = Gtk.MenuButton(label="Filter", valign=Gtk.Align.CENTER, tooltip_text="Choose Which Decodes to Show")
        button.add_css_class("flat")
        button.add_css_class("caption")
        pop = Gtk.Popover()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, margin_top=6, margin_bottom=6,
                      margin_start=6, margin_end=6)
        for attr, title in (("cq_only", "CQs Only"), ("hide_worked", "Hide Stations in the Log"),
                            ("hide_doubtful", "Hide Doubtful Decodes")):
            check = Gtk.CheckButton(label=title, active=getattr(self.filter, attr))
            check.connect("toggled", self._on_filter_toggled, attr)
            box.append(check)
        self.unhide_button = Gtk.Button(label="Show Hidden Stations", sensitive=False, margin_top=6)
        self.unhide_button.add_css_class("flat")
        self.unhide_button.connect("clicked", lambda b: self._unhide())
        box.append(self.unhide_button)
        box.append(_label("Messages to you are always shown. Right-click a decode to hide that station.",
                          "caption", "dim-label", wrap=True, max_width_chars=28, xalign=0, margin_top=6))
        pop.set_child(box)
        button.set_popover(pop)
        self.filter_button = button
        return button

    def _on_filter_toggled(self, check, attr: str) -> None:
        setattr(self.filter, attr, check.get_active())
        self._refilter()

    def _hide_call(self, call: str) -> None:
        self.filter.hidden_calls.add(call)
        self._refilter()
        self.toast(f"{call} hidden for this session")

    def _unhide(self) -> None:
        self.filter.hidden_calls.clear()
        self._refilter()

    def _refilter(self) -> None:
        f = self.filter
        active = f.cq_only or f.hide_worked or bool(f.hidden_calls)
        self.filter_button.set_label("Filter On" if active else "Filter")
        self.unhide_button.set_sensitive(bool(f.hidden_calls))
        n = len(f.hidden_calls)
        self.unhide_button.set_label(f"Show {n} Hidden Station{'s' if n != 1 else ''}" if n else "Show Hidden Stations")
        self.list.invalidate_filter()
        self._update_labels()

    def _filter_row(self, row) -> bool:
        d = getattr(row, "decode", None)
        if d is None:
            return True
        return self.filter.shows(d, self.station.settings.callsign, self.engine.worked, self._band_name())

    def _band_name(self) -> str:
        band = bandplan.band_for(self.station.radio.frequency)
        return band.name if band else ""

    def _where(self, d: Decode) -> str:
        call = d.message.de.strip("<>") if d.message.de else ""
        grid = d.message.grid or self.engine.grids.get(call, "")
        mine = self.station.settings.grid
        if not grid or not mine:
            return ""
        dist = grids.distance_km(mine, grid)
        bearing = grids.bearing_deg(mine, grid)
        if dist is None or bearing is None:
            return ""
        return f"{dist:,.0f} km {grids.compass(bearing)}"

    def _is_new(self, d: Decode) -> bool:
        call = base_call(d.message.de) if d.message.de and d.message.de != "<...>" else ""
        return bool(call) and (d.message.is_cq or d.message.addressed_to(self.station.settings.callsign)) and \
            (call, self._band_name()) not in self.engine.worked

    def _update_labels(self) -> None:
        """Callsigns over the waterfall, where each was heard in the latest periods."""
        p = self.engine.proto
        me = self.station.settings.callsign
        c = self.engine.sequencer.contact
        labels = []
        for slot in sorted(self.engine.decodes)[-1:]:
            t_end = p.slot_start(slot) + p.decode_seconds
            for d in self.engine.decodes[slot]:
                m = d.message
                if not m.de or m.de == "<...>":
                    continue
                if not self.filter.shows(d, me, self.engine.worked, self._band_name()):
                    continue
                if c is not None and base_call(m.de) == base_call(c.call):
                    kind = "partner"
                elif m.addressed_to(me):
                    kind = "me"
                elif m.is_cq:
                    kind = "cq"
                else:
                    kind = ""
                labels.append((t_end - 1.0, d.freq, m.de.strip("<>"), kind, d))
        self.waterfall.set_labels(labels)

    # --- FT8 or FT4 ---------------------------------------------------------------------------

    def _bands(self) -> list[bandplan.Band]:
        return self.engine.proto.bands

    def _fill_bands(self) -> None:
        self._syncing = True
        p = self.engine.proto
        current = self._band_name() or "20m"
        self.band_model.splice(0, self.band_model.get_n_items(),
                               [f"{b.label}  ·  {_mhz(p.dial(b))} MHz" for b in self._bands()])
        names = [b.name for b in self._bands()]
        self.band_dd.set_selected(names.index(current) if current in names else names.index("20m"))
        self._syncing = False

    def _on_mode_toggled(self, button, name: str) -> None:
        if not button.get_active() or self.engine.proto.name == name:
            return
        if not self.engine.set_protocol(name):
            self.toast("Stop the current contact before switching between FT8 and FT4")
            self.mode_buttons[self.engine.proto.name].set_active(True)
            return
        self._fill_bands()
        self.waterfall.marker_width_hz = self.engine.proto.signal_width_hz
        self._clear_list()
        if callable(self.on_title):
            self.on_title(name)
        # Follow onto the new mode's dial when the radio was on the old one.
        if self.station.connected and bandplan.band_for(self.station.radio.frequency):
            self._tune_to_ft8()
        self._refresh_setup()

    # --- contact panel ----------------------------------------------------------------------

    def _build_panel(self) -> Gtk.Widget:
        scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18, margin_top=18, margin_bottom=18,
                        margin_start=18, margin_end=18)
        scroller.set_child(panel)

        # Idle
        self.idle_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.idle_box.append(_label("Make a Contact", "title-3", xalign=0))
        self.idle_hint = _label("Double-click a CQ to answer it, or call CQ and let others find you.",
                                "dim-label", xalign=0, wrap=True)
        self.idle_box.append(self.idle_hint)
        self.cq_button = Gtk.Button(label="Call CQ", halign=Gtk.Align.START)
        self.cq_button.add_css_class("pill")
        self.cq_button.add_css_class("suggested-action")
        self.cq_button.connect("clicked", lambda b: self._call_cq())
        self.idle_box.append(self.cq_button)
        self.tx_block = _label("", "caption", "warning", xalign=0, wrap=True, visible=False)
        self.idle_box.append(self.tx_block)
        panel.append(self.idle_box)

        # Active contact
        self.active_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, visible=False)
        self.contact_call = _label("", "contact-call", xalign=0, selectable=True)
        self.contact_where = _label("", "dim-label", xalign=0)
        self.contact_reports = _label("", "numeric", xalign=0)
        self.active_box.append(self.contact_call)
        self.active_box.append(self.contact_where)
        self.active_box.append(self.contact_reports)
        self.conversation = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.active_box.append(self.conversation)
        self.contact_status = _label("", "heading", xalign=0, wrap=True)
        self.active_box.append(self.contact_status)
        self.halt_button = Gtk.Button(label="Stop", halign=Gtk.Align.START)
        self.halt_button.add_css_class("pill")
        self.halt_button.add_css_class("destructive-action")
        self.halt_button.set_tooltip_text("Stop transmitting and end this contact (Esc)")
        self.halt_button.connect("clicked", lambda b: self.engine.halt())
        self.active_box.append(self.halt_button)
        panel.append(self.active_box)

        # Transmit settings
        tx = Adw.PreferencesGroup(title="Transmit")
        self.offset_row = Adw.ActionRow(title="Audio Offset", subtitle="Click the waterfall to move")
        self.offset_value = _label("", "numeric", "dim-label")
        self.offset_row.add_suffix(self.offset_value)
        tx.add(self.offset_row)
        level_row = Adw.ActionRow(title="Audio Level", subtitle="Aim for 4–5 ALC bars on the KX3")
        self.level = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0.05, 1.0, 0.05)
        self.level.set_value(self.station.settings.data_tx_level)
        self.level.set_size_request(120, -1)
        self.level.set_valign(Gtk.Align.CENTER)
        self.level.connect("value-changed", lambda s: setattr(self.station.settings, "data_tx_level", s.get_value()))
        level_row.add_suffix(self.level)
        tx.add(level_row)
        tune_row = Adw.ActionRow(title="Tune", subtitle="A 10-second tone to check SWR and power")
        self.tune_button = Gtk.Button(label="Tune", valign=Gtk.Align.CENTER)
        self.tune_button.connect("clicked", lambda b: self._tune())
        tune_row.add_suffix(self.tune_button)
        tx.add(tune_row)
        panel.append(tx)

        # Log
        self.log_group = Adw.PreferencesGroup(title="Logged Contacts")
        self.log_group.set_description("Saved to your ADIF log")
        self.log_empty = Adw.ActionRow(title="None yet")
        self.log_empty.add_css_class("dim-label")
        self.log_group.add(self.log_empty)
        self._log_rows: list[Adw.ActionRow] = []
        panel.append(self.log_group)
        return scroller

    # --- actions ---------------------------------------------------------------------------

    def _selected_band(self) -> bandplan.Band:
        return self._bands()[min(self.band_dd.get_selected(), len(self._bands()) - 1)]

    def _on_band_selected(self, dd, _pspec) -> None:
        if getattr(self, "_syncing", False):
            return
        if self.station.connected:
            self._tune_to_ft8()

    def _tune_to_ft8(self) -> None:
        if self.engine.busy:
            self.toast("Stop the current contact before changing band")
            return
        band = self._selected_band()
        self.station.go_dial(self.engine.proto.dial(band))
        self._clear_list()

    def _set_offset(self, hz: float) -> None:
        self.engine.set_tx_offset(hz)
        self._refresh_panel()

    def _answer(self, d: Decode) -> None:
        def go():
            check = self.engine.answer(d)
            if not check.allowed:
                self.toast(check.reason)
        self.confirm_tx(go)

    def _call_cq(self) -> None:
        def go():
            check = self.engine.call_cq()
            if not check.allowed:
                self.toast(check.reason)
        self.confirm_tx(go)

    def _tune(self) -> None:
        if self.engine.tuning:
            self.engine.halt()
            return

        def go():
            check = self.engine.tune()
            if not check.allowed:
                self.toast(check.reason)
        self.confirm_tx(go)

    # --- updates -----------------------------------------------------------------------------

    def _clear_list(self) -> None:
        self.list.remove_all()
        self._row_count = 0
        self.decode_count.set_label("")

    def _scroll_to_end(self) -> bool:
        adj = self.scroller.get_vadjustment()
        adj.set_value(adj.get_upper() - adj.get_page_size())
        return False

    def _on_decoded(self, slot: int, decodes: list[Decode]) -> None:
        # Follow new decodes like a chat, unless the operator scrolled up to read.
        adj = self.scroller.get_vadjustment()
        at_bottom = adj.get_value() >= adj.get_upper() - adj.get_page_size() - 40
        if decodes or self._row_count:
            sep = Gtk.ListBoxRow(activatable=False, selectable=False)
            text = f"{_utc(self.engine.proto.slot_start(slot))}  ·  {len(decodes)} decode{'s' if len(decodes) != 1 else ''}"
            sep.set_child(_label(text, "caption-heading", "dim-label", xalign=0, margin_top=8, margin_start=12))
            self.list.append(sep)
            self._row_count += 1
        for d in decodes:
            self.list.append(DecodeRow(d, self.station.settings.callsign, self._answer, self._where(d),
                                       self._is_new(d), self._hide_call))
            self._row_count += 1
        self._update_labels()
        while self._row_count > MAX_ROWS:
            first = self.list.get_row_at_index(0)
            if first is None:
                break
            self.list.remove(first)
            self._row_count -= 1
        total = sum(len(v) for v in self.engine.decodes.values())
        self.decode_count.set_label(f"{total} decodes" if total else "")
        if at_bottom:
            GLib.timeout_add(150, self._scroll_to_end)   # after the new rows are laid out
        self._refresh_panel()

    def _on_transmitting(self, on: bool, text: str) -> None:
        self.waterfall.tx_offset = self.engine.tx_offset
        if on:
            self.cycle.add_css_class("tx")
        else:
            self.cycle.remove_css_class("tx")
        self.tune_button.set_label("Stop" if self.engine.tuning else "Tune")
        self._refresh_panel()

    def _on_logged(self, entry) -> None:
        self.toast(f"Contact with {entry.call} logged")
        if self.log_empty.get_parent():
            self.log_group.remove(self.log_empty)
        dist = grids.distance_km(self.station.settings.grid, entry.grid) if entry.grid else None
        sub = "  ·  ".join(x for x in (entry.grid, f"{dist:,.0f} km" if dist else "", entry.band,
                                        entry.time_off.strftime("%H:%M UTC")) if x)
        row = Adw.ActionRow(title=entry.call, subtitle=sub)
        row.add_css_class("property")
        self.log_group.add(row)
        self._log_rows.append(row)
        if len(self._log_rows) > 6:
            self.log_group.remove(self._log_rows.pop(0))

    def _refresh_setup(self) -> None:
        st = self.station.radio
        on_ft8 = self.engine.on_ft8_frequency()
        connected = st.link is Link.CONNECTED
        wrong_sub = st.data_submode is not None and st.data_submode is not DataSubmode.DATA_A
        self.setup_button.set_visible(connected and (on_ft8 is None or wrong_sub))
        self.band_dd.set_sensitive(connected)
        if on_ft8 is not None:
            self._syncing = True
            idx = next((i for i, b in enumerate(self._bands()) if b.name == on_ft8.name), None)
            if idx is not None and idx != self.band_dd.get_selected():
                self.band_dd.set_selected(idx)
            self._syncing = False
        if not connected:
            self.status.set_label("The radio isn't connected")
        elif not self.station.audio.rx:
            self.status.set_label("Waiting for radio audio")
        elif st.mode is not Mode.DATA:
            self.status.set_label("The radio isn't in DATA mode")
        elif on_ft8 is None:
            self.status.set_label(f"Listening on {st.frequency / 1e6:.3f} MHz "
                                  f"(not an {self.engine.proto.name} frequency)")
        else:
            self.status.set_label(f"Listening on {on_ft8.label}")
        self.empty.set_title("Listening…" if self.engine.listening else "Not Listening")
        p = self.engine.proto
        self.empty.set_description(
            f"Decodes appear after each {p.period:g}-second cycle" if self.engine.listening
            else f"Tune the radio to an {p.name} frequency to start decoding")
        self._refresh_panel()

    def _refresh_panel(self) -> None:
        seq = self.engine.sequencer
        active = seq.active
        self.idle_box.set_visible(not active)
        self.active_box.set_visible(active)
        self.waterfall.tx_offset = self.engine.tx_offset
        c = seq.contact
        self.waterfall.rx_offset = c.their_freq if (active and c and c.their_freq) else None
        self.offset_value.set_label(f"{self.engine.tx_offset} Hz")
        check = self.engine.check_tx()
        self.cq_button.set_sensitive(check.allowed)
        self.tune_button.set_sensitive(check.allowed or self.engine.tuning)
        self.tx_block.set_visible(not check.allowed and self.station.connected)
        self.tx_block.set_label(check.reason)
        if not active:
            return
        if seq.stage is Stage.CALLING_CQ:
            self.contact_call.set_label("Calling CQ")
            self.contact_where.set_label(f"Call {seq.repeats + (0 if self.engine.transmitting_text else 1)} "
                                         f"of 8  ·  {'even' if seq.tx_even else 'odd'} periods")
            self.contact_reports.set_label("")
        elif c is not None:
            self.contact_call.set_label(c.call)
            parts = []
            if c.grid:
                parts.append(c.grid)
                dist = grids.distance_km(self.station.settings.grid, c.grid)
                bearing = grids.bearing_deg(self.station.settings.grid, c.grid)
                if dist is not None:
                    parts.append(f"{dist:,.0f} km {grids.compass(bearing)}")
            self.contact_where.set_label("  ·  ".join(parts) or "Grid unknown")
            sent = f"{c.report_sent:+03d}" if c.report_sent is not None else "–"
            rcvd = f"{c.report_rcvd:+03d}" if c.report_rcvd is not None else "–"
            self.contact_reports.set_label(f"Report sent {sent}   ·   received {rcvd}")
        self._rebuild_conversation()

    def _rebuild_conversation(self) -> None:
        seq = self.engine.sequencer
        c = seq.contact
        items: list[tuple[float, str, bool]] = []
        for slot, ds in self.engine.decodes.items():
            for d in ds:
                if c and d.message.addressed_to(self.station.settings.callsign) and \
                        d.message.de.strip("<>") == c.call:
                    items.append((self.engine.proto.slot_start(slot), d.text, False))
        for when, text in seq.history:
            items.append((when.timestamp(), text, True))
        if self.engine.transmitting_text and self.engine.transmitting_text != "Tune":
            items.append((time.time(), self.engine.transmitting_text, True))
        key = tuple(t for _, t, _ in items[-8:])
        if key == self._conversation_key:
            return
        self._conversation_key = key
        child = self.conversation.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self.conversation.remove(child)
            child = nxt
        for _, text, mine in sorted(items, key=lambda x: x[0])[-8:]:
            self.conversation.append(Bubble(text, mine))

    def _clock_tick(self) -> bool:
        now = time.time()
        p = self.engine.proto
        slot = p.slot_of(now)
        t_in = now - p.slot_start(slot)
        self.clock.set_label(datetime.fromtimestamp(now, timezone.utc).strftime("%H:%M:%S UTC"))
        self.cycle.set_fraction(t_in / p.period)
        seq = self.engine.sequencer
        if seq.active:
            if seq.waiting:
                self.contact_status.remove_css_class("error")
                left = max(0.0, p.slot_start(seq.wait_until + 1) - now)
                who = seq.contact.call if seq.contact else "them"
                self.contact_status.set_label(f"Waiting for {who} to come back · {int(left // 60)}:"
                                              f"{int(left % 60):02d} left. KX3-Rig answers if they call.")
            elif self.engine.transmitting_text:
                self.contact_status.set_label("Transmitting…")
                self.contact_status.add_css_class("error")
            else:
                self.contact_status.remove_css_class("error")
                ours_next = ((slot + 1) % 2 == 0) == seq.tx_even
                wait = p.period - t_in + (0 if ours_next else p.period)
                if seq.next_message() is None:
                    self.contact_status.set_label("Listening for their 73…")
                else:
                    self.contact_status.set_label(f"Next transmission in {wait:.0f} s")
        return GLib.SOURCE_CONTINUE


def _clock_synchronized() -> bool:
    """systemd's view of NTP sync; assume fine if it can't be asked."""
    import subprocess

    try:
        out = subprocess.run(["timedatectl", "show", "-p", "NTPSynchronized", "--value"],
                             capture_output=True, text=True, timeout=3).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return True
    return out != "no"


def GObject_BIDIRECTIONAL():
    from gi.repository import GObject

    return GObject.BindingFlags.BIDIRECTIONAL | GObject.BindingFlags.SYNC_CREATE
