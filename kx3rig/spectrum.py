"""Audio spectrum for the waterfall, plus simple level metering.

Everything here is pure numpy so it can be tested without audio hardware.
The waterfall shows the receiver's audio passband (what comes out of the KX3
PHONES jack), sampled at 12 kHz.
"""

from __future__ import annotations

import numpy as np

SAMPLE_RATE = 12_000


class Spectrum:
    """Turns a stream of audio samples into waterfall rows (dB per bin).

    fft_size sets frequency resolution (2048 at 12 kHz = 5.9 Hz per bin, fine
    enough to see FT8's 6.25 Hz tones as one trace). hop sets the row rate
    (512 samples = about 23 rows per second).
    """

    def __init__(self, fft_size: int = 2048, hop: int = 512, sample_rate: int = SAMPLE_RATE):
        if hop <= 0 or hop > fft_size:
            raise ValueError("hop must be in 1..fft_size")
        self.fft_size = fft_size
        self.hop = hop
        self.sample_rate = sample_rate
        self.window = np.hanning(fft_size).astype(np.float32)
        # Normalize so a full-scale sine reads about 0 dB.
        self._scale = 2.0 / float(self.window.sum())
        self._buf = np.zeros(0, dtype=np.float32)

    @property
    def bin_hz(self) -> float:
        return self.sample_rate / self.fft_size

    def bins_for(self, low_hz: float, high_hz: float) -> slice:
        lo = max(0, int(round(low_hz / self.bin_hz)))
        hi = min(self.fft_size // 2 + 1, int(round(high_hz / self.bin_hz)) + 1)
        return slice(lo, hi)

    def feed(self, samples: np.ndarray) -> list[np.ndarray]:
        """Add samples; return any complete rows of dB magnitudes."""
        self._buf = np.concatenate([self._buf, np.asarray(samples, dtype=np.float32)])
        rows: list[np.ndarray] = []
        while self._buf.size >= self.fft_size:
            frame = self._buf[: self.fft_size] * self.window
            mag = np.abs(np.fft.rfft(frame)) * self._scale
            rows.append(20.0 * np.log10(mag + 1e-9).astype(np.float32))
            self._buf = self._buf[self.hop :]
        return rows


class AutoLevel:
    """Tracks the noise floor so the waterfall looks right at any AF gain.

    The floor follows the median of each row (the band noise, since signals
    occupy few bins), smoothed so it does not pump with every fade.
    """

    def __init__(self, span_db: float = 45.0, below_floor_db: float = 3.0, smoothing: float = 0.05):
        self.span_db = span_db
        self.below_floor_db = below_floor_db
        self.smoothing = smoothing
        self.floor: float | None = None

    def normalize(self, row_db: np.ndarray) -> np.ndarray:
        """Map a dB row to 0..1 for the color map."""
        median = float(np.median(row_db))
        if self.floor is None:
            self.floor = median
        else:
            self.floor += self.smoothing * (median - self.floor)
        low = self.floor - self.below_floor_db
        return np.clip((row_db - low) / self.span_db, 0.0, 1.0)


def rms_dbfs(samples: np.ndarray) -> float:
    """RMS level in dB relative to full scale (a full-scale sine is -3 dBFS)."""
    if samples.size == 0:
        return -120.0
    rms = float(np.sqrt(np.mean(np.square(samples, dtype=np.float64))))
    return 20.0 * np.log10(max(rms, 1e-6))


def audio_to_rf(offset_hz: float, dial_hz: int, lower_sideband: bool) -> float:
    """RF frequency of a signal heard at `offset_hz` in the audio passband."""
    return dial_hz - offset_hz if lower_sideband else dial_hz + offset_hz
