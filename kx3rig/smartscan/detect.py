"""Find signals in a short stretch of receive audio (one Smartscan dwell).

Pure numpy, so it is tested on synthetic audio. The input is what the KX3's
PHONES jack carries at 12 kHz: band noise shaped by the IF filter, plus any
signals in the passband.

Two measurements share one short-time spectrum (11.7 Hz bins, 23 frames/s):

* Narrow signals, per bin. A bin is "on" in a frame when it is HOT_DB above
  the noise floor. A region no wider than NARROW_MAX_HZ that is on in part of
  the frames and switches often is CW; one that is on nearly all the time is a
  carrier (a birdie, a tuning carrier, a beacon), shown but never offered as a
  contact.
* Voice, per 200 Hz chunk. Summing a chunk's bins makes noise very steady (it
  varies by about a decibel), so a voice that adds a few decibels across
  several adjacent chunks and rises and falls with syllables stands out even
  when no single bin does.

The noise floor is each bin's 20th percentile over the dwell (speech pauses
and CW spaces let the floor show through), smoothed across 800 Hz with a
median so it follows the IF filter's shape but not a single signal.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

RATE = 12_000
NFFT = 1024
HOP = 512
BIN_HZ = RATE / NFFT
LOW_HZ = 300.0          # ignore the filter skirts
HIGH_HZ = 2_800.0
FLOOR_PERCENTILE = 20
FLOOR_SMOOTH_HZ = 800.0
MIN_SECONDS = 0.5

HOT_DB = 8.0            # narrow: a bin this far above the floor is on
NARROW_ACTIVE = 0.2     # ...in at least this share of the frames
NARROW_MAX_HZ = 120.0
CARRIER_FRACTION = 0.8  # on more than this: steady, not keyed

CHUNK_HZ = 200.0
VOICE_DB = 3.0          # voice: a chunk this far above its noise power
VOICE_ACTIVE = 0.15     # ...in at least this share of the frames
VOICE_SWING_DB = 4.0    # and its level swings at least this much (syllables)
VOICE_MIN_CHUNKS = 2


@dataclass(frozen=True)
class Detection:
    kind: str            # "voice", "cw", or "carrier"
    low_hz: float        # audio offsets of the occupied region
    high_hz: float
    peak_hz: float       # audio offset of the strongest part
    snr_db: float        # how far the signal rises above the noise (90th percentile)
    activity: float      # share of the dwell in which it was on

    @property
    def center_hz(self) -> float:
        return (self.low_hz + self.high_hz) / 2

    @property
    def is_contact(self) -> bool:
        return self.kind in ("voice", "cw")


def spectrogram(samples: np.ndarray) -> np.ndarray:
    """Power in dB, shape (frames, bins), Hann window, averaged over 3 bins and
    2 frames so single-bin noise spikes do not look like signals."""
    samples = np.asarray(samples, dtype=np.float32)
    n = 1 + (len(samples) - NFFT) // HOP if len(samples) >= NFFT else 0
    if n <= 0:
        return np.zeros((0, NFFT // 2 + 1), np.float32)
    window = np.hanning(NFFT).astype(np.float32)
    idx = np.arange(NFFT)[None, :] + HOP * np.arange(n)[:, None]
    power = np.abs(np.fft.rfft(samples[idx] * window, axis=1)) ** 2
    power = np.pad((power[:, :-2] + power[:, 1:-1] + power[:, 2:]) / 3, ((0, 0), (1, 1)), mode="edge")
    if len(power) > 1:
        power = np.concatenate([power[:1], (power[1:] + power[:-1]) / 2])
    return (10.0 * np.log10(power + 1e-12)).astype(np.float32)


def _running_median(x: np.ndarray, width: int) -> np.ndarray:
    half = max(1, width // 2)
    windows = np.lib.stride_tricks.sliding_window_view(np.pad(x, half, mode="edge"), 2 * half + 1)
    return np.median(windows, axis=1)[: len(x)]


def _passband(spec: np.ndarray) -> tuple[np.ndarray, np.ndarray, int]:
    lo_bin, hi_bin = int(LOW_HZ / BIN_HZ), int(HIGH_HZ / BIN_HZ)
    band = spec[:, lo_bin:hi_bin]
    per_bin = np.percentile(band, FLOOR_PERCENTILE, axis=0)
    return band, _running_median(per_bin, int(FLOOR_SMOOTH_HZ / BIN_HZ)), lo_bin


def noise_floor_db(samples: np.ndarray) -> float | None:
    """Typical noise level in the passband (dB per bin, relative to full scale).

    Smartscan compares it between frequencies: a magnetic loop's response
    falls off away from where it is tuned, and the band noise falls with it.
    """
    spec = spectrogram(samples)
    if len(spec) < MIN_SECONDS * RATE / HOP:
        return None
    _, floor, _ = _passband(spec)
    return float(np.median(floor))


def detect(samples: np.ndarray) -> list[Detection]:
    spec = spectrogram(samples)
    if len(spec) < MIN_SECONDS * RATE / HOP:
        return []
    band, floor, lo_bin = _passband(spec)
    excess = band - floor[None, :]
    narrow = _narrow(excess, lo_bin)
    # A carrier is steady, so it would not pass the voice test anyway, but its
    # chunk is excluded so a voice beside it is measured on its own.
    carriers = [(d.low_hz - 30, d.high_hz + 30) for d in narrow if d.kind == "carrier"]
    voices = _voice(band, floor, lo_bin, carriers)
    # A voice's harmonics look keyed in single bins; they are part of the voice.
    narrow = [d for d in narrow
              if not any(v.low_hz <= d.center_hz <= v.high_hz for v in voices)]
    return sorted(narrow + voices, key=lambda d: d.low_hz)


def _regions(mask: np.ndarray, gap: int = 1) -> list[tuple[int, int]]:
    """Runs of True as (first, last) index pairs, bridging gaps up to `gap`."""
    out: list[tuple[int, int]] = []
    start = last = None
    for i in np.flatnonzero(mask):
        if start is None:
            start = i
        elif i - last > gap + 1:
            out.append((start, last))
            start = i
        last = i
    if start is not None:
        out.append((start, last))
    return out


def _narrow(excess: np.ndarray, lo_bin: int) -> list[Detection]:
    activity = (excess > HOT_DB).mean(axis=0)
    found = []
    for a, b in _regions(activity >= NARROW_ACTIVE):
        if (b - a + 1) * BIN_HZ > NARROW_MAX_HZ:
            continue
        level = excess[:, a:b + 1].max(axis=1)
        on = level > HOT_DB
        frac = float(on.mean())
        transitions = int(np.count_nonzero(on[1:] != on[:-1]))
        if frac > CARRIER_FRACTION:
            kind = "carrier"
        elif transitions >= 4:
            kind = "cw"
        else:
            continue   # one burst: a click or a static crash
        peak = a + int(np.argmax(np.percentile(excess[:, a:b + 1], 90, axis=0)))
        found.append(Detection(kind, (lo_bin + a) * BIN_HZ, (lo_bin + b + 1) * BIN_HZ,
                               (lo_bin + peak) * BIN_HZ, float(np.percentile(level, 90)), frac))
    return found


def _voice(band: np.ndarray, floor: np.ndarray, lo_bin: int, taken) -> list[Detection]:
    width = int(CHUNK_HZ / BIN_HZ)
    n = band.shape[1] // width
    if n < VOICE_MIN_CHUNKS:
        return []
    lin = 10.0 ** (band[:, : n * width] / 10.0)
    noise = 10.0 ** (floor[: n * width] / 10.0)
    # Chunk power over the chunk's noise power: steady near 0 dB on noise.
    ratio = lin.reshape(len(lin), n, width).sum(axis=2) / noise.reshape(n, width).sum(axis=1)
    level = 10.0 * np.log10(ratio)
    level -= np.median(np.percentile(level, FLOOR_PERCENTILE, axis=0))   # re-zero on noise
    on = level > VOICE_DB
    activity = on.mean(axis=0)
    swing = np.percentile(level, 90, axis=0) - np.percentile(level, 20, axis=0)
    centers = (lo_bin + (np.arange(n) + 0.5) * width) * BIN_HZ
    overlaps_narrow = np.array([any(lo <= c <= hi for lo, hi in taken) for c in centers])
    candidate = (activity >= VOICE_ACTIVE) & (swing >= VOICE_SWING_DB) & ~overlaps_narrow
    found = []
    for a, b in _regions(candidate, gap=1):
        if b - a + 1 < VOICE_MIN_CHUNKS:
            continue
        region = level[:, a:b + 1]
        peak = a + int(np.argmax(np.percentile(region, 90, axis=0)))
        found.append(Detection(
            "voice",
            (lo_bin + a * width) * BIN_HZ, (lo_bin + (b + 1) * width) * BIN_HZ,
            float(centers[peak]),
            float(np.percentile(region.max(axis=1), 90)),
            float(on[:, a:b + 1].any(axis=1).mean()),
        ))
    return found
