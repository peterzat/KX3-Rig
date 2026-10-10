"""FT8: message logic, WSJT-X encode/decode, and contact sequencing."""

from __future__ import annotations

import functools

import numpy as np

from . import encode as _encode

# Demo mode: the last message we transmitted, so simulated stations can answer it.
demo_last_tx: str = ""
demo_last_tx_slot: int = -10


@functools.lru_cache(maxsize=64)
def _tones(text: str) -> tuple[int, ...]:
    return _encode.encode(text).tones


def synthesize(text: str, offset_hz: float, rate: int) -> np.ndarray:
    """FT8 waveform for a message at an audio offset (unit amplitude)."""
    return _encode.waveform(_tones(text), rate, offset_hz)


# A small, believable band: CQs in even periods, exchanges in odd periods.
_DEMO_EVEN = [
    ("CQ W7DEM CN85", 1180, -9),
    ("CQ DX K9ZZX EN52", 640, -17),
    ("CQ VE7QRP CN89", 2240, -4),
    ("N5ABC WA6XYZ R-12", 1720, -14),
]
_DEMO_ODD = [
    ("CQ N7FTE CN87", 905, -6),
    ("WA6XYZ N5ABC RR73", 1450, -11),
    ("CQ POTA KE7PRK DN07", 2010, -15),
    ("K9ZZX JA1ABC PM95", 1330, -20),
]

def _demo_reply(slot: int) -> list[tuple[str, float, float]]:
    """Simulated stations answering our last transmission, one period later."""
    if not demo_last_tx or slot != demo_last_tx_slot + 1:
        return []
    words = demo_last_tx.split()
    if words[0] == "CQ" and len(words) >= 2:
        return [(f"{words[1]} N7DEM CN86", 1610, -8)]
    if len(words) != 3:
        return []
    dx, me, x = words
    if x.startswith("R") and x not in ("RR73", "RRR"):
        return [(f"{me} {dx} RR73", 1610, -7)]
    if x == "RR73":
        return [(f"{me} {dx} 73", 1610, -7)]
    if x[0] in "+-":
        return [(f"{me} {dx} R-07", 1610, -7)]
    if x != "73":
        return [(f"{me} {dx} -11", 1180, -9)]
    return []


def demo_messages(slot: int) -> list[tuple[str, float, float]]:
    base = _DEMO_EVEN if slot % 2 == 0 else _DEMO_ODD
    rng = np.random.default_rng(slot)
    picked = [m for m in base if rng.random() < 0.8]
    replies = _demo_reply(slot)
    if replies:
        # The replying station takes the place of whoever was on its frequency.
        picked = [m for m in picked if abs(m[1] - replies[0][1]) > 100] + replies
    return [(t, f + rng.uniform(-3, 3), snr + rng.uniform(-2, 2)) for t, f, snr in picked]
