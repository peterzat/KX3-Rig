"""FT8 engine: decode every period, run contacts, transmit on time, log.

Runs on the GLib main loop with a 100 ms tick. jt9 runs on a worker thread.

Timing (one 15 s period):
    0.0 s   period boundary (UTC)
    0.25 s  key the radio and start playback (audio lands at 0.5 s)
    13.4 s  snapshot the period's audio and start jt9 (about 1.5 s on this CPU)
    ~14.9 s decodes ready: the sequencer chooses the next message in time for
            the next period's 0.5 s start; if late, the start of the waveform
            is skipped (as WSJT-X does) up to MAX_LATE_S.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timezone

import gi
import numpy as np

gi.require_version("GLib", "2.0")
from gi.repository import GLib, GObject  # noqa: E402

from .. import bandplan, config  # noqa: E402
from ..cat import Mode  # noqa: E402
from . import adif, encode  # noqa: E402
from .decode import PERIOD, Jt9, SlotRecorder, slot_of, slot_start  # noqa: E402
from .messages import parse  # noqa: E402
from .sequencer import Decode, Sequencer, Stage  # noqa: E402

log = logging.getLogger(__name__)

DECODE_AT_S = 13.4
TX_RATE = 48_000
TX_START_S = 0.5
PTT_LEAD_S = 0.25         # key the radio this long before audio starts
OUTPUT_LATENCY_S = 0.08   # PipeWire stream start-up, compensated in the lead silence
MAX_LATE_S = 3.0
SIGNAL_WIDTH_HZ = 50
TUNE_SECONDS = 10.0
QSO_PROGRESS = {          # jt9 -Q: which a-priori decoding types to try
    Stage.CALLING_CQ: 0, Stage.ANSWERING: 1, Stage.REPORT: 2,
    Stage.ROGER_REPORT: 3, Stage.ROGERS: 4, Stage.SIGNOFF: 5,
}


class Ft8Engine(GObject.Object):
    __gtype_name__ = "KX3Ft8Engine"

    __gsignals__ = {
        "decoded": (GObject.SignalFlags.RUN_FIRST, None, (int, object)),
        "contact-changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "transmitting": (GObject.SignalFlags.RUN_FIRST, None, (bool, str)),
        "logged": (GObject.SignalFlags.RUN_FIRST, None, (object,)),
        "event": (GObject.SignalFlags.RUN_FIRST, None, (str, str)),
    }

    def __init__(self, station, demo: bool = False):
        super().__init__()
        self.station = station
        self.settings: config.Settings = station.settings
        self.demo = demo
        self.recorder = SlotRecorder()
        self.jt9 = Jt9(os.path.join(config.data_dir(), "jt9"))
        self.log_path = os.path.join(config.data_dir(), "kx3rig-log.adi")
        self.sequencer = Sequencer(self.settings.callsign, self.settings.grid4)
        self.decodes: dict[int, list[Decode]] = {}
        self.tx_offset = int(self.settings.ft8_tx_offset_hz)
        self.transmitting_text = ""
        self.tuning = False
        self.logged_count = adif.count(self.log_path)
        self._last_decode_slot = -1
        self._decoding_slot: int | None = None
        self._tx_slots: set[int] = set()
        self._wave_cache: dict[tuple[str, int], np.ndarray] = {}
        self._timer = 0
        self._decode_lock = threading.Lock()

    # --- lifecycle --------------------------------------------------------------------

    def start(self) -> None:
        self.station.sample_listeners.append(self.recorder.feed)
        self._timer = GLib.timeout_add(100, self._tick)

    def stop(self) -> None:
        self.halt()
        if self._timer:
            GLib.source_remove(self._timer)
            self._timer = 0
        if self.recorder.feed in self.station.sample_listeners:
            self.station.sample_listeners.remove(self.recorder.feed)

    # --- status -------------------------------------------------------------------------

    @property
    def listening(self) -> bool:
        """Decoding is useful only in DATA mode with receive audio flowing."""
        st = self.station.radio
        return self.station.connected and st.mode is Mode.DATA and self.station.audio.rx

    @property
    def busy(self) -> bool:
        return self.sequencer.active or self.tuning or bool(self.transmitting_text)

    def on_ft8_frequency(self) -> bandplan.Band | None:
        """The band whose FT8 dial the radio is on, if any."""
        st = self.station.radio
        band = bandplan.band_for(st.frequency)
        if band and abs(st.frequency - band.ft8) < 500 and st.mode is Mode.DATA:
            return band
        return None

    # --- operator actions -------------------------------------------------------------------

    def check_tx(self) -> bandplan.TxCheck:
        if not encode.available():
            return bandplan.TxCheck(False, "WSJT-X's ft8code isn't installed, so FT8 can't be encoded.")
        if self.station.radio.mode is not Mode.DATA:
            return bandplan.TxCheck(False, "Switch the radio to DATA mode to transmit FT8.")
        return self.station.can_transmit(Mode.DATA, self.tx_offset, self.tx_offset + SIGNAL_WIDTH_HZ)

    def answer(self, decode: Decode) -> bandplan.TxCheck:
        check = self.check_tx()
        if not check.allowed:
            return check
        self.sequencer = Sequencer(self.settings.callsign, self.settings.grid4)
        if not self.sequencer.answer(decode):
            return bandplan.TxCheck(False, "That message doesn't name a station to answer.")
        self._pick_clear_offset()
        self.emit("contact-changed")
        return check

    def call_cq(self) -> bandplan.TxCheck:
        check = self.check_tx()
        if not check.allowed:
            return check
        self.sequencer = Sequencer(self.settings.callsign, self.settings.grid4)
        now = time.time()
        upcoming = slot_of(now) + (1 if now - slot_start(slot_of(now)) > MAX_LATE_S else 0)
        self.sequencer.call_cq(tx_even=upcoming % 2 == 0)
        self._pick_clear_offset()
        self.emit("contact-changed")
        return check

    def halt(self) -> None:
        was_busy = self.busy
        self.sequencer.halt()
        self.tuning = False
        self.station.stop_data_tx()
        if self.transmitting_text:
            self.transmitting_text = ""
            self.emit("transmitting", False, "")
        if was_busy:
            self.emit("contact-changed")

    def set_tx_offset(self, hz: float) -> None:
        self.tx_offset = int(max(200, min(2900, round(hz))))
        self.settings.ft8_tx_offset_hz = self.tx_offset
        self.emit("contact-changed")

    def tune(self) -> bandplan.TxCheck:
        """Transmit a steady tone (up to 10 s) to check SWR and set levels."""
        if self.busy:
            return bandplan.TxCheck(False, "Already transmitting.")
        check = self.check_tx()
        if not check.allowed:
            return check
        tone = encode.tune_tone(TUNE_SECONDS, TX_RATE, self.tx_offset + 25)
        self.tuning = True
        result = self.station.play_data(tone, TX_RATE, on_done=self._tune_done, limit_s=TUNE_SECONDS + 1)
        if not result.allowed:
            self.tuning = False
            return result
        self.transmitting_text = "Tune"
        self.emit("transmitting", True, "Tune")
        return result

    def _tune_done(self) -> None:
        self.tuning = False
        self.transmitting_text = ""
        self.emit("transmitting", False, "")

    def _pick_clear_offset(self) -> None:
        """Keep our TX offset unless someone is on it; then move to the nearest gap."""
        recent = [d for slot in sorted(self.decodes)[-4:] for d in self.decodes[slot]]
        busy = [(d.freq - 10, d.freq + SIGNAL_WIDTH_HZ + 10) for d in recent]

        def clear(f: int) -> bool:
            return all(f + SIGNAL_WIDTH_HZ < lo or f > hi for lo, hi in busy)

        if clear(self.tx_offset):
            return
        for delta in range(10, 1300, 10):
            for f in (self.tx_offset + delta, self.tx_offset - delta):
                if 300 <= f <= 2700 and clear(f):
                    self.set_tx_offset(f)
                    return

    # --- the tick ------------------------------------------------------------------------------

    def _tick(self) -> bool:
        now = time.time()
        slot = slot_of(now)
        t_in = now - slot_start(slot)
        if t_in >= DECODE_AT_S and self._last_decode_slot != slot:
            self._last_decode_slot = slot
            if self.listening and slot not in self._tx_slots and self._decoding_slot is None:
                self._start_decode(slot)
        self._maybe_transmit(now)
        return GLib.SOURCE_CONTINUE

    def _start_decode(self, slot: int) -> None:
        if not Jt9.available():
            return
        samples, present = self.recorder.extract(slot_start(slot), PERIOD)
        if present < 0.6:
            return
        seq = self.sequencer
        c = seq.contact
        kwargs = dict(
            dx_call=c.call if c else "",
            dx_grid=c.grid if c else "",
            rx_freq=c.their_freq if c and c.their_freq else self.tx_offset,
            qso_progress=QSO_PROGRESS.get(seq.stage, 0),
        )
        self._decoding_slot = slot
        my_call = self.settings.callsign
        threading.Thread(target=self._decode_worker, args=(slot, samples, my_call, kwargs),
                         name="jt9", daemon=True).start()

    def _decode_worker(self, slot, samples, my_call, kwargs) -> None:
        try:
            raw = self.jt9.decode(samples, slot_start(slot), my_call, **kwargs)
        except Exception as exc:
            log.warning("jt9 failed: %s", exc)
            raw = []
        GLib.idle_add(self._on_decoded, slot, raw)

    def _on_decoded(self, slot: int, raw) -> bool:
        self._decoding_slot = None
        decodes = [Decode(slot=slot, snr=r.snr, dt=r.dt, freq=r.freq, text=r.message,
                          message=parse(r.message), low_confidence=r.low_confidence) for r in raw]
        decodes.sort(key=lambda d: d.freq)
        self.decodes[slot] = decodes
        for old in [s for s in self.decodes if s < slot - 40]:
            del self.decodes[old]
        self.emit("decoded", slot, decodes)
        seq = self.sequencer
        if seq.active and (slot % 2 == 0) != seq.tx_even:
            before = (seq.stage, seq.contact.call if seq.contact else "")
            seq.on_decodes([d for d in decodes if not d.low_confidence])
            if seq.stage is Stage.DONE:
                self._finish_contact()
            if (seq.stage, seq.contact.call if seq.contact else "") != before:
                self.emit("contact-changed")
        return False

    # --- transmit ----------------------------------------------------------------------------------

    def _maybe_transmit(self, now: float) -> None:
        seq = self.sequencer
        if not seq.active or self.transmitting_text or self.station.data_transmitting:
            return
        slot = slot_of(now)
        t_in = now - slot_start(slot)
        if (slot % 2 == 0) != seq.tx_even or slot in self._tx_slots:
            return
        if t_in < TX_START_S - PTT_LEAD_S or t_in > MAX_LATE_S:
            return
        if self._decoding_slot == slot - 1:
            return  # the reply depends on what was just heard; wait for jt9
        text = seq.next_message()
        if not text:
            return
        check = self.check_tx()
        if not check.allowed:
            self.halt()
            self.emit("event", "blocked", check.reason)
            return
        try:
            wave = self._wave(text)
        except encode.EncodeError as exc:
            self.halt()
            self.emit("event", "error", str(exc))
            return
        audio_at = slot_start(slot) + TX_START_S
        lead = audio_at - now - OUTPUT_LATENCY_S
        if lead >= 0:
            samples = np.concatenate([np.zeros(int(lead * TX_RATE), np.float32), wave])
        else:
            samples = wave[int(-lead * TX_RATE):]   # late: skip what has already elapsed
        self._tx_slots.add(slot)
        self._tx_slots = {s for s in self._tx_slots if s > slot - 10}
        result = self.station.play_data(samples, TX_RATE, on_done=lambda: self._tx_done(slot, text),
                                        limit_s=PERIOD)
        if not result.allowed:
            self.halt()
            self.emit("event", "blocked", result.reason)
            return
        if self.demo:
            from .. import ft8 as pkg
            pkg.demo_last_tx, pkg.demo_last_tx_slot = text, slot
        self.transmitting_text = text
        self.emit("transmitting", True, text)

    def _wave(self, text: str) -> np.ndarray:
        key = (text, self.tx_offset)
        if key not in self._wave_cache:
            if len(self._wave_cache) > 16:
                self._wave_cache.clear()
            tones = encode.encode(text).tones
            self._wave_cache[key] = encode.waveform(tones, TX_RATE, self.tx_offset)
        return self._wave_cache[key]

    def _tx_done(self, slot: int, text: str) -> None:
        if not self.transmitting_text:
            return  # halted
        self.transmitting_text = ""
        self.emit("transmitting", False, "")
        seq = self.sequencer
        if not seq.active:
            return
        if seq.sent(text, datetime.now(timezone.utc)):
            self._log_contact()
        if seq.stage is Stage.DONE:
            self._finish_contact()
        elif seq.should_give_up():
            who = seq.contact.call if seq.contact else "anyone"
            seq.halt()
            self.emit("event", "gave-up", f"No answer from {who}. Stopped transmitting.")
        self.emit("contact-changed")

    def _log_contact(self) -> None:
        c = self.sequencer.contact
        if c is None:
            return
        st = self.station.radio
        band = bandplan.band_for(st.frequency)
        entry = adif.LogEntry(
            call=c.call, grid=c.grid, rst_sent=c.report_sent, rst_rcvd=c.report_rcvd,
            time_on=c.time_on or datetime.now(timezone.utc), time_off=c.time_off or datetime.now(timezone.utc),
            band=band.name if band else "", dial_hz=st.frequency, station_call=self.settings.callsign,
            my_grid=self.settings.grid, tx_power_w=st.power_set,
        )
        try:
            adif.append(self.log_path, entry)
        except OSError as exc:
            self.emit("event", "error", f"Could not write the log: {exc}")
            return
        self.logged_count += 1
        self.emit("logged", entry)

    def _finish_contact(self) -> None:
        c = self.sequencer.contact
        if c is not None:
            self.emit("event", "done", f"Contact with {c.call} complete")
