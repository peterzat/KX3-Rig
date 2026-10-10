"""The Radio view: tune, pick a band and mode, watch the band, listen and talk."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, GLib, Gtk  # noqa: E402

from .. import bandplan  # noqa: E402
from ..cat import Mode  # noqa: E402
from ..radio import Link, RadioState  # noqa: E402
from .freq_readout import FrequencyReadout  # noqa: E402
from .meters import SignalMeter  # noqa: E402
from .waterfall import FrequencyAxis, Waterfall  # noqa: E402

MODES = [Mode.LSB, Mode.USB, Mode.CW, Mode.AM, Mode.FM, Mode.DATA]
MODE_TIPS = {
    Mode.LSB: "Lower sideband voice (usual below 10 MHz)",
    Mode.USB: "Upper sideband voice (usual above 10 MHz)",
    Mode.CW: "Morse code",
    Mode.AM: "Amplitude modulation voice",
    Mode.FM: "Frequency modulation voice (10 m and 6 m)",
    Mode.DATA: "Digital modes such as FT8 (DATA A)",
}
STEPS = [(10, "10 Hz"), (100, "100 Hz"), (1_000, "1 kHz"), (10_000, "10 kHz")]


def _label(text: str, *classes: str, **kw) -> Gtk.Label:
    lbl = Gtk.Label(label=text, **kw)
    for c in classes:
        lbl.add_css_class(c)
    return lbl


class RadioPage(Gtk.Box):
    __gtype_name__ = "KX3RadioPage"

    def __init__(self, station, toast):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.station = station
        self.toast = toast
        self._syncing = False

        scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        clamp = Adw.Clamp(maximum_size=980, tightening_threshold=760)
        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=22,
                       margin_top=18, margin_bottom=18, margin_start=12, margin_end=12)
        clamp.set_child(body)
        scroller.set_child(clamp)
        self.append(scroller)

        # --- hero ------------------------------------------------------------------
        hero = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.readout = FrequencyReadout()
        self.readout.connect("tune", lambda w, hz: self.station.tune_to(hz))
        hero.append(self.readout)
        tags = Gtk.Box(spacing=8, halign=Gtk.Align.CENTER)
        self.band_tag = _label("20 m", "tag", "heading")
        self.mode_tag = _label("USB", "tag", "heading")
        self.state_tag = _label("Receiving", "tag", "heading")
        for t in (self.band_tag, self.mode_tag, self.state_tag):
            tags.append(t)
        hero.append(tags)
        body.append(hero)

        # --- meters + power --------------------------------------------------------------
        meters = Gtk.Box(spacing=24, halign=Gtk.Align.CENTER)
        self.meter = SignalMeter()
        self.meter.set_size_request(360, -1)
        meters.append(self.meter)
        meters.append(self._build_power())
        body.append(meters)

        # --- band + mode ------------------------------------------------------------------
        controls = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        controls.append(self._build_bands())
        controls.append(self._build_modes())
        body.append(controls)

        # --- waterfall ------------------------------------------------------------------
        wf_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.waterfall = Waterfall(station)
        self.waterfall.set_size_request(-1, 220)
        self.waterfall.describe_offset = self._describe_offset
        self.waterfall.connect("scroll-tune", lambda w, n: self.readout.nudge(n))
        self.axis = FrequencyAxis(self.waterfall)
        self.axis.labeler = self._axis_label
        self.axis.step_hz = 500
        wf_box.append(self.waterfall)
        wf_box.append(self.axis)
        body.append(wf_box)

        # --- talk ---------------------------------------------------------------------------
        body.append(self._build_talk())

        station.connect("radio-changed", lambda s, st: self.update(st))
        station.connect("talking-changed", lambda s, on: self._on_talking(on))
        station.connect("mic-level", lambda s, db: self.mic_bar.set_value(max(0.0, min(1.0, (db + 50) / 50))))
        station.connect("audio-changed", lambda s, a: self.update(self.station.radio))
        self.update(station.radio)

    # --- builders -----------------------------------------------------------------------------

    def _build_power(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, valign=Gtk.Align.CENTER)
        box.append(_label("Power", "caption-heading", "dim-label", xalign=0))
        self.power_button = Gtk.MenuButton(label="– W")
        self.power_button.add_css_class("flat")
        self.power_button.add_css_class("numeric")
        self.power_button.set_tooltip_text("Transmit Power")
        pop = Gtk.Popover()
        pbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin_top=8, margin_bottom=8,
                       margin_start=8, margin_end=8)
        pbox.append(_label("Transmit Power", "heading", xalign=0))
        max_w = self.station.settings.max_power_w
        self.power_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 1, max_w, 1)
        self.power_scale.set_size_request(240, -1)
        self.power_scale.set_draw_value(True)
        self.power_scale.set_digits(0)
        self.power_scale.set_value_pos(Gtk.PositionType.RIGHT)
        for w in range(1, int(max_w) + 1):
            if w in (1, 5, int(max_w)):
                self.power_scale.add_mark(w, Gtk.PositionType.BOTTOM, f"{w} W")
        self.power_scale.connect("value-changed", self._on_power_changed)
        pbox.append(self.power_scale)
        pbox.append(_label(f"5 W or less is recommended for data modes. KX3-Rig never sets more than {max_w:g} W.",
                           "caption", "dim-label", wrap=True, max_width_chars=34, xalign=0))
        pop.set_child(pbox)
        self.power_button.set_popover(pop)
        box.append(self.power_button)
        return box

    def _build_bands(self) -> Gtk.Widget:
        row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        row.append(_label("Band", "caption-heading", "dim-label", xalign=0))
        self.band_box = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, homogeneous=True,
                                    max_children_per_line=11, min_children_per_line=4,
                                    column_spacing=6, row_spacing=6)
        self.band_box.add_css_class("band-chips")
        self.band_buttons: dict[str, Gtk.ToggleButton] = {}
        group = None
        for band in bandplan.BANDS:
            btn = Gtk.ToggleButton(label=band.name.replace("m", ""))
            btn.set_tooltip_text(f"{band.label}  ·  {band.low / 1e6:g}–{band.high / 1e6:g} MHz")
            if group is not None:
                btn.set_group(group)
            group = group or btn
            btn.connect("toggled", self._on_band_toggled, band)
            self.band_buttons[band.name] = btn
            self.band_box.append(btn)
        row.append(self.band_box)
        return row

    def _build_modes(self) -> Gtk.Widget:
        row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        row.append(_label("Mode", "caption-heading", "dim-label", xalign=0))
        box = Gtk.Box(halign=Gtk.Align.START)
        box.add_css_class("linked")
        box.add_css_class("mode-switch")
        self.mode_buttons: dict[Mode, Gtk.ToggleButton] = {}
        group = None
        for mode in MODES:
            btn = Gtk.ToggleButton(label=mode.label)
            btn.set_tooltip_text(MODE_TIPS[mode])
            if group is not None:
                btn.set_group(group)
            group = group or btn
            btn.connect("toggled", self._on_mode_toggled, mode)
            self.mode_buttons[mode] = btn
            box.append(btn)
        row.append(box)
        return row

    def _build_talk(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, halign=Gtk.Align.CENTER)
        self.talk = Gtk.Button()
        content = Adw.ButtonContent(icon_name="audio-input-microphone-symbolic", label="Hold to Talk")
        self.talk.set_child(content)
        self.talk_content = content
        self.talk.add_css_class("pill")
        self.talk.add_css_class("talk")
        self.talk.add_css_class("suggested-action")
        self.talk.set_halign(Gtk.Align.CENTER)
        self.talk.set_tooltip_text("Transmit your voice while the button is held down")
        press = Gtk.GestureClick(button=Gdk.BUTTON_PRIMARY)
        press.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        press.connect("pressed", lambda *a: self._talk_pressed())
        press.connect("released", lambda *a: self.station.stop_talking())
        press.connect("cancel", lambda *a: self.station.stop_talking())
        press.connect("stopped", lambda *a: self.station.stop_talking())
        self.talk.add_controller(press)
        box.append(self.talk)

        self.mic_bar = Gtk.LevelBar(min_value=0, max_value=1)
        self.mic_bar.add_css_class("meter")
        self.mic_bar.set_size_request(220, -1)
        self.mic_bar.set_visible(False)
        box.append(self.mic_bar)

        self.talk_hint = _label("", "caption", "dim-label", wrap=True, justify=Gtk.Justification.CENTER,
                                max_width_chars=60)
        box.append(self.talk_hint)
        return box

    # --- interaction ------------------------------------------------------------------------

    def _talk_pressed(self) -> None:
        check = self.station.start_talking()
        if not check.allowed and check.reason:
            self.toast(check.reason)

    def _on_talking(self, on: bool) -> None:
        self.mic_bar.set_visible(on)
        self.mic_bar.set_value(0)
        if on:
            self.talk.add_css_class("on-air")
            self.talk.remove_css_class("suggested-action")
            self.talk_content.set_label("On the Air")
        else:
            self.talk.remove_css_class("on-air")
            self.talk.add_css_class("suggested-action")
            self.talk_content.set_label("Hold to Talk")
        self.update(self.station.radio)

    def _on_band_toggled(self, button: Gtk.ToggleButton, band: bandplan.Band) -> None:
        if self._syncing or not button.get_active():
            return
        current = bandplan.band_for(self.station.radio.frequency)
        if current is None or current.name != band.name:
            self.station.select_band(band)

    def _on_mode_toggled(self, button: Gtk.ToggleButton, mode: Mode) -> None:
        if self._syncing or not button.get_active():
            return
        if self.station.radio.mode is not mode:
            self.station.select_mode(mode)

    def _on_power_changed(self, scale: Gtk.Scale) -> None:
        if self._syncing:
            return
        watts = round(scale.get_value())
        self.power_button.set_label(f"{watts} W")
        if getattr(self, "_power_source", 0):
            GLib.source_remove(self._power_source)
        self._power_source = GLib.timeout_add(350, self._apply_power, watts)

    def _apply_power(self, watts: float) -> bool:
        self._power_source = 0
        self.station.set_power(watts)
        return False

    def set_step(self, step: int) -> None:
        self.readout.set_step(step)

    # --- state ----------------------------------------------------------------------------------

    def _lower_sideband(self) -> bool:
        return self.station.radio.mode in (Mode.LSB, Mode.DATA_REV)

    def _axis_label(self, hz: float) -> str:
        dial = self.station.radio.frequency
        if dial <= 0:
            return f"{hz:.0f}"
        rf = dial - hz if self._lower_sideband() else dial + hz
        return f"{rf / 1000:.1f}"

    def _describe_offset(self, hz: float) -> str:
        dial = self.station.radio.frequency
        if dial <= 0:
            return f"{hz:.0f} Hz"
        rf = dial - hz if self._lower_sideband() else dial + hz
        return f"{rf / 1e6:.4f} MHz  ·  {hz:.0f} Hz audio"

    def update(self, st: RadioState) -> None:
        online = st.link is Link.CONNECTED
        self._syncing = True
        try:
            self.readout.set_online(online)
            if st.frequency != self.readout.frequency:
                self.readout.set_frequency(st.frequency)
            band = bandplan.band_for(st.frequency)
            self.band_tag.set_label(band.label if band else "Out of band")
            for name, btn in self.band_buttons.items():
                btn.set_active(band is not None and band.name == name)
                btn.set_sensitive(online)
            mode = st.mode
            self.mode_tag.set_label(mode.label if mode else "–")
            for m, btn in self.mode_buttons.items():
                btn.set_active(mode is m or (mode is Mode.DATA_REV and m is Mode.DATA) or (mode is Mode.CW_REV and m is Mode.CW))
                btn.set_sensitive(online)
            transmitting = st.transmitting or st.ptt
            self.state_tag.set_label("Transmitting" if transmitting else "Receiving")
            if transmitting:
                self.state_tag.add_css_class("tx")
                self.meter.show_transmit(st.power_out, st.swr, self.station.settings.max_power_w)
            else:
                self.state_tag.remove_css_class("tx")
                self.meter.show_receive(st.smeter_db if online else -54)
            if st.power_set is not None:
                self.power_button.set_label(f"{st.power_set:g} W")
                if not self.power_button.get_popover().get_visible():
                    self.power_scale.set_value(st.power_set)
            self.power_button.set_sensitive(online)
            mirror = self._lower_sideband()
            if mirror != self.waterfall.mirror:
                self.waterfall.mirror = mirror
            self.axis.refresh()
            self._update_talk()
        finally:
            self._syncing = False

    def _update_talk(self) -> None:
        if self.station.talking:
            self.talk.set_sensitive(True)
            self.talk_hint.set_label("Speak normally. Release the button to listen.")
            return
        check = self.station.voice_check()
        self.talk.set_sensitive(check.allowed)
        if check.allowed:
            self.talk_hint.set_label("Using this computer's microphone. A headset avoids echo.")
        else:
            self.talk_hint.set_label(check.reason)
