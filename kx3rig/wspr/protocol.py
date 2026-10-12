"""WSPR protocol: message encoding, transmit audio, wsprd output, and scheduling.

WSJT-X installs wsprd (the decoder) but not wsprcode, so encoding is ported
here from WSJT-X lib/wsprd/wsprsim_utils.c (get_wspr_channel_symbols,
pack_call, pack_grid4_power, interleave) and lib/wsprd/fano.c (encode, with
the Layland-Lushbaugh polynomials selected at fano.c:13 and 48-49). Only Type 1
messages are supported: a plain callsign, a 4-character grid, and power in dBm.
The symbols match a reference build of that C code (tests/test_wspr_protocol.py).

Timing and tones (WSJT-X mainwindow.cpp and Modulator.cpp): 162 symbols of 8192
samples at 12 kHz (1.4648 baud), tone spacing 12000/8192 Hz, tone k at
f_center + (k - 1.5) * spacing (mainwindow.cpp:9114), 110.6 s long, starting
1 s after an even UTC minute (Modulator.cpp:72).

Dial frequencies are WSJT-X's defaults (models/FrequencyList.cpp). Line numbers
refer to WSJT-X commit b4f9a43.
"""

from __future__ import annotations

import math
import random
import wave
from dataclasses import dataclass
from datetime import datetime, timezone

import numpy as np

NSYM = 162
NSPS_12K = 8192
TONE_HZ = 12000 / 8192
PERIOD = 120.0
TX_START_S = 1.0
DURATION_S = NSYM * NSPS_12K / 12000
RATE = 12_000
WAV_SECONDS = 114          # wsprd reads exactly 114 * 12000 samples (wsprd.c:122)

# WSJT-X default WSPR dials (FrequencyList.cpp). 6 m 50.293 is listed for IARU
# Regions 2 and 3 (lines 282-283); the US is in Region 2.
DIALS: dict[str, int] = {
    "160m": 1_836_600,    # line 68
    "80m": 3_568_600,     # line 105
    "40m": 7_038_600,     # line 140
    "30m": 10_138_700,    # line 176
    "20m": 14_095_600,    # line 217
    "17m": 18_104_600,    # line 254
    "15m": 21_094_600,    # line 259
    "12m": 24_924_600,    # line 266
    "10m": 28_124_600,    # line 271
    "6m": 50_293_000,     # line 282 (R2)
}

# Allowed powers: 0, 3, 7, 10, 13, ... 60 dBm (the last digit 0, 3, or 7).
DBM_VALUES = tuple(d for d in range(0, 61) if d % 10 in (0, 3, 7))

# The 162-bit sync vector (wsprsim_utils.c pr3; genwspr.f90 npr3).
SYNC = (
    1, 1, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 1, 1, 1, 0, 0, 0, 1, 0,
    0, 1, 0, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 1, 0, 1,
    0, 0, 0, 0, 0, 0, 1, 0, 1, 1, 0, 0, 1, 1, 0, 1, 0, 0, 0, 1,
    1, 0, 1, 0, 0, 0, 0, 1, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 0, 1,
    0, 0, 1, 0, 1, 1, 0, 0, 0, 1, 1, 0, 1, 0, 1, 0, 0, 0, 1, 0,
    0, 0, 0, 0, 1, 0, 0, 1, 0, 0, 1, 1, 1, 0, 1, 1, 0, 0, 1, 1,
    0, 1, 0, 0, 0, 1, 1, 1, 0, 0, 0, 0, 0, 1, 0, 1, 0, 0, 1, 1,
    0, 0, 0, 0, 0, 0, 0, 1, 1, 0, 1, 0, 1, 1, 0, 0, 0, 1, 1, 0,
    0, 0,
)

POLY1 = 0xF2D05351
POLY2 = 0xE4613C47


# --- encoding -------------------------------------------------------------------------

def _call_code(ch: str) -> int:
    if ch.isdigit():
        return ord(ch) - 48
    if ch == " ":
        return 36
    return ord(ch) - 55        # A-Z -> 10-35


def _grid_code(ch: str) -> int:
    if ch.isdigit():
        return ord(ch) - 48
    return ord(ch) - 65        # A-R -> 0-17


def _plain_call(call: str) -> str:
    """The 6-character, space-padded form with the digit in position 3, or ValueError."""
    c = call.strip().upper()
    if not c or "/" in c or "<" in c or len(c) > 6 or not c.isascii() or not c.isalnum():
        raise ValueError(f"WSPR needs a plain callsign; “{call}” can't be sent as a standard WSPR message.")
    if len(c) >= 3 and c[2].isdigit():
        padded = c.ljust(6)
    elif len(c) >= 2 and c[1].isdigit():
        padded = (" " + c).ljust(6)
    else:
        padded = ""
    # Positions 4-6 must be letters or spaces (pack_call subtracts 10 from them).
    if len(padded) != 6 or not padded[0] in " 0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ" \
            or not padded[1].isalnum() or not padded[2].isdigit() \
            or any(not (ch == " " or ch.isalpha()) for ch in padded[3:]):
        raise ValueError(f"WSPR needs a plain callsign; “{call}” can't be sent as a standard WSPR message.")
    return padded


def _pack_call(call: str) -> int:
    c = [_call_code(ch) for ch in _plain_call(call)]
    n = c[0]
    n = n * 36 + c[1]
    n = n * 10 + c[2]
    n = n * 27 + c[3] - 10
    n = n * 27 + c[4] - 10
    n = n * 27 + c[5] - 10
    return n


def _pack_grid_power(grid4: str, dbm: int) -> int:
    g = grid4.strip().upper()
    if len(g) != 4 or not ("A" <= g[0] <= "R" and "A" <= g[1] <= "R" and g[2:].isdigit()):
        raise ValueError(f"WSPR needs a 4-character grid square; “{grid4}” isn't one.")
    if dbm not in DBM_VALUES:
        raise ValueError(f"{dbm} dBm isn't a WSPR power level.")
    a, b, c, d = (_grid_code(ch) for ch in g)
    m = (179 - 10 * a - c) * 180 + 10 * b + d
    return m * 128 + dbm + 64


def _parity(x: int) -> int:
    return bin(x).count("1") & 1


def _interleave(bits: list[int]) -> list[int]:
    """Bit-reversal interleaver over 0..255, keeping indices below 162."""
    out = [0] * NSYM
    p = 0
    i = 0
    while p < NSYM:
        j = int(f"{i:08b}"[::-1], 2)
        if j < NSYM:
            out[j] = bits[p]
            p += 1
        i += 1
    return out


def channel_symbols(call: str, grid4: str, dbm: int) -> tuple[int, ...]:
    """The 162 channel symbols (0-3) of a Type 1 message such as "K1ABC FN42 37"."""
    n = _pack_call(call)
    m = _pack_grid_power(grid4, dbm)
    data = [
        0xFF & (n >> 20), 0xFF & (n >> 12), 0xFF & (n >> 4),
        ((n & 0x0F) << 4) + ((m >> 18) & 0x0F),
        0xFF & (m >> 10), 0xFF & (m >> 2), (m & 0x03) << 6,
        0, 0, 0, 0,
    ]
    bits: list[int] = []
    state = 0
    for byte in data:
        for i in range(7, -1, -1):
            state = ((state << 1) | ((byte >> i) & 1)) & 0xFFFFFFFF
            bits.append(_parity(state & POLY1))
            bits.append(_parity(state & POLY2))
    channel = _interleave(bits[:NSYM])
    return tuple(2 * b + s for b, s in zip(channel, SYNC))


def message(call: str, grid4: str, dbm: int) -> str:
    return f"{call.strip().upper()} {grid4.strip().upper()} {dbm}"


# --- transmit audio ---------------------------------------------------------------------

RAMP_S = 0.01


def waveform(symbols, rate: int = 48_000, f_center: float = 1500.0) -> np.ndarray:
    """Unit-amplitude, continuous-phase 4-FSK, 110.6 s.

    WSJT-X starts at full amplitude and fades the last 0.017 symbol with a
    0.98-per-sample decay (Modulator.cpp:271-272, 316); here both ends get a
    10 ms raised-cosine ramp instead, which is equally short and click-free.
    """
    symbols = list(symbols)
    nsps = int(round(NSPS_12K * rate / 12_000))
    freqs = f_center + (np.repeat(np.asarray(symbols, float), nsps) - 1.5) * TONE_HZ
    phase = np.concatenate([[0.0], np.cumsum(2 * math.pi * freqs[:-1] / rate)])
    wave_ = np.sin(phase)
    n = int(RAMP_S * rate)
    ramp = (1 - np.cos(np.pi * np.arange(n) / n)) / 2
    wave_[:n] *= ramp
    wave_[-n:] *= ramp[::-1]
    return wave_.astype(np.float32)


def watts_to_dbm(watts: float) -> int:
    """The nearest allowed WSPR power for a transmitter power in watts."""
    if watts <= 0:
        return 0
    dbm = 10 * math.log10(watts * 1000)
    return min(DBM_VALUES, key=lambda d: abs(d - dbm))


def dbm_to_watts(dbm: int) -> float:
    return 10 ** (dbm / 10) / 1000


# --- receive (wsprd) -------------------------------------------------------------------

@dataclass(frozen=True)
class Spot:
    hhmm: str
    snr: int
    dt: float
    freq_hz: int
    drift: int
    message: str
    call: str = ""
    grid: str = ""
    dbm: int | None = None


def parse_wsprd_line(line: str, dial_hz: int = 0) -> Spot | None:
    """One stdout line, printf("%4s %3.0f %4.1f %10.6f %2d  %-s \\n") (wsprd.c:1505-1507).

    The frequency is printed in MHz as dial + (1500 + offset) Hz (wsprd.c:1459),
    using the -f dial wsprd was given; dial_hz is unused but kept for callers
    that ran wsprd without -f and want to add it.
    """
    text = line.strip()
    if not text or text.startswith("<DecodeFinished>"):
        return None
    parts = text.split(None, 5)
    if len(parts) < 6:
        return None
    hhmm, snr, dt, mhz, drift, msg = parts
    try:
        freq = float(mhz) * 1e6
        spot_snr = int(round(float(snr)))
        spot_dt = float(dt)
        spot_drift = int(drift)
    except ValueError:
        return None
    if freq < 1e5 and dial_hz:
        freq += dial_hz
    msg = " ".join(msg.split())
    words = msg.split(" ")
    call = grid = ""
    dbm = None
    if len(words) == 3 and "<" not in msg and "/" not in words[0] and words[2].lstrip("-").isdigit() \
            and len(words[1]) == 4:
        call, grid, dbm = words[0], words[1], int(words[2])
    return Spot(hhmm, spot_snr, spot_dt, int(round(freq)), spot_drift, msg, call, grid, dbm)


def wav_name(slot_start: float) -> str:
    """yymmdd_hhmm.wav: wsprd takes the date and time from the name (wsprd.c:966-967)."""
    return datetime.fromtimestamp(slot_start, timezone.utc).strftime("%y%m%d_%H%M.wav")


def write_wav(path: str, samples: np.ndarray) -> None:
    """16-bit mono 12 kHz with a plain 44-byte header, exactly 114 s.

    wsprd skips 22 shorts of header without reading it, then reads 114 * 12000
    samples (wsprd.c:146-147), so the rate is never checked: it must be 12 kHz.
    """
    want = WAV_SECONDS * RATE
    x = np.zeros(want, np.float32)
    n = min(want, len(samples))
    x[:n] = samples[:n]
    peak = float(np.max(np.abs(x))) if n else 0.0
    scale = 0.5 * 32767 / peak if peak > 0.5 else 32767
    pcm = np.clip(np.rint(x * scale), -32768, 32767).astype("<i2")
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(pcm.tobytes())


# --- transmit scheduling ---------------------------------------------------------------

def slot_of(t: float) -> int:
    return int(t // PERIOD)


class TxScheduler:
    """Which 2-minute slots transmit, at a given percentage.

    A summary port of WSJT-X WSPR/WsprTxScheduler.cpp: a table of 60 slots per
    2-hour block. At 25% or less it uses K1JT's random gaps (an average of
    100/pct - 1 receive slots between transmissions, lines 136-148); above
    that it places transmissions at random with at most one in a row below
    50% (two up to 60%, three above), and never in a block's first slot, so
    blocks never join into a double transmission (tx_trim). Deterministic for
    a given seed.
    """

    BLOCK = 60

    def __init__(self, percent: int = 20, seed: int | None = None):
        self.percent = max(0, min(100, int(percent)))
        self.seed = seed if seed is not None else random.randrange(1 << 30)
        self._tables: dict[int, list[int]] = {}

    def _table(self, block: int) -> list[int]:
        if block in self._tables:
            return self._tables[block]
        rng = random.Random(self.seed * 1_000_003 + block)
        pct = self.percent
        tx = [0] * self.BLOCK
        if pct >= 100:
            tx = [1] * self.BLOCK
        elif pct > 0 and pct <= 25:
            rxavg = 100.0 / pct - 1.0
            i = 0
            while True:
                x = rng.randrange(100) / 100.0
                i += int(rxavg + 3.0 * x - 1.0) + 1
                if i >= self.BLOCK:
                    break
                tx[i] = 1
        elif pct > 25:
            limit = 1 if pct < 50 else 2 if pct < 60 else 3
            needed = int(self.BLOCK * pct / 100 + 0.5)
            order = list(range(1, self.BLOCK))
            rng.shuffle(order)
            placed = 0
            for i in order:
                if placed >= needed:
                    break
                tx[i] = 1
                run = _run_through(tx, i)
                if run > limit:
                    tx[i] = 0
                    continue
                placed += 1
        if len(self._tables) > 8:
            self._tables.clear()
        self._tables[block] = tx
        return tx

    def transmit_in(self, slot: int) -> bool:
        return bool(self._table(slot // self.BLOCK)[slot % self.BLOCK])


def _run_through(tx: list[int], i: int) -> int:
    lo = i
    while lo > 0 and tx[lo - 1]:
        lo -= 1
    hi = i
    while hi < len(tx) - 1 and tx[hi + 1]:
        hi += 1
    return hi - lo + 1
