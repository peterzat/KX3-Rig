"""Loop Tune: where the AlexLoop is tuned, and the meters the guide shows.

The guide (ui/looptune.py) walks the operator through the procedure in
docs/looptune.md. This object holds what outlives one run of the guide:

* where the loop was last tuned, and whether the dial has left it
  ("need-changed" fires when the advice changes, never while Smartscan's
  sweep is moving the dial)
* the receive-noise meter while the guide is peaking
* the lowest SWR and highest power seen while the operator holds TUNE

KX3-Rig never keys the radio for a loop tune. The carrier is the KX3's own
TUNE, started and stopped by the operator's hand on XMIT; KX3-Rig only reads
TQ, PO, and (firmware 2.93+) SW, as it does for any transmission.
"""

from __future__ import annotations

import time

import gi

gi.require_version("GLib", "2.0")
from gi.repository import GLib, GObject  # noqa: E402

from .. import bandplan  # noqa: E402
from .meter import NoiseMeter, Reading  # noqa: E402
from .state import Need, need  # noqa: E402

TUNE_PWR_W = 1.0          # the TUN PWR the guide asks for
TUNE_POWER_WARN_W = 3.0   # TUNE above this: TUN PWR is probably NOR (following PWR)
LONG_KEYDOWN_S = 10.0


class LoopTuner(GObject.Object):
    __gtype_name__ = "KX3LoopTuner"

    __gsignals__ = {
        # The advice for the current dial changed (tuned, peak, retune, no loop).
        "need-changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
        # A new receive-noise reading (Reading) while metering.
        "reading": (GObject.SignalFlags.RUN_FIRST, None, (object,)),
        # TUNE carrier started or stopped, or its power or SWR changed.
        "carrier": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self, station, demo_loop=None):
        super().__init__()
        self.station = station
        self.tuned_hz = 0              # unknown until the operator tunes (each start of the app)
        self.meter = NoiseMeter()
        self.metering = False
        # The carrier while the operator holds TUNE.
        self.keyed_since: float | None = None
        self.best_swr: float | None = None
        self.max_power: float | None = None
        self.carrier_seen = False
        # Demo only: the simulated loop's tuning, so the guide can turn a pretend knob.
        self.demo_loop = demo_loop
        self._need = self._compute()
        station.connect("radio-changed", lambda s, st: self._on_radio())

    # --- the advice ---------------------------------------------------------------------

    @property
    def need(self) -> Need:
        return self._need

    def need_for(self, hz: int) -> Need:
        return need(hz, self.tuned_hz)

    def _compute(self) -> Need:
        return need(self.station.radio.frequency, self.tuned_hz)

    def _refresh_need(self) -> None:
        new = self._compute()
        if new != self._need:
            self._need = new
            self.emit("need-changed")

    def mark_tuned(self, hz: int | None = None) -> None:
        self.tuned_hz = hz if hz is not None else self.station.radio.frequency
        self._refresh_need()
        self.emit("need-changed")

    # --- receive-noise meter ---------------------------------------------------------------

    def start_meter(self) -> None:
        if self.metering:
            return
        self.meter.reset()
        self.metering = True
        self.station.sample_listeners.append(self._feed)

    def stop_meter(self) -> None:
        self.metering = False
        if self._feed in self.station.sample_listeners:
            self.station.sample_listeners.remove(self._feed)

    def restart_meter(self) -> None:
        self.meter.reset()

    def _feed(self, samples, end_time: float) -> None:
        """Audio thread."""
        if self.station.radio.transmitting or self.station.radio.ptt:
            return
        reading = self.meter.feed(samples)
        if reading is not None:
            GLib.idle_add(self._emit_reading, reading)

    def _emit_reading(self, reading: Reading) -> bool:
        if self.metering:
            self.emit("reading", reading)
        return False

    # --- the TUNE carrier ---------------------------------------------------------------------

    def reset_carrier(self) -> None:
        self.keyed_since = None
        self.best_swr = None
        self.max_power = None
        self.carrier_seen = False

    @property
    def keyed(self) -> bool:
        return self.keyed_since is not None

    @property
    def keydown_s(self) -> float:
        return time.monotonic() - self.keyed_since if self.keyed_since is not None else 0.0

    @property
    def swr_readable(self) -> bool:
        """SW; exists from firmware 2.93 (PR p.33); older radios show SWR only on their display."""
        return (self.station.radio.firmware or 0) >= 2.93

    @property
    def tune_power_high(self) -> bool:
        return self.max_power is not None and self.max_power > TUNE_POWER_WARN_W

    def _on_radio(self) -> None:
        st = self.station.radio
        # The sweep moves the dial every second; the advice follows the operator's dial.
        if not self.station.scanning:
            self._refresh_need()
        on_air = st.transmitting and not st.ptt     # keyed at the radio, not by KX3-Rig
        changed = False
        if on_air and self.keyed_since is None:
            self.keyed_since = time.monotonic()
            self.carrier_seen = True
            changed = True
        elif not on_air and self.keyed_since is not None:
            self.keyed_since = None
            changed = True
        if on_air:
            if st.power_out is not None and (self.max_power is None or st.power_out > self.max_power):
                self.max_power = st.power_out
                changed = True
            if st.swr is not None and (self.best_swr is None or st.swr < self.best_swr):
                self.best_swr = st.swr
                changed = True
        if changed:
            self.emit("carrier")

    # --- demo -----------------------------------------------------------------------------------

    def demo_knob(self, offset_hz: float) -> None:
        """Demo: turn the pretend loop knob to resonate offset_hz from the dial."""
        loop = self.demo_loop
        if loop is not None:
            loop.manual = True
            loop.tuned_hz = int(self.station.radio.frequency + offset_hz)

    def demo_release(self) -> None:
        if self.demo_loop is not None:
            self.demo_loop.manual = False

    def demo_hold_tune(self, on: bool) -> None:
        """Demo: the operator holds XMIT (TUNE) on the emulated KX3."""
        fake = getattr(self.station, "_fake", None)
        if fake is not None:
            fake.tune = on

    def tx_check(self) -> bandplan.TxCheck:
        """Whether a TUNE carrier here is within the operator's privileges."""
        st = self.station.radio
        from ..cat import Mode

        return bandplan.tx_check(st.frequency, Mode.CW, self.station.settings.license_class)
