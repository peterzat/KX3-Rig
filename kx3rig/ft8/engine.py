"""FT8 engine: decode every period, run contacts, transmit on time, log.

Runs on the GLib main loop with a 100 ms tick. jt9 runs on a worker thread.

Timing (one 15 s period):
    0.0 s   period boundary (UTC)
    0.25 s  key the radio and start playback (audio lands at 0.5 s)
    13.4 s  snapshot the period's audio and start jt9 (about 1.5 s on this CPU)
    ~14.9 s decodes ready: the sequencer chooses the next message in time for
            the next period's 0.5 s start; if late, the start of the waveform
            is skipped (as WSJT-X does) up to the protocol's max_late_s.

FT4 (protocol.py) runs through the same engine with 7.5 s periods.
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
from ..cat import DataSubmode, Mode  # noqa: E402
from . import adif, encode  # noqa: E402
from .decode import Jt9, SlotRecorder, slot_of, slot_start  # noqa: E402,F401  (FT8 slots, for tests)
from .messages import parse  # noqa: E402
from .protocol import FT8, PROTOCOLS, Protocol  # noqa: E402
from .sequencer import Decode, Sequencer, Stage  # noqa: E402

log = logging.getLogger(__name__)

TX_RATE = 48_000
TX_START_S = FT8.tx_start_s
PTT_LEAD_S = 0.25         # key the radio this long before audio starts
OUTPUT_LATENCY_S = 0.04   # PipeWire stream start-up (measured ~10 ms), compensated in the lead silence
TUNE_SECONDS = 10.0
REFUSAL_LIMIT = 10        # ticks (100 ms each) of refused key-down before a contact stops
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
        self.proto: Protocol = PROTOCOLS.get(getattr(self.settings, "digital_mode", "FT8"), FT8)
        self.recorder = SlotRecorder()
        self.jt9 = Jt9(os.path.join(config.data_dir(), "jt9"))
        # Demo contacts are simulated: keep them out of the real logbook.
        self.log_path = os.path.join(config.data_dir(), "kx3rig-demo-log.adi" if demo else "kx3rig-log.adi")
        self.sequencer = Sequencer(self.settings.callsign, self.settings.grid4)
        self.decodes: dict[int, list[Decode]] = {}
        self.tx_offset = int(self.settings.ft8_tx_offset_hz)
        self.transmitting_text = ""
        self.tuning = False
        self.logged_count = adif.count(self.log_path)
        self.worked: set[tuple[str, str]] = adif.worked(self.log_path)
        self.grids: dict[str, str] = {}        # call -> last grid heard, for distance on every line
        self._last_decode_slot = -1
        self._decoding_slot: int | None = None
        self._tx_slots: set[int] = set()
        self._wave_cache: dict[tuple[str, int], np.ndarray] = {}
        self._timer = 0
        self._decode_lock = threading.Lock()
        self._refusals = 0
        self._refusal_slot: int | None = None
        register = getattr(station, "register_keyer", None)   # absent on test stand-ins
        if register is not None:
            register(self, lambda: f"Finish the {self.proto.name} contact first." if self.busy else "")

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
        """The band whose FT8 (or FT4) dial the radio is on, if any."""
        st = self.station.radio
        if st.mode is not Mode.DATA:
            return None
        return self.proto.band_on_dial(st.frequency)

    def set_protocol(self, name: str) -> bool:
        """Switch between FT8 and FT4. Refused while a contact or tune is in progress."""
        proto = PROTOCOLS.get(name)
        if proto is None or self.busy:
            return False
        if proto is not self.proto:
            self.proto = proto
            self.settings.digital_mode = name
            self.decodes.clear()
            self._wave_cache.clear()
            self._last_decode_slot = -1
            self.sequencer = Sequencer(self.settings.callsign, self.settings.grid4)
            self.emit("contact-changed")
        return True

    @property
    def period(self) -> float:
        return self.proto.period

    # --- operator actions -------------------------------------------------------------------

    def check_tx(self) -> bandplan.TxCheck:
        other = self.station.auto_keying(exclude=self)
        if other:
            return bandplan.TxCheck(False, other)
        if not encode.available():
            return bandplan.TxCheck(False, "WSJT-X's ft8code isn't installed, so FT8 can't be encoded.")
        if self.station.radio.mode is not Mode.DATA:
            return bandplan.TxCheck(False, "Switch the radio to DATA mode to transmit FT8.")
        sub = self.station.radio.data_submode
        if sub is None:
            return bandplan.TxCheck(False, "Waiting for the radio's data submode.")
        if sub is not DataSubmode.DATA_A:
            # Other submodes change sideband and audio handling (KX3 Owner's Manual p.18).
            return bandplan.TxCheck(False, "Set the KX3's data submode to DATA A. Tune Radio to FT8 does this.")
        return self.station.can_transmit(Mode.DATA, self.tx_offset, self.tx_offset + self.proto.signal_width_hz)

    def answer(self, decode: Decode) -> bandplan.TxCheck:
        check = self.check_tx()
        if not check.allowed:
            return check
        self.sequencer = Sequencer(self.settings.callsign, self.settings.grid4)
        self._refusals = 0
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
        self._refusals = 0
        now = time.time()
        p = self.proto
        upcoming = p.slot_of(now) + (1 if now - p.slot_start(p.slot_of(now)) > p.max_late_s else 0)
        self.sequencer.call_cq(tx_even=upcoming % 2 == 0)
        self._pick_clear_offset()
        self.emit("contact-changed")
        return check

    def halt(self) -> None:
        was_busy = self.busy
        self._refusals = 0
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

    def _tune_done(self, ok: bool = True) -> None:
        self.tuning = False
        self.transmitting_text = ""
        self.emit("transmitting", False, "")

    def _pick_clear_offset(self) -> None:
        """Keep our TX offset unless someone is on it; then move to the nearest gap."""
        recent = [d for slot in sorted(self.decodes)[-4:] for d in self.decodes[slot]]
        width = self.proto.signal_width_hz
        busy = [(d.freq - 10, d.freq + width + 10) for d in recent]

        def clear(f: int) -> bool:
            return all(f + width < lo or f > hi for lo, hi in busy)

        if clear(self.tx_offset):
            return
        for delta in range(10, 1300, 10):
            for f in (self.tx_offset + delta, self.tx_offset - delta):
                if 300 <= f <= 2700 and clear(f):
                    self.set_tx_offset(f)
                    return

    # --- the tick ------------------------------------------------------------------------------

    def _tick(self) -> bool:
        if self.sequencer.active and not self.station.connected:
            self.halt()
            self.emit("event", "blocked", "Contact stopped: the radio disconnected.")
        now = time.time()
        p = self.proto
        slot = p.slot_of(now)
        t_in = now - p.slot_start(slot)
        seq = self.sequencer
        if seq.wait_expired(slot):
            who = seq.contact.call if seq.contact else "anyone"
            seq.halt()
            self.emit("event", "gave-up", f"{who} didn't come back. Stopped waiting.")
            self.emit("contact-changed")
        if t_in >= p.decode_at_s and self._last_decode_slot != slot:
            self._last_decode_slot = slot
            if self.listening and slot not in self._tx_slots and self._decoding_slot is None:
                self._start_decode(slot)
        self._maybe_transmit(now)
        return GLib.SOURCE_CONTINUE

    def _start_decode(self, slot: int) -> None:
        if not Jt9.available():
            if self.demo:
                self._demo_decode(slot)
            return
        p = self.proto
        samples, present = self.recorder.extract(p.slot_start(slot), p.decode_seconds)
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
        kwargs["proto"] = p
        threading.Thread(target=self._decode_worker, args=(slot, samples, my_call, kwargs),
                         name="jt9", daemon=True).start()

    def _demo_decode(self, slot: int) -> None:
        """Demo mode without WSJT-X (for example on a Mac): report the simulated
        band's messages as if jt9 had decoded them, so the view can be reviewed."""
        from .. import ft8 as pkg
        from .decode import RawDecode

        raw = [RawDecode("000000", int(round(snr)), 0.1, int(round(freq)), text, False, "")
               for text, freq, snr in pkg.demo_messages(slot)]
        GLib.idle_add(self._on_decoded, slot, raw, self.proto)

    def _decode_worker(self, slot, samples, my_call, kwargs) -> None:
        try:
            p = kwargs.pop("proto")
            raw = self.jt9.decode(samples, p.slot_start(slot), my_call, flag=p.jt9_flag, parse=p.parse,
                                  **kwargs)
        except Exception as exc:
            log.warning("jt9 failed: %s", exc)
            raw = []
        GLib.idle_add(self._on_decoded, slot, raw, p)

    def _on_decoded(self, slot: int, raw, proto: Protocol | None = None) -> bool:
        self._decoding_slot = None
        if proto is not None and proto is not self.proto:
            return False   # decoded under the other protocol: the slots no longer line up
        decodes = [Decode(slot=slot, snr=r.snr, dt=r.dt, freq=r.freq, text=r.message,
                          message=parse(r.message), low_confidence=r.low_confidence) for r in raw]
        decodes.sort(key=lambda d: d.freq)
        for d in decodes:
            if d.message.grid and d.message.de and not d.low_confidence:
                self.grids[d.message.de.strip("<>")] = d.message.grid
        if len(self.grids) > 2000:
            self.grids = dict(list(self.grids.items())[-1000:])
        self.decodes[slot] = decodes
        for old in [s for s in self.decodes if s < slot - 40]:
            del self.decodes[old]
        self.emit("decoded", slot, decodes)
        seq = self.sequencer
        if seq.waiting:
            # Waiting for a faded station: listen in both periods.
            who = seq.contact.call if seq.contact else ""
            how = seq.on_waiting_decodes([d for d in decodes if not d.low_confidence])
            if how:
                self.emit("event", "resumed", f"{who} is back. Resuming the contact."
                          if how == "reply" else f"{who} is calling again. Answering.")
                self.emit("contact-changed")
            return False
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
        p = self.proto
        slot = p.slot_of(now)
        t_in = now - p.slot_start(slot)
        if (slot % 2 == 0) != seq.tx_even or slot in self._tx_slots:
            return
        if t_in < p.tx_start_s - PTT_LEAD_S or t_in > p.max_late_s:
            return
        if self._decoding_slot == slot - 1:
            return  # the reply depends on what was just heard; wait for jt9
        if self.station.link.tuning_pending:
            return  # a frequency or mode change is still reaching the radio; retry next tick
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
        audio_at = p.slot_start(slot) + p.tx_start_s
        lead = audio_at - now - OUTPUT_LATENCY_S
        if lead >= 0:
            samples = np.concatenate([np.zeros(int(lead * TX_RATE), np.float32), wave])
        else:
            samples = wave[int(-lead * TX_RATE):]   # late: skip what has already elapsed
        self._tx_slots.add(slot)
        self._tx_slots = {s for s in self._tx_slots if s > slot - 10}
        result = self.station.play_data(samples, TX_RATE, on_done=lambda ok, s=seq, t=text: self._tx_done(s, t, ok),
                                        limit_s=p.period)
        if not result.allowed:
            if not result.retry:
                # Not transient (for example the audio failed after keying): stop now.
                self.halt()
                self.emit("event", "blocked", result.reason)
                return
            # Refused before keying (a tune still settling): retry on the next ticks,
            # and give up only if it keeps refusing for about a second.
            self._tx_slots.discard(slot)
            if self._refusal_slot != slot:
                self._refusal_slot, self._refusals = slot, 0   # count per transmit slot
            self._refusals += 1
            if self._refusals >= REFUSAL_LIMIT:
                self.halt()
                self.emit("event", "blocked", result.reason)
            return
        self._refusals = 0
        if self.demo:
            from .. import ft8 as pkg
            pkg.demo_last_tx, pkg.demo_last_tx_slot = text, slot
        self.transmitting_text = text
        self.emit("transmitting", True, text)

    def _wave(self, text: str) -> np.ndarray:
        key = (self.proto.name, text, self.tx_offset)
        if key not in self._wave_cache:
            if len(self._wave_cache) > 16:
                self._wave_cache.clear()
            tones = self.proto.tones(text)
            self._wave_cache[key] = self.proto.waveform(tones, TX_RATE, self.tx_offset)
        return self._wave_cache[key]

    def _tx_done(self, seq: Sequencer, text: str, ok: bool = True) -> None:
        if not self.transmitting_text:
            return  # halted
        self.transmitting_text = ""
        self.emit("transmitting", False, "")
        if seq is not self.sequencer:
            return  # the operator started a new contact while this one was sending
        if not seq.active:
            return
        if not ok:
            # The audio never fully went out: do not count it as sent.
            seq.halt()
            self.emit("contact-changed")
            return
        if seq.sent(text, datetime.now(timezone.utc)):
            self._log_contact()
        if seq.stage is Stage.DONE:
            self._finish_contact()
        elif seq.should_give_up():
            who = seq.contact.call if seq.contact else "anyone"
            if seq.can_wait():
                seq.start_waiting(self.proto.slot_of(time.time()))
                self.emit("event", "waiting", f"No answer from {who}. Waiting in case they come back.")
            else:
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
            mode=self.proto.adif_mode, submode=self.proto.adif_submode,
        )
        try:
            adif.append(self.log_path, entry)
        except OSError as exc:
            self.emit("event", "error", f"Could not write the log: {exc}")
            return
        self.logged_count += 1
        self.worked.add((entry.call.upper(), entry.band))
        self.emit("logged", entry)

    def _finish_contact(self) -> None:
        c = self.sequencer.contact
        if c is not None:
            self.emit("event", "done", f"Contact with {c.call} complete")
