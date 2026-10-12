"""The Keyboard view: PSK31 and CW, read and typed on the computer.

Left: setup strip (mode, band, speed), waterfall, the conversation transcript,
and the compose line with macro buttons. Right: the contact (their call, name,
Log Contact) and, for PSK31, every signal on the band with its latest text.
"""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk, Pango  # noqa: E402

from .. import bandplan  # noqa: E402
from ..cat import DataSubmode, Mode  # noqa: E402
from ..keyboard.engine import CW, MACROS, PSK31, WIDTH_HZ, KeyboardEngine, dial_for  # noqa: E402
from ..radio import Link  # noqa: E402
from .waterfall import FrequencyAxis, Waterfall  # noqa: E402

MODE_NAMES = {PSK31: "PSK31", CW: "CW"}


def _label(text: str = "", *classes: str, **kw) -> Gtk.Label:
    lbl = Gtk.Label(label=text, **kw)
    for c in classes:
        lbl.add_css_class(c)
    return lbl


def _mhz(hz: int) -> str:
    return f"{hz / 1e6:.4f}".rstrip("0").rstrip(".") if hz % 1000 else f"{hz / 1e6:.3f}"


class ChannelRow(Gtk.ListBoxRow):
    """One PSK31 signal in the band: where it is and what it said last."""

    def __init__(self, channel):
        super().__init__()
        self.channel_id = channel.id
        self.freq = channel.freq
        box = Gtk.Box(spacing=10, margin_top=6, margin_bottom=6, margin_start=10, margin_end=10)
        self.hz = _label("", "numeric", "dim-label", width_chars=5, xalign=1)
        self.text = _label("", "monospace", xalign=0, hexpand=True, ellipsize=Pango.EllipsizeMode.START)
        box.append(self.hz)
        box.append(self.text)
        self.set_child(box)
        self.update(channel)

    def update(self, channel) -> None:
        self.freq = channel.freq
        self.hz.set_label(f"{channel.freq:.0f}")
        text = " ".join(channel.text.split())[-60:]
        self.text.set_label(text or "…")
        self.set_tooltip_text(f"{channel.freq:.0f} Hz · click to read this signal")


class KeyboardPage(Gtk.Box):
    __gtype_name__ = "KX3KeyboardPage"

    def __init__(self, station, engine: KeyboardEngine, toast, confirm_tx):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.station = station
        self.engine = engine
        self.toast = toast
        self.confirm_tx = confirm_tx
        self._channel_rows: dict[int, ChannelRow] = {}

        self.split = Adw.OverlaySplitView(sidebar_position=Gtk.PackType.END, max_sidebar_width=380,
                                          min_sidebar_width=300, sidebar_width_fraction=0.32)
        self.split.set_content(self._build_main())
        self.split.set_sidebar(self._build_panel())
        self.split.set_vexpand(True)
        self.append(self.split)

        engine.connect("received", lambda e, text: self._insert(text, ours=False))
        engine.connect("sent-text", lambda e, text: self._insert(text, ours=True))
        engine.connect("sending", lambda e, on, text: self._on_sending(on))
        engine.connect("channels", lambda e, chans: self._on_channels(chans))
        engine.connect("changed", lambda e: self._refresh())
        engine.connect("event", lambda e, kind, msg: self.toast(msg))
        station.connect("radio-changed", lambda s, st: self._refresh())
        station.connect("audio-changed", lambda s, a: self._refresh())
        # Decode only while this view is on screen.
        self.connect("map", lambda w: engine.start())
        self.connect("unmap", lambda w: engine.stop())
        GLib.timeout_add(500, self._tick)
        self._refresh()

    # --- construction ------------------------------------------------------------------

    def _build_main(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin_top=12, margin_bottom=12,
                      margin_start=12, margin_end=12)
        strip = Gtk.Box(spacing=12)
        modes = Gtk.Box(valign=Gtk.Align.CENTER)
        modes.add_css_class("linked")
        self.mode_buttons: dict[str, Gtk.ToggleButton] = {}
        for mode, tip in ((PSK31, "Keyboard-to-keyboard text, about 60 Hz wide"),
                          (CW, "Morse code, sent as a keyed tone and read by the computer")):
            b = Gtk.ToggleButton(label=MODE_NAMES[mode], tooltip_text=tip, active=self.engine.mode == mode)
            if self.mode_buttons:
                b.set_group(next(iter(self.mode_buttons.values())))
            b.connect("toggled", self._on_mode_toggled, mode)
            self.mode_buttons[mode] = b
            modes.append(b)
        strip.append(modes)
        self.band_model = Gtk.StringList()
        self.band_dd = Gtk.DropDown(model=self.band_model, tooltip_text="Band")
        self._bands: list[bandplan.Band] = []
        self._fill_bands()
        strip.append(self.band_dd)
        self.tune_button = Gtk.Button(label="Tune Radio")
        self.tune_button.add_css_class("suggested-action")
        self.tune_button.add_css_class("pill")
        self.tune_button.connect("clicked", lambda b: self._tune_radio())
        strip.append(self.tune_button)
        self.status = _label("", "dim-label", xalign=0, hexpand=True, ellipsize=Pango.EllipsizeMode.END)
        strip.append(self.status)
        self.speed_box = Gtk.Box(spacing=6, valign=Gtk.Align.CENTER)
        self.speed_box.append(_label("Speed", "caption", "dim-label"))
        self.speed = Gtk.SpinButton.new_with_range(8, 40, 1)
        self.speed.set_value(self.engine.wpm)
        self.speed.set_tooltip_text("Sending Speed (words per minute)")
        self.speed.connect("value-changed", lambda s: self.engine.set_wpm(int(s.get_value())))
        self.speed_box.append(self.speed)
        self.speed_box.append(_label("WPM", "caption", "dim-label"))
        self.find_button = Gtk.Button(label="Find Tone", tooltip_text="Listen on the strongest CW signal")
        self.find_button.connect("clicked", lambda b: self._find_tone())
        self.speed_box.append(self.find_button)
        strip.append(self.speed_box)
        self.panel_toggle = Gtk.ToggleButton(icon_name="sidebar-show-right-symbolic", valign=Gtk.Align.CENTER,
                                             tooltip_text="Show Contact Panel", visible=False)
        self.panel_toggle.add_css_class("flat")
        from gi.repository import GObject
        self.split.bind_property("show-sidebar", self.panel_toggle, "active",
                                 GObject.BindingFlags.BIDIRECTIONAL | GObject.BindingFlags.SYNC_CREATE)
        strip.append(self.panel_toggle)
        box.append(strip)

        wf_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.waterfall = Waterfall(self.station)
        self.waterfall.set_size_request(-1, 130)
        self.waterfall.set_vexpand(False)
        self.waterfall.describe_offset = lambda hz: f"{hz:.0f} Hz  ·  click to read and send here"
        self.waterfall.connect("offset-clicked", lambda w, hz, shift: self._set_offset(hz))
        axis = FrequencyAxis(self.waterfall)
        wf_box.append(self.waterfall)
        wf_box.append(axis)
        box.append(wf_box)

        self.transcript = Gtk.TextView(editable=False, cursor_visible=False, wrap_mode=Gtk.WrapMode.WORD_CHAR,
                                       monospace=True, top_margin=10, bottom_margin=10, left_margin=12,
                                       right_margin=12)
        self.transcript.add_css_class("transcript")
        buf = self.transcript.get_buffer()
        self._ours_tag = buf.create_tag("ours", foreground="#3584e4", weight=Pango.Weight.BOLD)
        self._note_tag = buf.create_tag("note", foreground="#9a9996", scale=0.85, weight=Pango.Weight.BOLD)
        self.scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        self.scroller.set_child(self.transcript)
        overlay = Gtk.Overlay()
        overlay.set_child(self.scroller)
        self.empty = Adw.StatusPage(icon_name="kx3rig-keyboard-symbolic", title="Listening…",
                                    description="Click a signal on the waterfall to read it")
        self.empty.add_css_class("compact")
        self.empty.set_can_target(False)
        overlay.add_overlay(self.empty)
        card = Gtk.Frame()
        card.add_css_class("view")
        card.set_child(overlay)
        box.append(card)

        macros = Gtk.Box(spacing=6)
        self.macro_box = macros
        box.append(macros)
        compose = Gtk.Box(spacing=8)
        self.entry = Gtk.Entry(hexpand=True, placeholder_text="Type a message, then press Send")
        self.entry.connect("activate", lambda e: self._send())
        self.entry.connect("changed", lambda e: self._refresh_send())
        compose.append(self.entry)
        self.send_button = Gtk.Button(label="Send")
        self.send_button.add_css_class("suggested-action")
        self.send_button.add_css_class("pill")
        self.send_button.connect("clicked", lambda b: self._send_or_stop())
        compose.append(self.send_button)
        box.append(compose)
        self.tx_info = _label("", "caption", "dim-label", xalign=0, wrap=True)
        box.append(self.tx_info)
        self._fill_macros()
        return box

    def _build_panel(self) -> Gtk.Widget:
        scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18, margin_top=18, margin_bottom=18,
                        margin_start=18, margin_end=18)
        scroller.set_child(panel)

        contact = Adw.PreferencesGroup(title="Contact")
        self.call_row = Adw.EntryRow(title="Their Call")
        self.call_row.connect("changed", lambda r: self.engine.set_their_call(r.get_text()))
        contact.add(self.call_row)
        self.heard_row = Adw.ActionRow(title="Heard", subtitle="", visible=False)
        use = Gtk.Button(label="Use", valign=Gtk.Align.CENTER)
        use.connect("clicked", lambda b: self.call_row.set_text(self.engine.suggested_call()))
        self.heard_row.add_suffix(use)
        contact.add(self.heard_row)
        self.name_row = Adw.EntryRow(title="Their Name")
        contact.add(self.name_row)
        self.sent_row = Adw.EntryRow(title="Report Sent", text="599")
        self.rcvd_row = Adw.EntryRow(title="Report Received", text="599")
        contact.add(self.sent_row)
        contact.add(self.rcvd_row)
        panel.append(contact)
        self.log_button = Gtk.Button(label="Log Contact", halign=Gtk.Align.START)
        self.log_button.add_css_class("pill")
        self.log_button.connect("clicked", lambda b: self._log())
        panel.append(self.log_button)

        self.signals_group = Adw.PreferencesGroup(title="Signals Heard",
                                                  description="PSK31 on this band right now. Click one to read it.")
        self.channel_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.channel_list.add_css_class("boxed-list")
        self.channel_list.set_placeholder(_label("Nothing yet", "dim-label", margin_top=12, margin_bottom=12))
        self.channel_list.connect("row-activated", lambda lb, row: self._set_offset(row.freq))
        self.signals_group.add(self.channel_list)
        panel.append(self.signals_group)

        self.cw_group = Adw.PreferencesGroup(title="Reading")
        self.cw_speed_row = Adw.ActionRow(title="Their Speed", subtitle="–")
        self.cw_speed_row.add_css_class("property")
        self.cw_group.add(self.cw_speed_row)
        panel.append(self.cw_group)
        return scroller

    # --- mode and band -----------------------------------------------------------------

    def _fill_bands(self) -> None:
        mode = self.engine.mode
        self._bands = [b for b in bandplan.BANDS if dial_for(mode, b) is not None and b.name != "60m"]
        self._syncing = True
        self.band_model.splice(0, self.band_model.get_n_items(),
                               [f"{b.label}  ·  {_mhz(dial_for(mode, b))} MHz" for b in self._bands])
        current = bandplan.band_for(self.station.radio.frequency)
        names = [b.name for b in self._bands]
        name = current.name if current and current.name in names else "20m"
        self.band_dd.set_selected(names.index(name))
        self._syncing = False

    def _on_mode_toggled(self, button, mode: str) -> None:
        if not button.get_active() or self.engine.mode == mode:
            return
        if self.engine.busy:
            self.toast("Wait for the message to finish, or press Stop")
            self.mode_buttons[self.engine.mode].set_active(True)
            return
        self.engine.set_mode(mode)
        buf = self.transcript.get_buffer()
        if buf.get_char_count():
            buf.insert_with_tags(buf.get_end_iter(), f"\n\n{MODE_NAMES[mode]}\n", self._note_tag)
        self._fill_bands()
        self._fill_macros()
        self._on_channels([])
        self._refresh()

    def _fill_macros(self) -> None:
        child = self.macro_box.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self.macro_box.remove(child)
            child = nxt
        for title, template in MACROS[self.engine.mode]:
            b = Gtk.Button(label=title, tooltip_text=template)
            b.add_css_class("flat")
            b.connect("clicked", lambda btn, t=template: self._use_macro(t))
            self.macro_box.append(b)

    def _use_macro(self, template: str) -> None:
        self.engine.their_name = self.name_row.get_text()
        self.entry.set_text(self.engine.macro(template))
        self.entry.grab_focus()
        self.entry.set_position(-1)

    def _tune_radio(self) -> None:
        if not self._bands:
            return
        band = self._bands[min(self.band_dd.get_selected(), len(self._bands) - 1)]
        other = self.station.auto_keying(exclude=self.engine)
        if other:
            self.toast(other)
            return
        if not self.engine.tune_radio(band):
            self.toast("Can't change frequency while transmitting")

    def _set_offset(self, hz: float) -> None:
        self.engine.set_offset(hz)

    def _find_tone(self) -> None:
        hz = self.engine.find_cw_tone()
        if hz is None:
            self.toast("No CW signal found. Click one on the waterfall instead.")

    # --- transmit -----------------------------------------------------------------------

    def _send_or_stop(self) -> None:
        if self.engine.busy:
            self.engine.halt()
        else:
            self._send()

    def _send(self) -> None:
        text = self.entry.get_text()
        check = self.engine.check_tx(text)
        if not check.allowed:
            self.toast(check.reason)
            return

        def go():
            result = self.engine.send(text)
            if result.allowed:
                self.entry.set_text("")
            else:
                self.toast(result.reason)
        self.confirm_tx(go)

    def _on_sending(self, on: bool) -> None:
        if on:
            self.send_button.set_label("Stop")
            self.send_button.remove_css_class("suggested-action")
            self.send_button.add_css_class("destructive-action")
        else:
            self.send_button.set_label("Send")
            self.send_button.remove_css_class("destructive-action")
            self.send_button.add_css_class("suggested-action")
        self._refresh()

    def _log(self) -> None:
        try:
            entry = self.engine.log_contact(self.sent_row.get_text(), self.rcvd_row.get_text(),
                                            self.name_row.get_text())
        except (ValueError, OSError) as exc:
            self.toast(str(exc))
            return
        self.toast(f"Contact with {entry.call} logged")
        self.call_row.set_text("")
        self.name_row.set_text("")

    # --- receive ------------------------------------------------------------------------

    def _insert(self, text: str, ours: bool) -> None:
        buf = self.transcript.get_buffer()
        adj = self.scroller.get_vadjustment()
        at_bottom = adj.get_value() >= adj.get_upper() - adj.get_page_size() - 40
        end = buf.get_end_iter()
        if ours:
            buf.insert_with_tags(end, text, self._ours_tag)
        else:
            buf.insert(end, text)
        if buf.get_char_count() > 20_000:
            start = buf.get_start_iter()
            cut = buf.get_iter_at_offset(buf.get_char_count() - 15_000)
            buf.delete(start, cut)
        self.empty.set_visible(False)
        if at_bottom:
            GLib.idle_add(self._scroll_to_end)
        if not ours:
            self._refresh_heard()

    def _scroll_to_end(self) -> bool:
        adj = self.scroller.get_vadjustment()
        adj.set_value(adj.get_upper() - adj.get_page_size())
        return False

    def _refresh_heard(self) -> None:
        call = self.engine.suggested_call()
        show = bool(call) and call != self.engine.their_call
        self.heard_row.set_visible(show)
        if show:
            self.heard_row.set_subtitle(call)

    def _on_channels(self, channels) -> None:
        seen = set()
        for ch in sorted(channels, key=lambda c: c.freq):
            seen.add(ch.id)
            row = self._channel_rows.get(ch.id)
            if row is None:
                row = ChannelRow(ch)
                self._channel_rows[ch.id] = row
                self.channel_list.append(row)
            else:
                row.update(ch)
        for cid in [c for c in self._channel_rows if c not in seen]:
            self.channel_list.remove(self._channel_rows.pop(cid))

    # --- state --------------------------------------------------------------------------

    def _on_dial(self) -> bool:
        st = self.station.radio
        band = bandplan.band_for(st.frequency)
        dial = dial_for(self.engine.mode, band) if band else None
        return dial is not None and abs(st.frequency - dial) < 3_000

    def _refresh(self) -> None:
        if self.call_row.get_text().strip().upper() != self.engine.their_call:
            self.call_row.set_text(self.engine.their_call)
        st = self.station.radio
        mode = self.engine.mode
        connected = st.link is Link.CONNECTED
        data_a = st.mode is Mode.DATA and st.data_submode is DataSubmode.DATA_A
        self.tune_button.set_visible(connected and not (data_a and self._on_dial()))
        self.band_dd.set_sensitive(connected)
        self.speed_box.set_visible(mode == CW)
        self.signals_group.set_visible(mode == PSK31)
        self.cw_group.set_visible(mode == CW)
        self.waterfall.marker_width_hz = WIDTH_HZ[mode]
        half = WIDTH_HZ[mode] / 2
        self.waterfall.rx_offset = self.engine.tracked_hz - half
        self.waterfall.tx_offset = self.engine.offset_hz - half if self.engine.busy else None
        if not connected:
            self.status.set_label("The radio isn't connected")
        elif not self.station.audio.rx:
            self.status.set_label("Waiting for radio audio")
        elif not data_a:
            self.status.set_label("Press Tune Radio to set DATA A")
        else:
            self.status.set_label(f"{MODE_NAMES[mode]} at {self.engine.offset_hz:.0f} Hz  ·  "
                                  f"{(st.frequency + self.engine.offset_hz) / 1e6:.4f} MHz")
        self._refresh_send()

    def _refresh_send(self) -> None:
        text = self.entry.get_text()
        if self.engine.busy:
            self.send_button.set_sensitive(True)
            self.tx_info.set_label(f"Sending {MODE_NAMES[self.engine.mode]}…  Stop or Esc ends it.")
            return
        check = self.engine.check_tx(text or "x")
        self.send_button.set_sensitive(check.allowed and bool(text.strip()))
        if not check.allowed and self.station.connected:
            self.tx_info.set_label(check.reason)
        elif text.strip():
            secs = self.engine.duration_s(text)
            self.tx_info.set_label(f"About {secs:.0f} s on the air")
        else:
            self.tx_info.set_label("")

    def _tick(self) -> bool:
        if self.engine.mode == CW and self.engine.running:
            import time as _time

            recent = _time.monotonic() - self.engine.last_received < 10
            wpm = self.engine.cw_wpm
            self.cw_speed_row.set_subtitle(f"{wpm:.0f} WPM" if recent or self.engine.signal_active else "–")
        if self.engine.mode == PSK31 and self.engine.running:
            half = WIDTH_HZ[PSK31] / 2
            self.waterfall.rx_offset = self.engine.tracked_hz - half
        return GLib.SOURCE_CONTINUE

    def halt(self) -> None:
        self.engine.halt()
