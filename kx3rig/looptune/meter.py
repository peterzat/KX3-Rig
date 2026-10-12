"""The receive-noise meter for peaking the loop by ear and by eye.

A magnetic loop passes band noise only near its resonance, so the noise from
PHONES rises to a clear peak as the tuning capacitor passes the frequency on
the dial. The meter reports the passband noise floor (the same robust
measurement Smartscan uses, so a signal in the passband does not lift it),
the highest level seen, and whether the operator has turned past the peak.

Pure numpy and time arithmetic: the UI feeds it audio and reads it back.
"""

from __future__ import annotations

import collections
from dataclasses import dataclass

import numpy as np

from ..smartscan.detect import RATE, noise_floor_db

WINDOW_S = 0.75         # audio per reading (noise_floor_db needs 0.5 s of frames)
STEP_S = 0.25           # a new reading this often
RISE_DB = 3.0           # the level climbed this far: the operator found the peak region
PAST_DB = 2.5           # ...then fell this far below the best: turned past it
NEAR_DB = 1.0           # within this of the best: on the peak


@dataclass(frozen=True)
class Reading:
    level_db: float      # now
    best_db: float       # highest seen since reset
    low_db: float        # lowest seen since reset
    state: str           # "searching", "rising", "peak", or "past"

    @property
    def span_db(self) -> float:
        return self.best_db - self.low_db

    def fraction(self, floor_span_db: float = 12.0) -> float:
        """0..1 for a level bar: the current level within what has been seen,
        but never less than floor_span_db of range (so noise jitter on a flat
        reading does not swing the bar end to end)."""
        span = max(self.span_db, floor_span_db)
        return float(max(0.0, min(1.0, (self.level_db - (self.best_db - span)) / span)))


class NoiseMeter:
    def __init__(self) -> None:
        self._audio: collections.deque = collections.deque()
        self._samples = 0
        self._since_reading = 0
        self.reading: Reading | None = None
        self._smoothed: float | None = None
        self._peaked = False

    def reset(self) -> None:
        self._audio.clear()
        self._samples = 0
        self._since_reading = 0
        self.reading = None
        self._smoothed = None
        self._peaked = False

    def feed(self, samples: np.ndarray) -> Reading | None:
        """Add receive audio (12 kHz mono). Returns a new reading when one is due."""
        self._audio.append(np.asarray(samples, dtype=np.float32))
        self._samples += len(samples)
        self._since_reading += len(samples)
        window = int(WINDOW_S * RATE)
        while self._samples - len(self._audio[0]) >= window:
            self._samples -= len(self._audio.popleft())
        if self._samples < window or self._since_reading < STEP_S * RATE:
            return None
        self._since_reading = 0
        level = noise_floor_db(np.concatenate(list(self._audio))[-window:])
        if level is None:
            return None
        # Light smoothing: the knob is turned by hand, a fraction of a second matters less than jitter.
        self._smoothed = level if self._smoothed is None else 0.5 * self._smoothed + 0.5 * level
        self.reading = self._next(self._smoothed)
        return self.reading

    def _next(self, level: float) -> Reading:
        prev = self.reading
        best = level if prev is None else max(prev.best_db, level)
        low = level if prev is None else min(prev.low_db, level)
        if best - low < RISE_DB:
            state = "searching"
        elif level >= best - NEAR_DB:
            state = "peak"
        elif level < best - PAST_DB and self._peaked:
            state = "past"
        else:
            state = "rising"
        self._peaked = self._peaked or state == "peak"
        return Reading(level, best, low, state)
