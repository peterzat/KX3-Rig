"""FT8 receive: keep recent audio aligned to UTC and decode it with WSJT-X's jt9.

jt9 needs a 16-bit, mono, 12 kHz WAV (it does not check the header: anything
else silently decodes nothing). The file name supplies the HHMMSS printed on
each line, so files are named YYMMDD_HHMMSS.wav. Always pass -c MYCALL: jt9's
default call (K1ABC) is otherwise silently active. Details and timings in
docs/references.md ("FT8 engine").
"""

from __future__ import annotations

import os
import shutil
import subprocess
import threading
import time
import wave
from dataclasses import dataclass
from datetime import datetime, timezone

import numpy as np

RATE = 12_000
PERIOD = 15.0
JT9 = "jt9"


@dataclass(frozen=True)
class RawDecode:
    hhmmss: str
    snr: int
    dt: float
    freq: int
    message: str
    low_confidence: bool
    ap: str


def parse_jt9_line(line: str) -> RawDecode | None:
    """One stdout line: format(i6.6,i4,f5.1,i5,' ~ ',1x,a37,1x,a2) (lib/decoder.f90)."""
    line = line.rstrip("\n")
    if len(line) < 25 or line[20:23] != " ~ ":
        return None
    try:
        snr = int(line[6:10])
        dt = float(line[10:15])
        freq = int(line[15:20])
    except ValueError:
        return None
    msg37 = line[24:61].ljust(37)
    low = msg37[36] == "?"
    text = (msg37[:36] if low else msg37).strip()
    if not text:
        return None
    return RawDecode(line[0:6], snr, dt, freq, text, low, line[62:64].strip())


def wav_name(slot_start: float) -> str:
    return datetime.fromtimestamp(slot_start, timezone.utc).strftime("%y%m%d_%H%M%S.wav")


def write_wav(path: str, samples: np.ndarray) -> None:
    peak = float(np.max(np.abs(samples))) if samples.size else 0.0
    # Use most of the 16-bit range without clipping; jt9 normalizes anyway.
    scale = 0.5 * 32767 / peak if peak > 0.5 else 32767
    pcm = np.clip(np.rint(samples * scale), -32768, 32767).astype("<i2")
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(pcm.tobytes())


class Jt9:
    """Runs one jt9 process per period in a persistent work directory.

    The directory keeps jt9_wisdom.dat (FFTW plans), which makes later
    decodes about a second faster.
    """

    def __init__(self, workdir: str):
        self.workdir = workdir
        os.makedirs(workdir, exist_ok=True)

    @staticmethod
    def available() -> bool:
        return shutil.which(JT9) is not None

    def decode(self, samples: np.ndarray, slot_start: float, my_call: str, *, dx_call: str = "",
               dx_grid: str = "", rx_freq: int = 1500, qso_progress: int = 0, depth: int = 2,
               timeout: float = 12.0) -> list[RawDecode]:
        path = os.path.join(self.workdir, wav_name(slot_start))
        write_wav(path, samples)
        args = [JT9, "-8", "-d", str(depth), "-q", "-L", "200", "-H", "3000",
                "-f", str(int(rx_freq)), "-c", my_call or "b",
                "-x", dx_call or "b", "-Q", str(int(qso_progress)),
                "-a", self.workdir, "-t", self.workdir]
        if dx_grid:
            args += ["-g", dx_grid[:4]]
        args.append(path)
        try:
            out = subprocess.run(args, cwd=self.workdir, capture_output=True, text=True, timeout=timeout).stdout
        finally:
            try:
                os.remove(path)
            except OSError:
                pass
        decodes = [d for d in (parse_jt9_line(line) for line in out.splitlines()) if d]
        # jt9 can report the same message twice across passes; keep the first.
        seen: set[tuple[str, int]] = set()
        unique = []
        for d in decodes:
            key = (d.message, d.freq // 10)
            if key not in seen:
                seen.add(key)
                unique.append(d)
        return unique


class SlotRecorder:
    """Recent receive audio, indexed by wall-clock time.

    Audio arrives in chunks stamped with time.time() at arrival. The stream's
    epoch (wall time of sample 0) is tracked with a slow average, which
    smooths arrival jitter and follows the sound card's clock drifting
    against the system clock (tens of ppm, enough to matter over hours).
    """

    def __init__(self, seconds: float = 45.0, rate: int = RATE):
        self.rate = rate
        self.capacity = int(seconds * rate)
        self._buf = np.zeros(self.capacity, np.float32)
        self._total = 0
        self._epoch: float | None = None
        self._lock = threading.Lock()

    def feed(self, samples: np.ndarray, end_time: float) -> None:
        n = len(samples)
        if n == 0:
            return
        with self._lock:
            offset = end_time - (self._total + n) / self.rate
            if self._epoch is None or abs(offset - self._epoch) > 1.0:
                self._epoch = offset   # first audio, or the stream restarted
            else:
                self._epoch += 0.02 * (offset - self._epoch)
            start = self._total % self.capacity
            first = min(n, self.capacity - start)
            self._buf[start:start + first] = samples[:first]
            if first < n:
                self._buf[: n - first] = samples[first:]
            self._total += n

    def extract(self, t0: float, seconds: float) -> tuple[np.ndarray, float]:
        """Samples for [t0, t0 + seconds), zero where missing, and the fraction present."""
        want = int(seconds * self.rate)
        out = np.zeros(want, np.float32)
        with self._lock:
            if self._epoch is None:
                return out, 0.0
            i0 = int(round((t0 - self._epoch) * self.rate))
            lo = max(i0, self._total - self.capacity)
            hi = min(i0 + want, self._total)
            if hi <= lo:
                return out, 0.0
            idx = np.arange(lo, hi) % self.capacity
            out[lo - i0: hi - i0] = self._buf[idx]
        return out, (hi - lo) / want

    @property
    def newest_time(self) -> float | None:
        with self._lock:
            if self._epoch is None:
                return None
            return self._epoch + self._total / self.rate


def slot_of(t: float) -> int:
    return int(t // PERIOD)


def slot_start(slot: int) -> float:
    return slot * PERIOD


def now() -> float:
    return time.time()
