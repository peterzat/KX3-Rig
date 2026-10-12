"""WSPR: listen for beacons every two minutes, and beacon now and then.

WSPR is the loop's report card. Stations heard here show where the band is
open to; with the beacon on, other stations report hearing KX3-Rig's 1 W or so
signal, which says how well the loop is getting out (see who on wsprnet.org).

Receive: the last 114 s of each even UTC minute go to WSJT-X's wsprd
(protocol.py has the file format). Transmit: when the beacon is on, the
scheduler (protocol.TxScheduler) picks about one period in five; the
transmission starts 1 s after the even minute and lasts 110.6 s.

Safety, as for every transmit path:
- the operator starts the beacon, for a set time (30 minutes to 2 hours),
  and it stops by itself after that; Stop or Esc ends it at once
- can_transmit() and DATA A are checked before every transmission
- the message carries the radio's actual power setting

Network: spots are shared with wsprnet.org only when the operator turns that
on; it sends the callsign, the 4-character grid, and the spots heard (the
same fields WSJT-X sends, Network/wsprnet.cpp, with the grid cut to four
characters). Never in demo mode.
"""

from __future__ import annotations

import logging
import os
import random
import shutil
import subprocess
import threading
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass

import gi
import numpy as np

gi.require_version("GLib", "2.0")
from gi.repository import GLib, GObject  # noqa: E402

from .. import bandplan, config  # noqa: E402
from ..cat import DataSubmode, Mode  # noqa: E402
from ..ft8 import grid as grids  # noqa: E402
from ..ft8.decode import SlotRecorder  # noqa: E402
from . import protocol as wspr  # noqa: E402

log = logging.getLogger(__name__)

WSPRD = "wsprd"
TX_RATE = 48_000
DECODE_AT_S = 114.2          # WSJT-X decodes after 396 * 3456 samples (114.05 s)
TX_WINDOW_S = (0.6, 2.5)     # key between these times into the period (audio starts at 1.0 s)
PTT_LEAD_S = 0.25
SPOT_HOURS = 6
BEACON_MINUTES = (30, 60, 120)
UPLOAD_URL = "http://wsprnet.org/post/"   # plain HTTP, as WSJT-X uses (Network/wsprnet.cpp:23)


@dataclass(frozen=True)
class Heard:
    """A spot with where it came from, relative to this station."""

    time: float
    band: str
    spot: wspr.Spot
    km: float | None
    bearing: float | None


def wsprd_available() -> bool:
    return shutil.which(WSPRD) is not None


def band_on_dial(hz: int) -> bandplan.Band | None:
    band = bandplan.band_for(hz)
    dial = wspr.DIALS.get(band.name) if band else None
    return band if dial is not None and abs(hz - dial) < 500 else None


class WsprEngine(GObject.Object):
    __gtype_name__ = "KX3WsprEngine"

    __gsignals__ = {
        "spots": (GObject.SignalFlags.RUN_FIRST, None, (int, object)),   # (slot, list[Heard])
        "changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "transmitting": (GObject.SignalFlags.RUN_FIRST, None, (bool,)),
        "event": (GObject.SignalFlags.RUN_FIRST, None, (str, str)),
    }

    def __init__(self, station, demo: bool = False):
        super().__init__()
        self.station = station
        self.settings: config.Settings = station.settings
        self.demo = demo
        self.recorder = SlotRecorder(seconds=130.0)
        self.workdir = os.path.join(config.data_dir(), "wsprd")
        self.heard: list[Heard] = []
        self.beacon_until: float | None = None        # wall time the beacon ends
        self.percent = 20
        self.scheduler = wspr.TxScheduler(self.percent)
        self.transmitting = False
        self.tx_count = 0
        self.audio_hz = 1500.0 + random.uniform(-80, 80)   # WSJT-X: anywhere in 1400-1600 Hz
        self._last_decode_slot = -1
        self._decoding = False
        self._tx_slots: set[int] = set()
        self._timer = 0
        station.register_keyer(self, lambda: "Stop the WSPR beacon first." if self.busy else "")

    # --- lifecycle -------------------------------------------------------------------

    def start(self) -> None:
        if not self._timer:
            self.station.sample_listeners.append(self.recorder.feed)
            self._timer = GLib.timeout_add(200, self._tick)

    def stop(self) -> None:
        self.stop_beacon()
        if self._timer:
            GLib.source_remove(self._timer)
            self._timer = 0
        if self.recorder.feed in self.station.sample_listeners:
            self.station.sample_listeners.remove(self.recorder.feed)

    # --- status ------------------------------------------------------------------------

    @property
    def band(self) -> bandplan.Band | None:
        st = self.station.radio
        return band_on_dial(st.frequency) if st.mode is Mode.DATA else None

    @property
    def listening(self) -> bool:
        return self.station.connected and self.band is not None and self.station.audio.rx

    @property
    def beacon_on(self) -> bool:
        return self.beacon_until is not None

    @property
    def busy(self) -> bool:
        return self.beacon_on or self.transmitting

    def dbm(self) -> int | None:
        p = self.station.radio.power_set
        return None if p is None else wspr.watts_to_dbm(p)

    def next_tx_slot(self, now: float | None = None) -> int | None:
        if not self.beacon_on:
            return None
        now = now or time.time()
        slot = wspr.slot_of(now) + 1
        for s in range(slot, slot + 60):
            if wspr.slot_of(self.beacon_until) < s:
                return None
            if self.scheduler.transmit_in(s):
                return s
        return None

    # --- beacon ------------------------------------------------------------------------

    def check_tx(self) -> bandplan.TxCheck:
        st = self.station.radio
        other = self.station.auto_keying(exclude=self)
        if other:
            return bandplan.TxCheck(False, other)
        if self.band is None:
            return bandplan.TxCheck(False, "Tune the radio to a WSPR frequency first. Tune Radio does this.")
        if st.data_submode is not DataSubmode.DATA_A:
            return bandplan.TxCheck(False, "Set the KX3's data submode to DATA A. Tune Radio does this.")
        dbm = self.dbm()
        if dbm is None:
            return bandplan.TxCheck(False, "Waiting for the radio's power setting.")
        try:
            wspr.channel_symbols(self.settings.callsign, self.settings.grid4, dbm)
        except ValueError as exc:
            return bandplan.TxCheck(False, str(exc))
        lo, hi = int(self.audio_hz - 4), int(self.audio_hz + 4)
        return self.station.can_transmit(Mode.DATA, lo, hi)

    def start_beacon(self, minutes: int = 60, percent: int | None = None) -> bandplan.TxCheck:
        check = self.check_tx()
        if not check.allowed:
            return check
        if percent is not None:
            self.set_percent(percent)
        self.beacon_until = time.time() + minutes * 60
        self.emit("changed")
        return check

    def set_percent(self, percent: int) -> None:
        self.percent = int(max(5, min(50, percent)))
        self.scheduler = wspr.TxScheduler(self.percent)
        self.emit("changed")

    def stop_beacon(self) -> None:
        was = self.busy
        self.beacon_until = None
        if self.transmitting:
            self.station.stop_data_tx()
            self.transmitting = False
            self.emit("transmitting", False)
        if was:
            self.emit("changed")

    # --- the tick ----------------------------------------------------------------------

    def _tick(self) -> bool:
        now = time.time()
        slot = wspr.slot_of(now)
        t_in = now - slot * wspr.PERIOD
        if self.beacon_on and now > self.beacon_until and not self.transmitting:
            self.beacon_until = None
            self.emit("event", "done", "The WSPR beacon finished.")
            self.emit("changed")
        if t_in >= DECODE_AT_S and self._last_decode_slot != slot:
            self._last_decode_slot = slot
            if self.listening and slot not in self._tx_slots and not self._decoding:
                self._start_decode(slot)
        self._maybe_transmit(now, slot, t_in)
        return GLib.SOURCE_CONTINUE

    def _maybe_transmit(self, now: float, slot: int, t_in: float) -> None:
        if not self.beacon_on or self.transmitting or slot in self._tx_slots:
            return
        if not (TX_WINDOW_S[0] <= t_in <= TX_WINDOW_S[1]) or not self.scheduler.transmit_in(slot):
            return
        if self.station.data_transmitting or self.station.link.tuning_pending:
            return
        check = self.check_tx()
        if not check.allowed:
            self.stop_beacon()
            self.emit("event", "blocked", f"WSPR beacon stopped: {check.reason}")
            return
        symbols = wspr.channel_symbols(self.settings.callsign, self.settings.grid4, self.dbm())
        wave = wspr.waveform(symbols, TX_RATE, self.audio_hz)
        audio_at = slot * wspr.PERIOD + wspr.TX_START_S
        lead = audio_at - now
        samples = np.concatenate([np.zeros(int(lead * TX_RATE), np.float32), wave]) if lead > 0 \
            else wave[int(-lead * TX_RATE):]
        self._tx_slots.add(slot)
        self._tx_slots = {s for s in self._tx_slots if s > slot - 5}
        result = self.station.play_data(samples, TX_RATE, on_done=self._tx_done,
                                        limit_s=len(samples) / TX_RATE + 3)
        if not result.allowed:
            if not result.retry:
                self.stop_beacon()
                self.emit("event", "blocked", f"WSPR beacon stopped: {result.reason}")
            else:
                self._tx_slots.discard(slot)
            return
        self.transmitting = True
        self.tx_count += 1
        self.emit("transmitting", True)
        self.emit("changed")

    def _tx_done(self, ok: bool = True) -> None:
        if not self.transmitting:
            return
        self.transmitting = False
        self.emit("transmitting", False)
        if not ok:
            self.beacon_until = None
            self.emit("event", "blocked", "The WSPR transmission did not finish, so the beacon stopped.")
        self.emit("changed")

    # --- receive -----------------------------------------------------------------------

    def _start_decode(self, slot: int) -> None:
        band = self.band
        dial = self.station.radio.frequency
        if not wsprd_available():
            if self.demo:
                GLib.idle_add(self._on_spots, slot, band.name if band else "", self._demo_spots(slot, dial))
            return
        samples, present = self.recorder.extract(slot * wspr.PERIOD, wspr.WAV_SECONDS)
        if present < 0.8:
            return
        self._decoding = True
        threading.Thread(target=self._decode_worker, args=(slot, band.name if band else "", dial, samples),
                         name="wsprd", daemon=True).start()

    def _decode_worker(self, slot: int, band: str, dial: int, samples: np.ndarray) -> None:
        spots: list[wspr.Spot] = []
        try:
            os.makedirs(self.workdir, exist_ok=True)
            path = os.path.join(self.workdir, wspr.wav_name(slot * wspr.PERIOD))
            wspr.write_wav(path, samples)
            try:
                out = subprocess.run([WSPRD, "-a", self.workdir, "-f", f"{dial / 1e6:.6f}", "-C", "500", "-o", "4",
                                      path], cwd=self.workdir, capture_output=True, text=True, timeout=90).stdout
            finally:
                try:
                    os.remove(path)
                except OSError:
                    pass
            spots = [s for s in (wspr.parse_wsprd_line(line) for line in out.splitlines()) if s]
        except Exception as exc:
            log.warning("wsprd failed: %s", exc)
        GLib.idle_add(self._on_spots, slot, band, spots)

    def _on_spots(self, slot: int, band: str, spots: list[wspr.Spot]) -> bool:
        self._decoding = False
        now = time.time()
        mine = self.settings.grid
        new = []
        for s in spots:
            if s.call and s.call == self.settings.callsign:
                continue
            km = grids.distance_km(mine, s.grid) if s.grid and mine else None
            bearing = grids.bearing_deg(mine, s.grid) if s.grid and mine else None
            new.append(Heard(now, band, s, km, bearing))
        self.heard = [h for h in self.heard if now - h.time < SPOT_HOURS * 3600] + new
        self.emit("spots", slot, new)
        if new and self.settings.wspr_upload and not self.demo:
            threading.Thread(target=self._upload, args=(slot, list(new), self.station.radio.frequency),
                             name="wsprnet", daemon=True).start()
        return False

    def summary(self, hours: float = 1.0) -> tuple[int, Heard | None]:
        """Stations heard in the last hours, and the farthest of them."""
        now = time.time()
        recent = [h for h in self.heard if now - h.time < hours * 3600]
        calls = {h.spot.call or h.spot.message for h in recent}
        far = max((h for h in recent if h.km is not None), key=lambda h: h.km, default=None)
        return len(calls), far

    # --- sharing spots (operator opt-in) ----------------------------------------------------

    def upload_fields(self, slot: int, heard: list[Heard], dial: int) -> list[dict[str, str]]:
        """One wsprnet form per spot, as WSJT-X builds them (Network/wsprnet.cpp:306-314)."""
        from .. import __version__

        when = time.gmtime(slot * wspr.PERIOD)
        out = []
        for h in heard:
            s = h.spot
            if not s.call:
                continue
            out.append({
                "function": "wspr", "rcall": self.settings.callsign, "rgrid": self.settings.grid4,
                "rqrg": f"{(dial + 1500) / 1e6:.6f}", "date": time.strftime("%y%m%d", when),
                "time": time.strftime("%H%M", when), "sig": str(s.snr), "dt": f"{s.dt:.1f}",
                "drift": str(s.drift), "tqrg": f"{s.freq_hz / 1e6:.6f}", "tcall": s.call,
                "tgrid": s.grid, "dbm": str(s.dbm if s.dbm is not None else ""),
                "version": f"KX3-Rig {__version__}", "mode": "2",
            })
        return out

    def _upload(self, slot: int, heard: list[Heard], dial: int) -> None:
        time.sleep(random.uniform(0, 20))       # WSJT-X spreads uploads over 0-20 s
        for fields in self.upload_fields(slot, heard, dial):
            try:
                data = urllib.parse.urlencode(fields).encode()
                req = urllib.request.Request(UPLOAD_URL, data=data,
                                             headers={"Content-Type": "application/x-www-form-urlencoded"})
                urllib.request.urlopen(req, timeout=15).read()
            except Exception as exc:
                log.info("wsprnet upload failed: %s", exc)
                return

    # --- demo ---------------------------------------------------------------------------

    def _demo_spots(self, slot: int, dial: int) -> list[wspr.Spot]:
        """Demo mode without wsprd: a believable handful of beacons."""
        rng = np.random.default_rng(slot)
        pool = [("K1JT", "FN20", 37), ("W7DEM", "CN85", 23), ("VE7QRP", "CN89", 30), ("JA1WSP", "PM95", 37),
                ("VK2LOOP", "QF56", 33), ("KH6BCN", "BL11", 30), ("N5ZZ", "EM12", 37), ("G4WSP", "IO91", 33),
                ("KL7NA", "BP51", 27), ("XE2WSP", "DL44", 30)]
        hhmm = time.strftime("%H%M", time.gmtime(slot * wspr.PERIOD))
        out = []
        for call, grid4, dbm in pool:
            if rng.random() < 0.45:
                hz = dial + 1500 + int(rng.uniform(-90, 90))
                snr = int(rng.uniform(-28, -8))
                out.append(wspr.Spot(hhmm, snr, float(rng.uniform(-1, 1)), hz, int(rng.integers(-1, 2)),
                                     f"{call} {grid4} {dbm}", call, grid4, dbm))
        return out
