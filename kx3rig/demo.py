"""Synthetic receive audio for demo mode (`kx3-rig --demo`).

Produces 12 kHz audio in real time that resembles what the KX3 PHONES output
carries: receiver noise shaped by the IF filter, plus signals appropriate to the
current mode. In DATA mode on an FT8 dial frequency it transmits real FT8
messages (when the FT8 encoder is available) so the decoder can be exercised
end to end without a radio.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

from .cat import Mode
from .looptune.state import BANDWIDTH_HZ

RATE = 12_000
CHUNK = 256


def synth_voice(seconds: float, rate: int, center_hz: float = 1100, amp: float = 0.05,
                pitch: float = 140, rng: np.random.Generator | None = None, t0: float = 0.0,
                shift_hz: float = 0.0, phase: float | None = None) -> np.ndarray:
    """Speech-like audio: harmonics of a wandering pitch under a formant hump,
    gated by a syllable-rate envelope. Good enough to exercise detection.

    shift_hz moves the whole spectrum, as an SSB receiver does when it is not
    tuned to the station's carrier. Time starts at t0 and the phase is
    computed in closed form, so consecutive blocks join without clicks.
    """
    if phase is None:
        phase = (rng or np.random.default_rng()).uniform(0, 6.3)
    t = t0 + np.arange(int(round(seconds * rate))) / rate
    env = np.clip(0.8 * np.sin(2 * np.pi * 3.3 * t + phase) + 0.4 * np.sin(2 * np.pi * 0.7 * t + 2 * phase), 0, None)
    wobble = 1.3
    f0 = pitch + 20 * np.sin(2 * np.pi * wobble * t + phase)
    ph = 2 * np.pi * pitch * t - (20 / wobble) * np.cos(2 * np.pi * wobble * t + phase)
    out = np.zeros_like(t)
    for k in range(2, 24):
        gain = np.exp(-((k * pitch - center_hz) / 700) ** 2)
        if gain <= 0.02:
            continue
        audio_hz = k * f0 + shift_hz
        audible = (audio_hz > 150) & (audio_hz < 3_000) & (k * f0 < 2_700)
        if audible.any():
            out += gain * np.sin(k * ph + 2 * np.pi * shift_hz * t) * audible
    return (amp * env * out).astype(np.float32)


def synth_cw(seconds: float, rate: int, freq: float = 700, amp: float = 0.03, wpm: float = 18,
             t0: float = 0.0) -> np.ndarray:
    """A keyed tone: dits and dahs with spaces, at roughly `wpm`."""
    t = t0 + np.arange(int(round(seconds * rate))) / rate
    dot = 1.2 / wpm
    pattern = np.array([1, 0, 1, 1, 1, 0, 1, 0, 0, 0, 1, 1, 1, 0, 1, 0, 1, 1, 1, 0, 0, 0, 0])   # a repeating "word"
    # Raised-cosine edges (about 5 ms) keep the keying clicks out of the neighbouring bins.
    pos = t / dot
    idx = np.floor(pos).astype(int)
    on = pattern[idx % len(pattern)].astype(np.float32)
    prev = pattern[(idx - 1) % len(pattern)].astype(np.float32)
    frac = np.clip((pos - idx) * dot / 0.005, 0, 1)
    edge = 0.5 - 0.5 * np.cos(np.pi * frac)
    keyed = prev + (on - prev) * edge
    return (amp * keyed * np.sin(2 * np.pi * freq * t)).astype(np.float32)


# --- a band full of stations, heard through a magnetic loop ------------------------------

# The AlexLoop's approximate 2:1 SWR bandwidth per band (looptune.state). The
# demo uses it as the loop's -3 dB receive bandwidth: good enough to make the
# band view's noise curve and the Loop Tune meter behave like the real thing.
LOOP_BANDWIDTH_HZ = BANDWIDTH_HZ
CW_PITCH = 600


@dataclass(frozen=True)
class DemoStation:
    rf: int            # carrier (voice) or signal (CW) frequency
    kind: str          # "voice" or "cw"
    amp: float
    on_s: float        # transmits for this long ...
    off_s: float       # ... then listens for this long (the other side, unheard)
    offset_s: float
    pitch: float = 130

    def keyed(self, wall: float) -> bool:
        return (wall + self.offset_s) % (self.on_s + self.off_s) < self.on_s


def demo_stations() -> list[DemoStation]:
    """A few voice and CW stations on each band, at plausible frequencies."""
    from . import bandplan

    out: list[DemoStation] = []
    rng = np.random.default_rng(73)
    for band in bandplan.BANDS:
        for kind, count in (("voice", 6), ("cw", 4)):
            ranges = bandplan.scan_ranges(band, kind, "General")
            if not ranges:
                continue
            low, high = ranges[0]
            for i in range(count):
                if kind == "voice":
                    rf = int(round(rng.uniform(low + 3_000, high - 3_000) / 1_000) * 1_000)
                    on, off = rng.uniform(8, 16), rng.uniform(3, 8)
                else:
                    rf = int(round(rng.uniform(low + 1_000, high - 1_000) / 50) * 50)
                    on, off = rng.uniform(10, 20), rng.uniform(2, 5)
                out.append(DemoStation(rf, kind, float(rng.uniform(0.015, 0.08)), on, off,
                                       float(rng.uniform(0, 30)), float(rng.uniform(100, 190))))
    # The "voice" screenshot plan tunes to 14.285: always someone there.
    out.append(DemoStation(14_285_000, "voice", 0.07, 20, 2, 0, 140))
    return out


class DemoLoop:
    """Where the demo's magnetic loop is tuned: wherever the dial rests a while,
    or, while the Loop Tune guide turns its pretend knob, wherever that says."""

    REST_S = 8.0
    MATCH_R = 1.3     # resistive mismatch at resonance: a good AlexLoop dips to about 1.3:1

    def __init__(self) -> None:
        self.tuned_hz = 0
        self.manual = False
        self._dial = 0
        self._since = 0.0

    def _x(self, dial: int) -> float | None:
        """Offset from resonance in half-bandwidths, or None off the loop's bands."""
        from . import bandplan

        band = bandplan.band_for(dial)
        bw = LOOP_BANDWIDTH_HZ.get(band.name if band else "", 0)
        if not bw:
            return None
        if bandplan.band_for(self.tuned_hz) is not band:
            return float("inf")
        return 2 * (dial - self.tuned_hz) / bw

    def gain(self, dial: int, wall: float) -> float:
        if dial != self._dial:
            self._dial, self._since = dial, wall
        elif not self.manual and (wall - self._since > self.REST_S or not self.tuned_hz):
            self.tuned_hz = dial
        x = self._x(dial)
        if x is None:
            return 1.0
        if x == float("inf"):
            return 0.25
        return float(1 / np.sqrt(1 + x * x))

    def swr(self, dial: int) -> float:
        """A series-resonant load, z = R + jX, scaled so the 2:1 points sit
        half a bandwidth either side (as VE3WDM measured)."""
        x = self._x(dial)
        if x is None or x == float("inf"):
            return 15.0
        z = complex(self.MATCH_R, x / np.sqrt(2) * 1.1)
        gamma = abs((z - 1) / (z + 1))
        return float(min(99.9, (1 + gamma) / (1 - gamma)))


class DemoAudio:
    def __init__(self, on_samples: Callable[[np.ndarray, float], None], radio_state: Callable[[], object]):
        self._on_samples = on_samples
        self._radio_state = radio_state
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._rng = np.random.default_rng(7)
        self.listen = True
        self._ft8_slot = None
        self._ft8_audio = np.zeros(0, np.float32)
        self._ft8_messages: list[tuple[str, float, float]] = []
        self._noise_state = np.zeros(2)
        # Bandpass shaping for receiver noise, roughly 250-2900 Hz.
        self._fir = self._design_bandpass(250, 2900)
        self._stations = demo_stations()
        self.loop = DemoLoop()

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="demo-audio", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)

    @staticmethod
    def _design_bandpass(lo: float, hi: float, taps: int = 129) -> np.ndarray:
        n = np.arange(taps) - (taps - 1) / 2
        h = (np.sinc(2 * hi / RATE * n) * 2 * hi / RATE) - (np.sinc(2 * lo / RATE * n) * 2 * lo / RATE)
        return (h * np.hamming(taps)).astype(np.float32)

    def _run(self) -> None:
        t_next = time.monotonic()
        tail = np.zeros(len(self._fir) - 1, np.float32)
        sample_index = 0
        while not self._stop.is_set():
            now = time.monotonic()
            if now < t_next:
                time.sleep(min(0.01, t_next - now))
                continue
            noise = self._rng.normal(0, 0.02, CHUNK).astype(np.float32)
            block = np.concatenate([tail, noise])
            shaped = np.convolve(block, self._fir, mode="valid").astype(np.float32)
            tail = block[-(len(self._fir) - 1):]
            t = (sample_index + np.arange(CHUNK)) / RATE
            wall = time.time()
            signal = self._signals(t, wall)
            # Band noise and signals both come through the loop; the receiver's
            # own noise does not, so the floor drops (but not to nothing) off tune.
            g = self.loop.gain(getattr(self._radio_state(), "frequency", 0), wall)
            out = shaped * 4.0 * (0.3 + 0.7 * g) + signal * g
            sample_index += CHUNK
            self._on_samples(out.astype(np.float32), time.time())
            t_next += CHUNK / RATE

    def _signals(self, t: np.ndarray, wall: float) -> np.ndarray:
        state = self._radio_state()
        mode = getattr(state, "mode", None)
        freq = getattr(state, "frequency", 0)
        out = np.zeros_like(t, dtype=np.float32)
        if getattr(state, "ptt", False) or getattr(state, "transmitting", False):
            return out
        if mode is not None and mode.is_data:
            out += self._ft8_like(t, wall)
        elif mode is not None and (mode.is_cw or mode in (Mode.USB, Mode.LSB, Mode.AM)):
            out += self._band(t, wall, freq, mode)
        return out.astype(np.float32)

    def _band(self, t: np.ndarray, wall: float, dial: int, mode: Mode) -> np.ndarray:
        """The demo stations audible at this dial frequency and mode."""
        out = np.zeros(len(t), np.float32)
        lsb = mode in (Mode.LSB, Mode.CW_REV)
        for st in self._stations:
            if abs(st.rf - dial) > 4_000 or not st.keyed(wall):
                continue
            # Audio offset of the station's carrier (voice) or tone (CW).
            shift = (dial - st.rf) if lsb else (st.rf - dial)
            if mode.is_cw:
                shift += CW_PITCH if st.kind == "cw" else 0
            if st.kind == "voice":
                if lsb and mode is Mode.LSB or not lsb and mode is Mode.USB or mode is Mode.AM:
                    out += synth_voice(len(t) / RATE, RATE, center_hz=900, amp=st.amp, pitch=st.pitch,
                                       t0=t[0], shift_hz=shift, phase=st.offset_s)
            elif 150 < shift < 3_000:
                out += synth_cw(len(t) / RATE, RATE, freq=shift, amp=st.amp, t0=t[0] + st.offset_s)
        return out

    def _ft8_like(self, t: np.ndarray, wall: float) -> np.ndarray:
        slot = int(wall // 15)
        if slot != self._ft8_slot:
            self._ft8_slot = slot
            self._ft8_audio = self._render_slot(slot)
        offset = int(((wall % 15.0) - (t[-1] - t[0])) * RATE)
        offset = max(0, offset)
        seg = self._ft8_audio[offset: offset + len(t)]
        if len(seg) < len(t):
            seg = np.concatenate([seg, np.zeros(len(t) - len(seg), np.float32)])
        return seg

    def _render_slot(self, slot: int) -> np.ndarray:
        """One 15 s FT8 cycle of demo signals."""
        try:
            from . import ft8
        except ImportError:
            return np.zeros(15 * RATE, np.float32)

        rng = np.random.default_rng(slot)
        audio = np.zeros(15 * RATE, np.float32)
        try:
            messages = ft8.demo_messages(slot)
        except AttributeError:
            return audio
        for text, offset_hz, snr_db in messages:
            try:
                wave = ft8.synthesize(text, offset_hz, RATE)
            except Exception:
                continue
            amp = 0.02 * 4.0 * 10 ** (snr_db / 20.0) * 3.0
            start = int((0.5 + rng.uniform(-0.1, 0.3)) * RATE)
            end = min(len(audio), start + len(wave))
            audio[start:end] += amp * wave[: end - start]
        return audio
