"""FT8 and FT4: what differs between the two, in one place.

Both use the same messages, the same contact sequence (WSJT-X's Tx1 to Tx6;
FT4 always sends RR73), the same 77-bit packing, and jt9 for decoding. They
differ in timing, bandwidth, the jt9 mode flag, and the waveform. Sources: the
module docstrings of encode.py (FT8) and ft4.py (FT4).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

from .. import bandplan
from . import encode, ft4
from .decode import RATE, RawDecode, parse_jt9_line


@dataclass(frozen=True)
class Protocol:
    name: str
    period: float            # seconds per transmit/receive period
    tx_start_s: float        # audio starts this long after the period boundary
    decode_at_s: float       # start jt9 this far into the period
    decode_seconds: float    # how much audio jt9 reads
    max_late_s: float        # start a late transmission (skipping its start) up to here
    signal_width_hz: int
    jt9_flag: str
    dials: dict[str, int]    # band name -> dial frequency, Hz
    tones: Callable[[str], tuple[int, ...]]
    waveform: Callable[..., np.ndarray]
    parse: Callable[[str], RawDecode | None]
    adif_mode: str           # ADIF MODE and SUBMODE
    adif_submode: str = ""

    def slot_of(self, t: float) -> int:
        return int(t // self.period)

    def slot_start(self, slot: int) -> float:
        return slot * self.period

    def dial(self, band: bandplan.Band) -> int | None:
        return self.dials.get(band.name)

    def band_on_dial(self, hz: int) -> bandplan.Band | None:
        band = bandplan.band_for(hz)
        dial = self.dial(band) if band else None
        return band if dial is not None and abs(hz - dial) < 500 else None

    @property
    def bands(self) -> list[bandplan.Band]:
        return [b for b in bandplan.BANDS if b.name in self.dials]


def _ft8_tones(text: str) -> tuple[int, ...]:
    return encode.encode(text).tones


def _ft4_tones(text: str) -> tuple[int, ...]:
    return ft4.encode(text).tones


FT8 = Protocol(
    name="FT8", period=15.0, tx_start_s=encode.TX_START_S, decode_at_s=13.4, decode_seconds=15.0,
    max_late_s=3.0, signal_width_hz=50, jt9_flag="-8",
    dials={b.name: b.ft8 for b in bandplan.BANDS if b.name != "60m"},
    tones=_ft8_tones, waveform=encode.waveform, parse=parse_jt9_line, adif_mode="FT8",
)

# jt9 needs 6.048 s of an FT4 period; decoding at 6.2 s leaves about 1.3 s for
# jt9 and the reply before the next period's 0.3 s start.
FT4 = Protocol(
    name="FT4", period=ft4.PERIOD, tx_start_s=ft4.TX_START_S, decode_at_s=6.2,
    decode_seconds=ft4.DECODE_SAMPLES / RATE, max_late_s=1.0, signal_width_hz=ft4.SIGNAL_WIDTH_HZ,
    jt9_flag="-5", dials=dict(ft4.DIALS), tones=_ft4_tones, waveform=ft4.waveform,
    parse=ft4.parse_jt9_ft4_line, adif_mode="MFSK", adif_submode="FT4",
)

PROTOCOLS = {p.name: p for p in (FT8, FT4)}
