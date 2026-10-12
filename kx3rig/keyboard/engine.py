"""Keyboard modes: PSK31 and CW, typed and read on the computer.

Both are done in software, not with the KX3's built-in text modes, for control:
the waterfall picks the signal, several PSK31 signals are read at once, and the
transcript is on a full screen instead of the radio's display. Both run in DATA
A (upper sideband), so the radio never switches mode between receive and
transmit:

- PSK31 is sent as audio, as every sound-card program does (emission J2B).
- CW is sent as a keyed, shaped audio tone (emission J2A). 47 CFR 97.3(c)(1)
  counts J2A as CW, so it is checked against CW privileges. The other two ways
  were ruled out: ACC1 carries no RTS or DTR to key with (KX3 Owner's Manual
  p.5), and the KY text-keying command is refused by the CAT allow-list on
  purpose.

A message is composed first and sent as one transmission, with the same
transmit policy as FT8: can_transmit(), a time limit, and Stop or Esc.
Receive runs only while the Keyboard view is open (start/stop).
"""

from __future__ import annotations

import os
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

import gi
import numpy as np

gi.require_version("GLib", "2.0")
from gi.repository import GLib, GObject  # noqa: E402

from .. import bandplan, config  # noqa: E402
from ..bandplan import CW as CW_KIND  # noqa: E402
from ..cat import DataSubmode, Mode  # noqa: E402
from . import cw, psk31  # noqa: E402

PSK31, CW = "psk31", "cw"
TX_RATE = 48_000
MAX_TX_S = 110.0            # one message; under the radio link's two-minute voice limit
PSK_OFFSET_HZ = 1000.0      # fldigi's default audio offset for PSK31 dial frequencies
CW_OFFSET_HZ = 700.0        # our CW tone; also where receive listens until moved
WIDTH_HZ = {PSK31: 60, CW: 100}

# PSK31 dial frequencies (USB, signals about 1 kHz above), from fldigi's default
# list (src/rigcontrol/rigsupport.cxx); the KX3 Owner's Manual p.18 also suggests
# 14070-14073 kHz. fldigi's 17 m (18.100) and 12 m (24.920) dials are left out: a
# signal 1 kHz up lands inside the FT8 (18.100) and FT4 (24.919) windows there.
PSK_DIALS = {
    "160m": 1_807_000, "80m": 3_580_000, "40m": 7_070_000, "30m": 10_135_000,
    "20m": 14_070_000, "15m": 21_070_000, "10m": 28_120_000,
}


def cw_dial(band: bandplan.Band) -> int | None:
    """The dial that puts our tone on the band's QRP CW calling frequency."""
    spot = next((h for h in bandplan.hot_spots(band) if h.kind == "cw"), None)
    return None if spot is None else int(spot.hz - CW_OFFSET_HZ)


def dial_for(mode: str, band: bandplan.Band) -> int | None:
    return PSK_DIALS.get(band.name) if mode == PSK31 else cw_dial(band)


MACROS = {
    PSK31: [
        ("CQ", "CQ CQ CQ de {me} {me} {me} pse k"),
        ("Answer", "{call} de {me} {me} k"),
        ("Report", "{call} de {me} - Thanks for the call. Your RST is 599. QTH grid {grid}. "
                   "Name {name}. How copy? {call} de {me} k"),
        ("73", "{call} de {me} - Thanks for the contact. 73! {call} de {me} sk"),
    ],
    CW: [
        ("CQ", "CQ CQ CQ DE {me} {me} K"),
        ("Answer", "{call} DE {me} {me} K"),
        ("Report", "{call} DE {me} TU UR RST 599 599 QTH {grid} NAME {name} HW? {call} DE {me} KN"),
        ("73", "{call} DE {me} TU 73 <SK>"),
    ],
}

_DE_RE = re.compile(r"\b(?:DE|de)\s+([A-Z0-9]{1,3}[0-9][A-Z0-9]{0,4}[A-Z](?:/[A-Z0-9]{1,4})?)\b", re.I)


def heard_call(text: str, my_call: str = "") -> str:
    """The last callsign that followed "de" in received text, other than ours."""
    calls = [m.group(1).upper() for m in _DE_RE.finditer(text)]
    calls = [c for c in calls if c != my_call.upper()]
    return calls[-1] if calls else ""


def expand(template: str, me: str, call: str, grid: str, name: str) -> str:
    out = template.format(me=me or "N0CALL", call=call or "QRZ?", grid=grid[:4] or "", name=name or "")
    return " ".join(out.split())


@dataclass
class Line:
    """One run of text in the transcript."""

    ours: bool
    text: str = ""
    started: float = field(default_factory=time.time)


class KeyboardEngine(GObject.Object):
    __gtype_name__ = "KX3KeyboardEngine"

    __gsignals__ = {
        # New characters from the focused signal.
        "received": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        # The PSK31 signal browser changed (list of psk31 channels).
        "channels": (GObject.SignalFlags.RUN_FIRST, None, (object,)),
        # (on, text): a transmission started or ended.
        "sending": (GObject.SignalFlags.RUN_FIRST, None, (bool, str)),
        # Characters of our transmission as they go out, for the transcript.
        "sent-text": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        "changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "event": (GObject.SignalFlags.RUN_FIRST, None, (str, str)),
    }

    def __init__(self, station, demo: bool = False):
        super().__init__()
        self.station = station
        self.settings: config.Settings = station.settings
        # The same logbook as FT8 (demo contacts stay out of the real one).
        self.log_path = os.path.join(config.data_dir(), "kx3rig-demo-log.adi" if demo else "kx3rig-log.adi")
        self.their_call = ""
        self.their_name = ""
        self.time_on: datetime | None = None
        self.mode = PSK31
        self.offset_hz = PSK_OFFSET_HZ
        self.wpm = 18
        self.running = False
        self.last_received = 0.0
        self.sending_text = ""
        self.lines: list[Line] = []
        self._lock = threading.Lock()
        self._psk = psk31.Decoder(freq=self.offset_hz)
        self._browser = psk31.Browser()
        self._cw = cw.Decoder(freq=CW_OFFSET_HZ, wpm=self.wpm)
        self._pending = ""
        self._channels_dirty = False
        self._timer = 0
        self._progress: list[tuple[str, float]] = []
        self._progress_i = 0
        self._tx_started = 0.0
        self._send_timer = 0
        self._recent: list[np.ndarray] = []     # the last few seconds, for finding a CW tone
        self._recent_n = 0
        station.register_keyer(self, lambda: "Wait for the message to finish, or press Stop." if self.busy else "")

    # --- lifecycle -------------------------------------------------------------------

    def start(self) -> None:
        if self.running:
            return
        self.running = True
        self.station.sample_listeners.append(self._feed)
        self._timer = GLib.timeout_add(150, self._drain)

    def stop(self) -> None:
        if not self.running:
            return
        self.running = False
        if self._feed in self.station.sample_listeners:
            self.station.sample_listeners.remove(self._feed)
        if self._timer:
            GLib.source_remove(self._timer)
            self._timer = 0

    # --- settings ---------------------------------------------------------------------

    def set_mode(self, mode: str) -> None:
        if mode == self.mode or self.busy:
            return
        self.mode = mode
        self.set_offset(PSK_OFFSET_HZ if mode == PSK31 else CW_OFFSET_HZ)
        self.emit("changed")

    def set_offset(self, hz: float) -> None:
        """Where we listen and transmit (audio Hz above the dial)."""
        self.offset_hz = float(max(300.0, min(2700.0, hz)))
        with self._lock:
            self._psk.set_freq(self.offset_hz)
            self._cw.set_freq(self.offset_hz)
        self.emit("changed")

    def set_wpm(self, wpm: int) -> None:
        self.wpm = int(max(8, min(40, wpm)))
        self.emit("changed")

    @property
    def tracked_hz(self) -> float:
        """The receive frequency after PSK31's AFC."""
        return self._psk.freq if self.mode == PSK31 else self.offset_hz

    @property
    def channels(self) -> list:
        return list(self._browser.channels) if self.mode == PSK31 else []

    @property
    def cw_wpm(self) -> float:
        return self._cw.wpm

    @property
    def signal_active(self) -> bool:
        return self._psk.active if self.mode == PSK31 else self._cw.active

    # --- receive ----------------------------------------------------------------------

    def _feed(self, samples: np.ndarray, end_time: float) -> None:
        """Audio thread. Nothing is decoded while we transmit (the KX3's monitor audio)."""
        if self.station.radio.ptt or self.station.radio.transmitting:
            return
        with self._lock:
            self._recent.append(samples)
            self._recent_n += len(samples)
            while self._recent_n - len(self._recent[0]) > 4 * 12_000:
                self._recent_n -= len(self._recent.pop(0))
            if self.mode == PSK31:
                text = self._psk.feed(samples)
                if self._browser.feed(samples, now=end_time):
                    self._channels_dirty = True
            else:
                text = self._cw.feed(samples)
            if text:
                self._pending += text

    def _drain(self) -> bool:
        with self._lock:
            text, self._pending = self._pending, ""
            dirty, self._channels_dirty = self._channels_dirty, False
        if text:
            self.last_received = time.monotonic()
            self._append(False, text)
            self.emit("received", text)
        if dirty:
            self.emit("channels", self.channels)
        return GLib.SOURCE_CONTINUE

    def _append(self, ours: bool, text: str) -> None:
        if not self.lines or self.lines[-1].ours != ours:
            self.lines.append(Line(ours))
            del self.lines[:-200]
        self.lines[-1].text += text

    def received_text(self, chars: int = 600) -> str:
        return "".join(line.text for line in self.lines if not line.ours)[-chars:]

    def suggested_call(self) -> str:
        return heard_call(self.received_text(), self.settings.callsign)

    def clear(self) -> None:
        self.lines = []
        self.emit("changed")

    # --- transmit ---------------------------------------------------------------------

    @property
    def busy(self) -> bool:
        return bool(self.sending_text)

    def _audio_span(self) -> tuple[int, int]:
        half = WIDTH_HZ[self.mode] // 2
        return int(self.offset_hz - half), int(self.offset_hz + half)

    def check_tx(self, text: str = "x") -> bandplan.TxCheck:
        other = self.station.auto_keying(exclude=self)
        if other:
            return bandplan.TxCheck(False, other)
        radio = self.station.radio
        if radio.mode is not Mode.DATA:
            return bandplan.TxCheck(False, "Switch the radio to DATA mode. Tune Radio does this.")
        if radio.data_submode is None:
            return bandplan.TxCheck(False, "Waiting for the radio's data submode.")
        if radio.data_submode is not DataSubmode.DATA_A:
            return bandplan.TxCheck(False, "Set the KX3's data submode to DATA A. Tune Radio does this.")
        if not self._normalize(text):
            return bandplan.TxCheck(False, "Type something to send.")
        if self.duration_s(text) > MAX_TX_S:
            return bandplan.TxCheck(False, "That message is too long for one transmission. Send it in parts.")
        lo, hi = self._audio_span()
        return self.station.can_transmit(Mode.DATA, lo, hi, kind=CW_KIND if self.mode == CW else None)

    def _normalize(self, text: str) -> str:
        text = " ".join(text.split())
        return cw.normalize(text).strip() if self.mode == CW else text

    def duration_s(self, text: str) -> float:
        text = self._normalize(text)
        if self.mode == CW:
            return cw.duration_s(text, self.wpm)
        return psk31.duration_s(text + " ")

    def send(self, text: str) -> bandplan.TxCheck:
        """Transmit one composed message."""
        if self.busy:
            return bandplan.TxCheck(False, "Already sending.")
        check = self.check_tx(text)
        if not check.allowed:
            return check
        text = self._normalize(text)
        if self.mode == CW:
            wave = cw.modulate(text, self.wpm, TX_RATE, self.offset_hz)
            progress = cw.char_times(text, self.wpm)
        else:
            # A leading and trailing space keep the first and last words apart from
            # whatever the other station's decoder printed before.
            line = " " + text + " "
            wave = psk31.modulate(line, TX_RATE, self.offset_hz)
            progress = psk31.char_times(line)
        result = self.station.play_data(wave, TX_RATE, on_done=self._sent, limit_s=len(wave) / TX_RATE + 2)
        if not result.allowed:
            return result
        self.sending_text = text
        self._progress, self._progress_i = progress, 0
        self._tx_started = time.monotonic()
        self._append(True, "")
        self._send_timer = GLib.timeout_add(50, self._send_progress)
        self.emit("sending", True, text)
        return result

    def _send_progress(self) -> bool:
        if not self.sending_text:
            self._send_timer = 0
            return False
        elapsed = time.monotonic() - self._tx_started
        out = ""
        while self._progress_i < len(self._progress) and self._progress[self._progress_i][1] <= elapsed:
            out += self._progress[self._progress_i][0]
            self._progress_i += 1
        if out:
            self._append(True, out)
            self.emit("sent-text", out)
        return True

    def _finish_progress(self, complete: bool) -> None:
        if self._send_timer:
            GLib.source_remove(self._send_timer)
            self._send_timer = 0
        if complete:
            rest = "".join(c for c, _ in self._progress[self._progress_i:])
            if rest:
                self._append(True, rest)
                self.emit("sent-text", rest)
        self._append(True, "\n")
        self._progress, self._progress_i = [], 0

    def _sent(self, ok: bool = True) -> None:
        if not self.sending_text:
            return
        self._finish_progress(ok)
        self.sending_text = ""
        self.emit("sending", False, "")
        if not ok:
            self.emit("event", "error", "The transmission did not finish.")

    def halt(self) -> None:
        if not self.sending_text:
            return
        self.station.stop_data_tx()
        self._finish_progress(False)
        self.sending_text = ""
        self.emit("sending", False, "")

    # --- the contact ------------------------------------------------------------------

    def set_their_call(self, call: str) -> None:
        call = call.strip().upper()
        if call != self.their_call:
            self.their_call = call
            self.time_on = datetime.now(timezone.utc) if call else None
            self.emit("changed")

    def macro(self, template: str) -> str:
        return expand(template, self.settings.callsign, self.their_call, self.settings.grid,
                      getattr(self.settings, "operator_name", ""))

    def log_contact(self, rst_sent: str = "599", rst_rcvd: str = "599", name: str = "",
                    comment: str = ""):
        """Append the contact to the ADIF log; returns the entry (or raises OSError)."""
        from ..ft8 import adif

        if not self.their_call:
            raise ValueError("Enter the other station's callsign first.")
        st = self.station.radio
        band = bandplan.band_for(st.frequency)
        now = datetime.now(timezone.utc)
        # The KX3 dial plus our tone is where the signal is.
        rf = int(st.frequency + self.offset_hz)
        entry = adif.LogEntry(
            call=self.their_call, grid="", rst_sent=rst_sent or "599", rst_rcvd=rst_rcvd or "599",
            time_on=self.time_on or now, time_off=now, band=band.name if band else "", dial_hz=rf,
            station_call=self.settings.callsign, my_grid=self.settings.grid, tx_power_w=st.power_set,
            mode="CW" if self.mode == CW else "PSK", submode="" if self.mode == CW else "PSK31",
            name=name.strip(), comment=comment.strip(),
        )
        adif.append(self.log_path, entry)
        self.set_their_call("")
        return entry

    # --- tuning -----------------------------------------------------------------------

    def tune_radio(self, band: bandplan.Band) -> bool:
        """Put the radio on the band's PSK31 or CW-calling dial, DATA A. Refused while
        another activity (an FT8 contact, a WSPR beacon) may key the radio by itself."""
        dial = dial_for(self.mode, band)
        if dial is None or not self.station.connected or self.station.transmitting:
            return False
        if self.station.auto_keying(exclude=self):
            return False
        self.station.link.set_frequency(dial)
        self.station.link.set_mode(Mode.DATA, DataSubmode.DATA_A)
        self.set_offset(PSK_OFFSET_HZ if self.mode == PSK31 else CW_OFFSET_HZ)
        return True

    def find_cw_tone(self, seconds: float = 3.0) -> float | None:
        """Move receive to the strongest CW tone in the last few seconds of audio."""
        with self._lock:
            samples = np.concatenate(self._recent)[-int(seconds * 12_000):] if self._recent else None
        if samples is None or len(samples) < 6000:
            return None
        hz = cw.strongest_tone(samples, 12_000, 300, 2_000)
        if hz is not None:
            self.set_offset(hz)
        return hz
