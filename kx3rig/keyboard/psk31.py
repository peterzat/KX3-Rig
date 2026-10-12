"""BPSK31 on this computer: transmit audio and a receive decoder.

The mode is G3PLX's ("PSK31: A new radio-teletype mode", RadCom Dec 1998 /
Jan 1999, summarized at https://www.arrl.org/psk31-spec): 31.25 baud binary
PSK where a 0 bit is a phase reversal and a 1 bit is no change. Each reversal
is shaped with a raised cosine, so the amplitude falls through zero at the
reversal and the signal stays about 60 Hz wide. Idle is continuous reversals
(zeros); a transmission ends with a steady carrier. The transmit shaping
(amplitude = shape * previous + (1 - shape) * next, shape = (1 + cos)/2 across
the symbol) follows fldigi's src/psk/psk.cxx tx_symbol.

Receive (Decoder): mix the chosen audio frequency to baseband, low-pass and
decimate to 500 Hz (16 samples per symbol), pick the symbol timing from where
the envelope peaks, and compare each symbol's phase with the previous one.
The squared phase difference is 0 for both bit values when the tuning is
right, so its running mean gives both a quality figure (how coherent it is)
and the frequency error (how far it rotates per symbol) for AFC.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from . import varicode

BAUD = 31.25
RX_RATE = 12_000
DECIM = 24                       # 12 kHz -> 500 Hz
SPS = 16                         # samples per symbol after decimation
FIR_TAPS = 384
FIR_CUTOFF_HZ = 50.0
AFC_RANGE_HZ = 15.0
AFC_GAIN = 0.08
QUALITY_ALPHA = 0.05             # per symbol
SQUELCH = 0.55
TIMING_DECAY = 0.97              # per symbol


def _symbol_count(seconds: float) -> int:
    return int(round(seconds * BAUD))


def _bits(text: str, preamble_s: float, postamble_s: float) -> str:
    return "0" * _symbol_count(preamble_s) + varicode.encode(text) + "1" * _symbol_count(postamble_s)


def duration_s(text: str, preamble_s: float = 1.0, postamble_s: float = 0.5) -> float:
    """Length of modulate(text): every bit, plus one symbol of fade-out."""
    return (len(_bits(text, preamble_s, postamble_s)) + 1) / BAUD


def char_times(text: str, preamble_s: float = 1.0) -> list[tuple[str, float]]:
    """Each sent character with the time its first bit starts, from the start of the audio."""
    t = _symbol_count(preamble_s) / BAUD
    out = []
    for ch in text:
        if ord(ch) >= 128:
            continue
        out.append((ch, t))
        t += (len(varicode.CODES[ord(ch)]) + 2) / BAUD
    return out


def modulate(text: str, rate: int = 48_000, f0: float = 1000.0, preamble_s: float = 1.0,
             postamble_s: float = 0.5) -> np.ndarray:
    """Unit-amplitude BPSK31 audio for text, starting and ending at zero."""
    bits = _bits(text, preamble_s, postamble_s)
    signs = np.empty(len(bits))
    s = 1.0
    for i, b in enumerate(bits):
        if b == "0":
            s = -s
        signs[i] = s
    levels = np.concatenate([[0.0], signs, [0.0]])
    nsps = int(round(rate / BAUD))
    i = np.arange(nsps)
    shape = 0.5 + 0.5 * np.cos(np.pi * i / nsps)
    env = (shape[None, :] * levels[:-1, None] + (1 - shape[None, :]) * levels[1:, None]).ravel()
    t = np.arange(env.size) / rate
    return (env * np.cos(2 * np.pi * f0 * t)).astype(np.float32)


def _lowpass(taps: int, cutoff: float, rate: float) -> np.ndarray:
    n = np.arange(taps) - (taps - 1) / 2
    h = np.sinc(2 * cutoff / rate * n) * np.blackman(taps)
    return (h / h.sum()).astype(np.float64)


_FIR = _lowpass(FIR_TAPS, FIR_CUTOFF_HZ, RX_RATE)


class Decoder:
    """One PSK31 channel at an audio frequency. Feed it 12 kHz audio in any chunk size."""

    def __init__(self, rate: int = RX_RATE, freq: float = 1000.0):
        if rate != RX_RATE:
            raise ValueError("the PSK31 decoder expects 12 kHz audio")
        self.rate = rate
        self.set_freq(freq)

    def set_freq(self, hz: float) -> None:
        self.center = float(hz)          # where the operator (or the browser) put it
        self.freq = float(hz)            # where AFC has it now
        self._phase = 0.0
        self._tail = np.zeros(0, np.complex128)
        self._count = 0                  # decimated samples seen
        self._energy = np.zeros(SPS)
        self._sample_at = 0
        self._since = SPS
        self._prev: complex | None = None
        self._coherence = 0j             # running mean of the unit squared phase difference
        self.quality = 0.0
        self._varicode = varicode.Decoder()

    @property
    def active(self) -> bool:
        return self.quality >= SQUELCH

    def feed(self, samples: np.ndarray) -> str:
        x = np.asarray(samples, dtype=np.float64)
        if x.size == 0:
            return ""
        n = np.arange(x.size)
        w = 2 * np.pi * self.freq / self.rate
        base = x * np.exp(-1j * (self._phase + w * n))
        self._phase = (self._phase + w * x.size) % (2 * np.pi)
        buf = np.concatenate([self._tail, base])
        if buf.size < FIR_TAPS:
            self._tail = buf
            return ""
        m = (buf.size - FIR_TAPS) // DECIM + 1
        windows = np.lib.stride_tricks.sliding_window_view(buf, FIR_TAPS)[::DECIM][:m]
        z = windows @ _FIR
        self._tail = buf[m * DECIM:]
        return self._symbols(z)

    def _symbols(self, z: np.ndarray) -> str:
        out = []
        mags = np.abs(z)
        for k in range(z.size):
            slot = self._count % SPS
            self._energy[slot] += mags[k]
            self._count += 1
            self._since += 1
            if slot != self._sample_at or self._since < SPS // 2:
                continue
            self._since = 0
            self._energy *= TIMING_DECAY
            self._sample_at = int(np.argmax(self._energy))
            cur = complex(z[k])
            prev, self._prev = self._prev, cur
            if prev is None:
                continue
            d = cur * prev.conjugate()
            if abs(d) < 1e-12:
                continue
            u = (d / abs(d)) ** 2
            self._coherence += QUALITY_ALPHA * (u - self._coherence)
            self.quality = abs(self._coherence)
            if self.quality > 0.3:
                # Rotation per symbol from the mistuning, in hertz.
                err = math.atan2(self._coherence.imag, self._coherence.real) / 2 / (2 * math.pi) * BAUD
                self.freq = min(max(self.freq + AFC_GAIN * err, self.center - AFC_RANGE_HZ),
                                self.center + AFC_RANGE_HZ)
            ch = self._varicode.push(1 if d.real > 0 else 0)
            if ch is not None and self.active:
                out.append(ch)
        return "".join(out)


# --- watching the whole passband -------------------------------------------------------------

SCAN_EVERY_S = 2.0
SILENT_DROP_S = 30.0
MIN_SPACING_HZ = 50.0
KEEP_HZ = 20.0
TEXT_KEEP = 200


@dataclass
class Channel:
    id: int
    decoder: Decoder
    created: float
    last_heard: float
    text: str = ""

    @property
    def freq(self) -> float:
        return self.decoder.freq

    @property
    def quality(self) -> float:
        return self.decoder.quality


@dataclass
class Browser:
    """Finds PSK31 signals in the passband and decodes each one."""

    rate: int = RX_RATE
    max_channels: int = 8
    lo: float = 300.0
    hi: float = 2700.0
    channels: list[Channel] = field(default_factory=list)

    def __post_init__(self) -> None:
        self._nfft = 4096
        self._window = np.hanning(self._nfft)
        self._recent = np.zeros(0, np.float64)
        self._clock = 0.0                  # seconds of audio seen
        self._next_scan = SCAN_EVERY_S
        self._next_id = 1

    def feed(self, samples: np.ndarray, now: float | None = None) -> dict[int, str]:
        x = np.asarray(samples, dtype=np.float64)
        self._clock += x.size / self.rate
        now = self._clock if now is None else now
        keep = int(SCAN_EVERY_S * self.rate)
        self._recent = np.concatenate([self._recent, x])[-keep:]
        new: dict[int, str] = {}
        for ch in self.channels:
            text = ch.decoder.feed(x)
            if text:
                ch.text = (ch.text + text)[-TEXT_KEEP:]
                ch.last_heard = now
                new[ch.id] = text
        if self._clock >= self._next_scan:
            self._next_scan = self._clock + SCAN_EVERY_S
            self._scan(now)
        return new

    def _scan(self, now: float) -> None:
        # Merge decoders that AFC pulled onto the same signal: keep the older.
        merged: list[Channel] = []
        for ch in sorted(self.channels, key=lambda c: c.created):
            if all(abs(ch.freq - m.freq) > KEEP_HZ / 2 for m in merged):
                merged.append(ch)
        self.channels = [c for c in merged if now - c.last_heard < SILENT_DROP_S]
        peaks = self.find_peaks(self._recent)
        for f in peaks:
            if len(self.channels) >= self.max_channels:
                break
            if any(abs(c.freq - f) < KEEP_HZ for c in self.channels):
                continue
            self.channels.append(Channel(self._next_id, Decoder(self.rate, f), now, now))
            self._next_id += 1
        self.channels.sort(key=lambda c: c.freq)

    def find_peaks(self, x: np.ndarray) -> list[float]:
        """Audio frequencies of narrow (about 31-60 Hz wide) signals, strongest first."""
        n = self._nfft
        if x.size < n:
            return []
        frames = [x[i:i + n] * self._window for i in range(0, x.size - n + 1, n // 2)]
        power = np.mean([np.abs(np.fft.rfft(f)) ** 2 for f in frames], axis=0)
        bin_hz = self.rate / n
        inner = max(1, int(round(25 / bin_hz)))       # +-25 Hz: the PSK31 signal
        outer = int(round(80 / bin_hz))               # 40-80 Hz away: should be quiet
        smooth = np.convolve(power, np.ones(2 * inner + 1), "same")
        floor = np.median(smooth[int(self.lo / bin_hz):int(self.hi / bin_hz)]) + 1e-20
        found: list[tuple[float, float]] = []
        lo_bin, hi_bin = int(self.lo / bin_hz), int(self.hi / bin_hz)
        for k in range(max(lo_bin, outer + 1), min(hi_bin, smooth.size - outer - 1)):
            s = smooth[k]
            if s < 4 * floor or s < smooth[k - 1] or s <= smooth[k + 1]:
                continue
            shoulders = np.concatenate([power[k - outer:k - 2 * inner], power[k + 2 * inner + 1:k + outer + 1]])
            ring = float(np.mean(shoulders)) * (2 * inner + 1) if shoulders.size else 0.0
            if ring > 0.3 * s:
                continue        # wide: voice, noise, or an FT8 cluster, not PSK31
            found.append((s, k * bin_hz))
        found.sort(reverse=True)
        picked: list[float] = []
        for _, f in found:
            if all(abs(f - p) >= MIN_SPACING_HZ for p in picked):
                picked.append(f)
        return picked


def demo_signal(texts_and_offsets: list[tuple[str, float]], seconds: float, rate: int = RX_RATE,
                snr_db: float = 10.0, seed: int = 0) -> np.ndarray:
    """A band of PSK31 stations, each repeating its text, in white noise.

    snr_db is each signal's power against the noise in a 3 kHz bandwidth.
    """
    rng = np.random.default_rng(seed)
    total = int(seconds * rate)
    out = np.zeros(total)
    noise_power_3k = 1.0
    sigma = math.sqrt(noise_power_3k * (rate / 2) / 3000)
    amp = math.sqrt(2 * noise_power_3k * 10 ** (snr_db / 10))
    for text, offset in texts_and_offsets:
        # One continuous transmission of the text repeated: no fades between repeats.
        line = text + " "
        reps = int(np.ceil(seconds / max(duration_s(line, 0, 0), 0.1))) + 2
        wave = modulate(line * reps, rate, offset, preamble_s=1.0, postamble_s=0.2).astype(np.float64)
        start = int(rng.integers(0, max(1, wave.size - total)))
        piece = wave[start:start + total]
        out[:piece.size] += amp * piece
    out += rng.normal(0, sigma, total)
    return (0.5 * out / (np.max(np.abs(out)) + 1e-12)).astype(np.float32)
