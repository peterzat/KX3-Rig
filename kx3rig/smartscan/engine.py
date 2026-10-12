"""Smartscan: sweep the band, find stations, keep a list of who was heard.

Runs on the GLib main loop with a 50 ms tick. Each step of the sweep:

    tune      set the dial (a verified SET through the link) and wait until
              the radio has it
    settle    skip SETTLE_S of audio (synthesizer and AGC settling, audio
              pipeline latency)
    quick     listen QUICK_S; if nothing that could be a contact is there,
              move on (most steps of a quiet band end here)
    confirm   a possible station: listen to CONFIRM_S, or to CLIP_S when the
              heard list has no fresh clip of it, and detect again on the
              longer audio
    record    noise floor and detections for the band view, hearings for the
              heard list, a clip for replay

Receive only. While it runs, Station.scanning makes every transmit path
refuse. It stops when the operator takes over (tunes, changes mode or band,
transmits), when the radio disconnects, or on Stop; a plain Stop puts the
radio back where it was.

The band outlook (conditions.py) is fetched on a worker thread while
Smartscan is on, no more often than the sources ask. In demo mode a
synthetic outlook stands in, so the demo never touches the network.
"""

from __future__ import annotations

import collections
import logging
import threading
import time

import gi
import numpy as np

gi.require_version("GLib", "2.0")
from gi.repository import GLib, GObject  # noqa: E402

from .. import bandplan  # noqa: E402
from ..cat import DataSubmode, Mode  # noqa: E402
from ..radio import Link  # noqa: E402
from . import conditions  # noqa: E402
from .detect import RATE, detect, noise_floor_db  # noqa: E402
from .heard import HeardList  # noqa: E402
from .plan import Plan, make_plan  # noqa: E402

log = logging.getLogger(__name__)

TICK_MS = 50
SETTLE_S = 0.25
QUICK_S = 0.6
CONFIRM_S = 1.5
CLIP_S = 5.0
CLIP_REFRESH_S = 300        # record a new clip of a known station after this long
TUNE_TIMEOUT_S = 3.0        # the radio never reached the step: give up the scan
TAKEOVER_S = 0.4            # a different frequency for this long means the operator tuned
REVISIT_EVERY = 6           # after this many sweep steps, check the next calling frequency

# Module level, so turning Smartscan off and on does not query sooner than the
# sources allow.
_last_fetch = {"psk": 0.0, "kp": 0.0}


class Smartscan(GObject.Object):
    __gtype_name__ = "KX3Smartscan"

    __gsignals__ = {
        # Running or stopped, plan, position, sweep timing: anything in the status line.
        "changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "heard-changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
        # A step's findings: (dial, [Detection], t_start, t_end) for the waterfall.
        "dwell": (GObject.SignalFlags.RUN_FIRST, None, (object,)),
        "conditions-changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
        # (kind, message) for toasts.
        "event": (GObject.SignalFlags.RUN_FIRST, None, (str, str)),
    }

    def __init__(self, station, ft8_engine=None, demo: bool = False):
        super().__init__()
        self.station = station
        self.ft8 = ft8_engine
        self.demo = demo
        self.active = False
        self.plan: Plan | None = None
        self.heard = HeardList()
        self.noise: dict[int, float] = {}            # dial -> noise floor (dB) on the last visit
        self.carriers: dict[int, list[tuple[int, int]]] = {}   # dial -> carrier RF spans
        self.index = 0
        self.position = 0                            # dial frequency of the current step
        self.sweeps = 0
        self.sweep_seconds: float | None = None
        self.outlook: dict[str, conditions.BandOutlook] | None = None
        self.kp: float | None = None
        self.conditions_error = ""
        self.fetching = False
        self._origin: tuple[int, Mode | None, DataSubmode | None] | None = None
        self._timer = 0
        self._phase = ""
        self._phase_since = 0.0
        self._listen_from = 0.0
        self._want_s = QUICK_S
        self._smeter = -54.0
        self._off_target_since: float | None = None
        self._sweep_started = 0.0
        self._samples: collections.deque = collections.deque(maxlen=2000)
        self._lock = threading.Lock()
        self._quick_done = False
        self._on_hot = False
        self._since_hot = 0
        self._hot_index = 0
        self._step_started = 0.0
        self._step_avg: float | None = None

    # --- control ---------------------------------------------------------------------------

    def start(self) -> str:
        """Begin sweeping the band the radio is on. Returns "" or why not."""
        if self.active:
            return ""
        st = self.station.radio
        if not self.station.connected:
            return "The radio isn't connected."
        if self.station.transmitting:
            return "Stop transmitting first."
        if self.ft8 is not None and self.ft8.busy:
            return "Finish the FT8 contact first."
        if not self.station.audio.rx:
            return "Radio audio isn't available, so there is nothing to listen to."
        band = bandplan.band_for(st.frequency)
        if band is None:
            return "Tune to an amateur band first."
        plan = make_plan(band, st.mode, self.station.settings.license_class, st.bandwidth)
        if plan is None:
            if band.name == "60m":
                return "Smartscan doesn't sweep 60 m (it is channelized)."
            return f"Your license class has no voice or CW privileges on {band.label}."
        self.plan = plan
        self._origin = (st.frequency, st.mode, st.data_submode)
        if self.heard.entries and self.heard.entries[0].kind != plan.kind or not self._same_band(plan):
            self.heard.clear()
            self.noise.clear()
            self.carriers.clear()
            self.emit("heard-changed")
        # Start at the step nearest the dial: that is where the antenna is tuned.
        self.index = min(range(len(plan.steps)), key=lambda i: abs(plan.steps[i] - st.frequency))
        self.sweeps = 0
        self.sweep_seconds = None
        self._sweep_started = time.monotonic()
        self._step_started = 0.0
        self._on_hot = False
        self._since_hot = 0
        self.active = True
        self.station.scanning = True
        if st.mode is not plan.scan_mode:
            self.station.link.set_mode(plan.scan_mode)
        self.station.sample_listeners.append(self._feed)
        self._tune_step()
        self._timer = GLib.timeout_add(TICK_MS, self._tick)
        self._maybe_fetch(force_emit=True)
        self.emit("changed")
        return ""

    def _same_band(self, plan: Plan) -> bool:
        return bool(self.heard.entries) and bandplan.band_for(self.heard.entries[0].tune_hz) is plan.band

    def stop(self, reason: str = "", restore: bool = True) -> None:
        if not self.active:
            return
        self.active = False
        self.station.scanning = False
        if self._timer:
            GLib.source_remove(self._timer)
            self._timer = 0
        if self._feed in self.station.sample_listeners:
            self.station.sample_listeners.remove(self._feed)
        origin, self._origin = self._origin, None
        if restore and origin and self.station.connected and not self.station.transmitting:
            freq, mode, sub = origin
            self.station.link.set_frequency(freq)
            if mode is not None:
                self.station.link.set_mode(mode, sub if mode.is_data else None)
        self._phase = ""
        self.emit("changed")
        if reason:
            self.emit("event", "stopped", reason)

    def toggle(self) -> str:
        if self.active:
            self.stop()
            return ""
        return self.start()

    def tune(self, entry_id: int) -> None:
        """Stop and listen to a heard station."""
        entry = self.heard.get(entry_id)
        if entry is None:
            return
        self.stop(restore=False)
        if not self.station.connected or self.station.transmitting:
            return
        self.station.link.set_frequency(entry.tune_hz)
        self.station.link.set_mode(entry.mode)

    def play(self, entry_id: int, on_done=None) -> str:
        entry = self.heard.get(entry_id)
        if entry is None or entry.clip is None:
            return "No recording of that station yet."
        return self.station.play_clip(entry.clip, RATE, on_done)

    # --- audio (audio thread) ---------------------------------------------------------------

    def _feed(self, samples: np.ndarray, end_time: float) -> None:
        with self._lock:
            self._samples.append((end_time - len(samples) / RATE, samples))

    def _audio_since(self, t0: float) -> np.ndarray:
        with self._lock:
            chunks = [s for start, s in self._samples if start >= t0]
        return np.concatenate(chunks) if chunks else np.zeros(0, np.float32)

    # --- the sweep ---------------------------------------------------------------------------

    @property
    def sweep_estimate_s(self) -> float | None:
        """Expected time for a full sweep, from the average step so far."""
        if self.sweep_seconds is not None and self.sweeps >= 2:
            return self.sweep_seconds
        if self._step_avg is None or self.plan is None:
            return None
        extra = len(self.plan.steps) // REVISIT_EVERY if self.plan.hot_steps else 0
        return self._step_avg * (len(self.plan.steps) + extra)

    def _tune_step(self, dial: int | None = None) -> None:
        """Go to the sweep's current step, or to `dial` (a calling frequency)."""
        now = time.monotonic()
        if self._step_started:
            took = now - self._step_started
            self._step_avg = took if self._step_avg is None else 0.8 * self._step_avg + 0.2 * took
        self._step_started = now
        self.position = self.plan.steps[self.index] if dial is None else dial
        self.station.link.set_frequency(self.position)
        self._phase = "tune"
        self._phase_since = time.monotonic()
        self._off_target_since = None

    def _tick(self) -> bool:
        if not self.active:
            return GLib.SOURCE_REMOVE
        st = self.station.radio
        if st.link is not Link.CONNECTED:
            self.stop("Smartscan stopped: the radio disconnected.", restore=False)
            return GLib.SOURCE_REMOVE
        if self.station.transmitting or self.station.talking:
            self.stop("Smartscan stopped for transmit.", restore=False)
            return GLib.SOURCE_REMOVE
        now = time.monotonic()
        settled = not self.station.link.tuning_pending
        if self._phase == "tune":
            if settled and st.frequency == self.position and st.mode is self.plan.scan_mode:
                self._phase = "listen"
                self._listen_from = time.time() + SETTLE_S
                self._want_s = QUICK_S
                self._smeter = -54.0
                self._quick_done = False
            elif now - self._phase_since > TUNE_TIMEOUT_S:
                if st.mode is not self.plan.scan_mode:
                    self.stop("Smartscan stopped: the mode changed.", restore=False)
                else:
                    self.stop("Smartscan stopped: the radio didn't follow the sweep.", restore=False)
                return GLib.SOURCE_REMOVE
            return GLib.SOURCE_CONTINUE

        # Listening. Anyone else moving the dial or the mode is the operator taking over.
        if settled and (st.frequency != self.position or st.mode is not self.plan.scan_mode):
            if self._off_target_since is None:
                self._off_target_since = now
            elif now - self._off_target_since > TAKEOVER_S:
                self.stop("Smartscan stopped: you tuned the radio.", restore=False)
                return GLib.SOURCE_REMOVE
            return GLib.SOURCE_CONTINUE
        self._off_target_since = None
        self._smeter = max(self._smeter, st.smeter_db)
        audio = self._audio_since(self._listen_from)
        if len(audio) < self._want_s * RATE:
            return GLib.SOURCE_CONTINUE
        found = detect(audio)
        contacts = [d for d in found if d.is_contact]
        if not self._quick_done:
            self._quick_done = True
            if contacts:
                self.emit("dwell", (self.position, found, self._listen_from, time.time()))
                self._want_s = CLIP_S if self._needs_clip(contacts) else CONFIRM_S
                return GLib.SOURCE_CONTINUE
        self._finish_step(audio, found)
        return GLib.SOURCE_CONTINUE

    def _needs_clip(self, contacts) -> bool:
        now = time.time()
        for d in contacts:
            hz = self.plan.tune_frequency(self.position, d)
            entry = self._find(hz, d.kind)
            if entry is None or entry.clip is None or now - entry.last_seen > CLIP_REFRESH_S:
                return True
        return False

    def _find(self, hz: int, kind: str):
        from .heard import MERGE_HZ

        tol = MERGE_HZ.get(kind, 500)
        return next((e for e in self.heard.entries if e.kind == kind and abs(e.tune_hz - hz) <= tol), None)

    def _finish_step(self, audio: np.ndarray, found) -> None:
        plan, dial, now = self.plan, self.position, time.time()
        floor = noise_floor_db(audio)
        if floor is not None:
            self.noise[dial] = floor
        self.carriers[dial] = [plan.detection_rf(dial, d) for d in found if d.kind == "carrier"]
        contacts = [d for d in found if d.is_contact]
        self.emit("dwell", (dial, found, self._listen_from, now))
        clip = audio[-int(CLIP_S * RATE):] if len(audio) >= CLIP_S * RATE * 0.9 else None
        for d in contacts:
            low, high = plan.detection_rf(dial, d)
            if not any(lo <= (low + high) / 2 <= hi for lo, hi in plan.ranges):
                continue   # the window reaches past the sweep's edge; that station is outside it
            hz = plan.tune_frequency(dial, d)
            self.heard.add(hz, d.kind, plan.tune_mode, d.snr_db, self._smeter, now,
                           clip=clip, clip_dial=dial, spot=plan.spot_label(hz, d.kind))
        if contacts:
            self.emit("heard-changed")
        if self._on_hot:
            # Back to the sweep where it left off.
            self._on_hot = False
            self._tune_step()
            self.emit("changed")
            return
        self.index += 1
        self._since_hot += 1
        if self.index >= len(plan.steps):
            self.index = 0
            self.sweeps += 1
            mono = time.monotonic()
            self.sweep_seconds = mono - self._sweep_started
            self._sweep_started = mono
            self.heard.prune(now)
            self.emit("heard-changed")
        self._maybe_fetch()
        if plan.hot_steps and self._since_hot >= REVISIT_EVERY:
            # Calling frequencies are where a CQ is most likely: check them
            # every few seconds instead of once a sweep.
            self._since_hot = 0
            self._on_hot = True
            self._tune_step(plan.hot_steps[self._hot_index % len(plan.hot_steps)])
            self._hot_index += 1
            self.emit("changed")
            return
        self._tune_step()
        self.emit("changed")

    # --- band outlook -------------------------------------------------------------------------

    @property
    def grid(self) -> str:
        return conditions.grid4(self.station.settings.grid)

    @property
    def sun(self) -> str:
        return conditions.daylight(self.grid)

    def _maybe_fetch(self, force_emit: bool = False) -> None:
        if self.demo:
            if self.outlook is None and not self.fetching:
                self.fetching = True
                GLib.timeout_add(1800, self._demo_outlook)
            if force_emit:
                self.emit("conditions-changed")
            return
        now = time.time()
        due_psk = now - _last_fetch["psk"] >= conditions.PSKREPORTER_EVERY_S
        due_kp = now - _last_fetch["kp"] >= conditions.KP_EVERY_S
        if not self.fetching and (due_psk or due_kp):
            self.fetching = True
            if due_psk:
                _last_fetch["psk"] = now
            if due_kp:
                _last_fetch["kp"] = now
            grid = self.grid
            threading.Thread(target=self._fetch_worker, args=(grid, due_psk, due_kp),
                             name="smartscan-conditions", daemon=True).start()
        if force_emit:
            self.emit("conditions-changed")

    def _fetch_worker(self, grid: str, psk: bool, kp: bool) -> None:
        outlook = kp_value = None
        errors = []
        if psk:
            try:
                reports = conditions.parse_pskreporter(conditions.fetch(conditions.pskreporter_url(grid)))
                outlook = conditions.grade(reports, grid)
            except Exception as exc:
                log.info("PSKReporter fetch failed: %s", exc)
                errors.append("PSKReporter")
        if kp:
            try:
                kp_value = conditions.parse_kp(conditions.fetch(conditions.KP_URL))
            except Exception as exc:
                log.info("SWPC fetch failed: %s", exc)
                errors.append("NOAA")
        GLib.idle_add(self._on_fetched, outlook, kp_value, errors)

    def _on_fetched(self, outlook, kp_value, errors) -> bool:
        self.fetching = False
        if outlook is not None:
            self.outlook = outlook
        if kp_value is not None:
            self.kp = kp_value
        self.conditions_error = (f"Couldn't reach {' or '.join(errors)}. Trying again in a few minutes."
                                 if errors and self.outlook is None else "")
        self.emit("conditions-changed")
        return False

    def _demo_outlook(self) -> bool:
        self.fetching = False
        now = time.time()
        made = []
        for band, count, where, grid in (("20m", 46, "Japan", "PM95"), ("17m", 9, "New Zealand", "RF70"),
                                         ("40m", 31, "Mexico", "DK89"), ("15m", 2, "Australia", "QF56"),
                                         ("30m", 14, "Alaska", "BP51"), ("80m", 3, "Utah", "DN40")):
            f = bandplan.BY_NAME[band].ft8
            made += [conditions.Report(f"DEMO{i}", grid if i == 0 else "DM79", f"N7RX{i % 4}", f + i, "FT8",
                                       int(now) - 60, where if i == 0 else "United States") for i in range(count)]
        self.outlook = conditions.grade(made, self.grid, now)
        self.kp = 2.0
        self.emit("conditions-changed")
        return False
