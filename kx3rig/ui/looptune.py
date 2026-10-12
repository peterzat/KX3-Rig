"""The Loop Tune guide: peak the AlexLoop on receive, then confirm with TUNE.

The procedure and its sources are in docs/looptune.md. Pages:

    setup   once: the two KX3 menu settings the procedure relies on
    peak    turn the knob for the loudest band noise (nothing transmitted)
    swr     hold XMIT for TUNE, dip the SWR, tap XMIT (the operator's hand
            keys the radio, never KX3-Rig)
    high    the SWR stayed high: re-site the loop; the ATU as a last resort
    done    the loop is tuned here; optionally start Smartscan
"""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk  # noqa: E402

from ..looptune.state import BANDWIDTH_HZ  # noqa: E402
from ..looptune.tuner import LONG_KEYDOWN_S, TUNE_PWR_W  # noqa: E402

PEAK_TEXT = {
    "searching": "Turn the knob slowly. The band noise jumps when the loop comes near this frequency.",
    "rising": "The noise is rising. Keep turning slowly.",
    "peak": "That is the peak. Leave the knob here.",
    "past": "You turned past the peak. Turn back slowly.",
}
GOOD_SWR = 1.5
HIGH_SWR = 2.0


def _label(text: str, *classes: str, **kw) -> Gtk.Label:
    kw.setdefault("wrap", True)
    kw.setdefault("xalign", 0)
    lbl = Gtk.Label(label=text, **kw)
    for c in classes:
        lbl.add_css_class(c)
    return lbl


def _steps(*items: str) -> Gtk.Widget:
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    for i, text in enumerate(items, 1):
        row = Gtk.Box(spacing=10)
        num = _label(str(i), "tag", "small", "numeric", valign=Gtk.Align.START, wrap=False)
        row.append(num)
        row.append(_label(text, hexpand=True))
        box.append(row)
    return box


def _page(title: str, intro: str) -> tuple[Gtk.Widget, Gtk.Box]:
    scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True,
                                  propagate_natural_height=True)
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14, margin_top=6, margin_bottom=18,
                  margin_start=18, margin_end=18)
    box.append(_label(title, "title-2"))
    if intro:
        box.append(_label(intro, "dim-label"))
    scroller.set_child(box)
    return scroller, box


class LoopTuneDialog(Adw.Dialog):
    __gtype_name__ = "KX3LoopTuneDialog"

    def __init__(self, tuner, settings, smartscan=None, then_scan: bool = False, toast=None):
        super().__init__(title="Loop Tune", content_width=520, content_height=600)
        self.tuner = tuner
        self.station = tuner.station
        self.settings = settings
        self.smartscan = smartscan
        self.then_scan = then_scan
        self.toast = toast or (lambda m: None)
        self.demo = tuner.demo_loop is not None
        self.rx_only = False
        self._handlers = []
        self._tick = 0

        st = self.station.radio
        band = tuner.need_for(st.frequency).band
        self.band_label = band.label if band else "this band"
        width = BANDWIDTH_HZ.get(band.name if band else "", 0)
        self.width_hz = width

        view = Adw.ToolbarView()
        header = Adw.HeaderBar()
        self.back = Gtk.Button(icon_name="go-previous-symbolic", tooltip_text="Back", visible=False)
        self.back.connect("clicked", lambda b: self._go_back())
        header.pack_start(self.back)
        view.add_top_bar(header)
        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.SLIDE_LEFT_RIGHT, vhomogeneous=False)
        view.set_content(self.stack)

        bottom = Gtk.Box(spacing=8, margin_top=8, margin_bottom=12, margin_start=18, margin_end=18)
        self.secondary = Gtk.Button(visible=False)
        bottom.append(self.secondary)
        bottom.append(Gtk.Box(hexpand=True))
        self.primary = Gtk.Button()
        self.primary.add_css_class("suggested-action")
        self.primary.add_css_class("pill")
        bottom.append(self.primary)
        view.add_bottom_bar(bottom)
        self.set_child(view)
        self._primary_cb = None
        self._secondary_cb = None
        self.primary.connect("clicked", lambda b: self._primary_cb and self._primary_cb())
        self.secondary.connect("clicked", lambda b: self._secondary_cb and self._secondary_cb())

        # Demo: one pretend knob shared by the peak and SWR pages.
        self.knob = None
        if self.demo:
            span = max(width, 10_000) * 3
            self.knob = Gtk.Adjustment(lower=-span, upper=span, value=span * 0.6,
                                       step_increment=max(width, 10_000) / 50)
            self.knob.connect("value-changed", lambda a: tuner.demo_knob(a.get_value()))

        self._build_setup()
        self._build_peak()
        self._build_swr()
        self._build_high()
        self._build_done()
        self._history: list[str] = []

        self._handlers.append(tuner.connect("reading", lambda t, r: self._on_reading(r)))
        self._handlers.append(tuner.connect("carrier", lambda t: self._refresh_swr()))
        self._tick = GLib.timeout_add(500, self._on_tick)
        self.connect("closed", lambda d: self._cleanup())

        # Smartscan moves the dial; tuning happens where the operator left it.
        if smartscan is not None and smartscan.active:
            smartscan.stop()
        self._show("peak" if settings.loop_setup_seen else "setup", remember=False)

    # --- pages ----------------------------------------------------------------------------

    def _build_setup(self) -> None:
        page, box = _page("Before the First Tune",
                          "Two KX3 menu settings, once. Hold MENU, turn the small OFS/VFO B knob to the entry, "
                          "and turn the big VFO A knob to change it. Hold MENU again to leave.")
        rows = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        rows.add_css_class("boxed-list")
        for title, subtitle in (
            (f"TUN PWR to {TUNE_PWR_W:.1f} W",
             "TUNE then sends a gentle carrier: enough to read SWR, easy on the loop and the KX3's amplifier "
             "while the loop is still off resonance."),
            ("ATU MD to BYP",
             "The AlexLoop is its own matching network. With the ATU in AUTO, any key-down can switch in a stored "
             "match that hides the loop's real SWR and turns power into heat."),
        ):
            row = Adw.ActionRow(title=title, subtitle=subtitle)
            row.set_subtitle_lines(0)
            rows.append(row)
        box.append(rows)
        box.append(_label("Loop Tune never transmits for you. When it needs a carrier, it asks you to hold XMIT "
                          "on the radio, so the radio is only keyed by your hand.", "caption", "dim-label"))
        self.stack.add_named(page, "setup")

    def _build_peak(self) -> None:
        page, box = _page("Peak on Receive", "")
        self.peak_intro = _label("", "dim-label")
        box.append(self.peak_intro)
        meter_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=6)
        meter_box.append(_label("Band Noise", "caption-heading", "dim-label"))
        self.peak_bar = Gtk.LevelBar(min_value=0, max_value=1)
        self.peak_bar.add_css_class("meter")
        self.peak_bar.add_css_class("loop-meter")
        meter_box.append(self.peak_bar)
        self.peak_status = _label(PEAK_TEXT["searching"], "heading")
        meter_box.append(self.peak_status)
        self.peak_detail = _label("", "caption", "dim-label", "numeric")
        meter_box.append(self.peak_detail)
        box.append(meter_box)
        if self.knob is not None:
            box.append(self._demo_knob())
        box.append(_label("Reach the knob from behind or beside the loop: a hand or body close to it shifts "
                          "the tuning. Nothing is transmitted on this step.", "caption", "dim-label"))
        self.stack.add_named(page, "peak")

    def _build_swr(self) -> None:
        page, box = _page("Fine-Tune with TUNE",
                          "A short, low-power carrier shows the loop's true resonance.")
        self.swr_privilege = _label("", "warning")
        box.append(self.swr_privilege)
        box.append(_steps(
            "Listen for a moment: make sure nobody is using the frequency.",
            "Hold XMIT on the KX3 for half a second to start TUNE.",
            "Turn the loop's knob slowly for the lowest SWR on the KX3's display (VFO A) and the brightest "
            "LED on the loop.",
            "Take your hand away, check the SWR again, then tap XMIT to stop.",
        ))
        status = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, margin_top=6)
        status.add_css_class("card")
        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, margin_top=12, margin_bottom=12,
                        margin_start=14, margin_end=14)
        status.append(inner)
        self.swr_state = _label("Waiting for TUNE", "heading")
        self.swr_detail = _label("", "caption", "dim-label", "numeric")
        inner.append(self.swr_state)
        inner.append(self.swr_detail)
        box.append(status)
        self.swr_warning = _label("", "caption", "warning")
        box.append(self.swr_warning)
        if self.knob is not None:
            box.append(self._demo_knob())
            hold = Gtk.ToggleButton(label="Hold XMIT (Demo)", halign=Gtk.Align.START)
            hold.connect("toggled", lambda b: self.tuner.demo_hold_tune(b.get_active()))
            self.demo_hold = hold
            box.append(hold)
        self.swr_result = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, visible=False)
        self.swr_result.append(_label("What was the lowest SWR?", "heading"))
        choices = Gtk.Box(spacing=8, homogeneous=True)
        for text, swr in ((f"{GOOD_SWR:g} or Lower", 1.4), (f"Up to {HIGH_SWR:g}", 1.9), (f"Above {HIGH_SWR:g}", 3.0)):
            b = Gtk.Button(label=text)
            b.add_css_class("pill")
            b.connect("clicked", lambda btn, v=swr: self._finish_swr(v))
            choices.append(b)
        self.swr_result.append(choices)
        box.append(self.swr_result)
        self.stack.add_named(page, "swr")

    def _build_high(self) -> None:
        page, box = _page("The SWR Stayed High",
                          "At true resonance a well-placed AlexLoop dips to about 1.5:1 or better. Above 2:1 at "
                          "the best dip, the loop's surroundings are usually the cause.")
        box.append(_steps(
            "Move the loop a few feet away from walls, metal, furniture with springs, and people.",
            "Stand it upright about a meter above the ground, outdoors if you can.",
            "Check the coax and its connectors. Use the coax that came with the loop.",
            "Peak on receive again, then retry TUNE.",
        ))
        expander = Gtk.Expander(label="Last Resort: the KX3's ATU")
        expander.set_child(_label(
            "If the SWR is still above 2:1 at the loop's best dip: set ATU MD to AUTO, tap ATU TUNE once (it "
            "transmits at 2 to 3 W for a few seconds), then peak the loop again, because the two interact. Never "
            "use the ATU instead of tuning the loop: a mistuned loop behind a matched ATU heats up instead of "
            "radiating. Set ATU MD back to BYP afterwards.", "caption", margin_top=6))
        box.append(expander)
        self.stack.add_named(page, "high")

    def _build_done(self) -> None:
        self.done_page = Adw.StatusPage(icon_name="kx3rig-loop-symbolic", title="Loop Tuned")
        self.done_page.add_css_class("compact")
        self.stack.add_named(self.done_page, "done")

    def _demo_knob(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        box.append(_label("Demo: this slider stands in for the loop's tuning knob.", "caption", "dim-label"))
        scale = Gtk.Scale(adjustment=self.knob, draw_value=False)
        box.append(scale)
        return box

    # --- navigation -------------------------------------------------------------------------

    def _show(self, name: str, remember: bool = True) -> None:
        current = self.stack.get_visible_child_name()
        if remember and current and current != name:
            self._history.append(current)
        self.stack.set_visible_child_name(name)
        self.back.set_visible(bool(self._history) and name != "done")
        if name != "swr" and getattr(self, "demo_hold", None) is not None:
            self.demo_hold.set_active(False)
        getattr(self, f"_enter_{name}")()

    def _go_back(self) -> None:
        if self._history:
            name = self._history.pop()
            self.stack.set_visible_child_name(name)
            self.back.set_visible(bool(self._history))
            getattr(self, f"_enter_{name}")()

    def _buttons(self, primary: str, on_primary, secondary: str = "", on_secondary=None) -> None:
        self.primary.set_label(primary)
        self._primary_cb = on_primary
        self.primary.set_visible(bool(primary))
        self.secondary.set_label(secondary)
        self.secondary.set_visible(bool(secondary))
        self._secondary_cb = on_secondary

    def _enter_setup(self) -> None:
        self.tuner.stop_meter()

        def next_():
            self.settings.loop_setup_seen = True
            self._show("peak")
        self._buttons("Next", next_)

    def _enter_peak(self) -> None:
        st = self.station.radio
        band = self.tuner.need_for(st.frequency).band
        self.band_label = band.label if band else "this band"
        self.width_hz = BANDWIDTH_HZ.get(band.name if band else "", 0)
        mhz = st.frequency / 1e6
        narrow = st.mode is not None and st.mode.is_cw
        text = (f"Set the loop's knob near the {self.band_label} mark, then find the peak for {mhz:.3f} MHz "
                "by ear and on the meter below.")
        if narrow:
            text += " The noise peak is easier to hear in USB or LSB than through the narrow CW filter."
        self.peak_intro.set_label(text)
        self.tuner.start_meter()
        if self.knob is not None:
            self.tuner.demo_knob(self.knob.get_value())
        self._buttons("Next", lambda: self._show("swr"), "Done Without TUNE", self._finish_rx_only)

    def _enter_swr(self) -> None:
        self.tuner.stop_meter()
        self.tuner.reset_carrier()
        check = self.tuner.tx_check()
        self.swr_privilege.set_label("" if check.allowed else
                                     f"{check.reason} Move to a frequency inside your privileges to use TUNE, "
                                     "or finish without it.")
        self.swr_privilege.set_visible(not check.allowed)
        self._buttons("", None, "Done Without TUNE", self._finish_rx_only)
        self._refresh_swr()

    def _enter_high(self) -> None:
        self._buttons("Peak Again", lambda: self._show("peak"), "Finish Anyway", lambda: self._show("done"))

    def _enter_done(self) -> None:
        self.tuner.stop_meter()
        self.tuner.mark_tuned()
        self.done_page.set_title("Loop Tuned")
        self.done_page.set_description(done_text(self.station.radio.frequency, self.width_hz, self.rx_only))
        if self.then_scan and self.smartscan is not None:
            self._buttons("Start Smartscan", self._start_scan, "Close", self.close)
        else:
            self._buttons("Done", self.close)

    # --- live state ----------------------------------------------------------------------------

    def _on_reading(self, r) -> None:
        if self.stack.get_visible_child_name() != "peak":
            return
        self.peak_bar.set_value(r.fraction())
        self.peak_status.set_label(PEAK_TEXT[r.state])
        for c in ("good", "warn"):
            self.peak_bar.remove_css_class(c)
        if r.state == "peak":
            self.peak_bar.add_css_class("good")
        elif r.state == "past":
            self.peak_bar.add_css_class("warn")
        self.peak_detail.set_label(f"{r.level_db - r.best_db:+.1f} dB from the best so far"
                                   if r.span_db >= 1 else "")

    def _refresh_swr(self) -> None:
        if self.stack.get_visible_child_name() != "swr":
            return
        t = self.tuner
        parts = []
        if t.keyed:
            self.swr_state.set_label("TUNE is on the air")
            if t.max_power is not None:
                parts.append(f"{self.station.radio.power_out or t.max_power:.1f} W")
            swr = self.station.radio.swr
            if t.swr_readable and swr is not None:
                parts.append(f"SWR {swr:.1f}")
            elif not t.swr_readable:
                parts.append("SWR is on the KX3's display")
            parts.append(f"{t.keydown_s:.0f} s")
        elif t.carrier_seen:
            self.swr_state.set_label("TUNE stopped")
            if t.best_swr is not None:
                parts.append(f"Lowest SWR {t.best_swr:.1f}")
        else:
            self.swr_state.set_label("Waiting for TUNE")
            parts.append("Hold XMIT on the KX3")
        self.swr_detail.set_label("  ·  ".join(parts))
        warn = ""
        if t.tune_power_high:
            warn = (f"TUNE is running at {t.max_power:.0f} W. Set MENU > TUN PWR to {TUNE_PWR_W:.1f} W: more power "
                    "only raises the voltage across the loop's capacitor.")
        elif t.keyed and t.keydown_s > LONG_KEYDOWN_S:
            warn = "Keep TUNE short: tap XMIT to stop, then check the reading."
        self.swr_warning.set_label(warn)
        self.swr_warning.set_visible(bool(warn))
        done = t.carrier_seen and not t.keyed
        if done and t.swr_readable and t.best_swr is not None:
            self.swr_result.set_visible(False)
            self._buttons("Next", lambda: self._finish_swr(t.best_swr), "Done Without TUNE", self._finish_rx_only)
        else:
            self.swr_result.set_visible(done)

    def _on_tick(self) -> bool:
        if self.stack.get_visible_child_name() == "swr" and self.tuner.keyed:
            self._refresh_swr()
        return GLib.SOURCE_CONTINUE

    # --- finishing ----------------------------------------------------------------------------

    def _finish_swr(self, swr: float) -> None:
        self.rx_only = False
        if swr > HIGH_SWR:
            self._show("high")
        else:
            self._show("done")

    def _finish_rx_only(self) -> None:
        self.rx_only = True
        self._show("done")

    def _start_scan(self) -> None:
        self.close()
        if self.smartscan is not None:
            reason = self.smartscan.start()
            if reason:
                self.toast(reason)

    def _cleanup(self) -> None:
        self.tuner.stop_meter()
        if self.knob is not None:
            self.tuner.demo_hold_tune(False)
            self.tuner.demo_release()
        if self._tick:
            GLib.source_remove(self._tick)
            self._tick = 0
        for h in self._handlers:
            self.tuner.disconnect(h)
        self._handlers = []


def done_text(hz: int, width_hz: int, rx_only: bool) -> str:
    """What the last page says: where it was tuned, and when to tune again."""
    how = "on receive noise" if rx_only else "with TUNE"
    text = f"Peaked {how} at {hz / 1e6:.3f} MHz."
    if width_hz:
        text += (f" The Loop tag turns amber as you move away (from about {width_hz / 4000:g} kHz here) and "
                 f"asks for a retune past {width_hz / 2000:g} kHz or on another band.")
    if rx_only:
        text += " Before transmitting, a quick check with TUNE confirms the SWR."
    return text
