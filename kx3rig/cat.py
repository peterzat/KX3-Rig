"""Elecraft KX3 CAT protocol: command formatting, reply parsing, and an allow-list.

Pure functions only (no I/O), so everything here is unit-tested without a radio.
Source for every format: Elecraft "K3S/K3/KX3/KX2 Programmer's Reference" rev G5,
cross-checked against Hamlib 4.5.5 (see docs/references.md, "CAT protocol").

Safety: the transport refuses to send anything that does not match ALLOWED.
Commands that can transmit or reconfigure the radio (SWT/SWH switch emulation,
KY keying text, MN/MP menu writes, BR baud change, PS0 power off, UP/DN, which
edit an open menu, TX keying) are deliberately absent. Push-to-talk is the
Digirig's RTS line, which has a watchdog. RX; is allowed because it is the
safe stop.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

TERMINATOR = b";"
_ASCII_DIGITS = re.compile(r"[0-9]+")


def _digits_only(text: str) -> bool:
    """ASCII digits only; str.isdigit() also accepts superscripts like '\u00b2'."""
    return bool(_ASCII_DIGITS.fullmatch(text))


class Mode(Enum):
    LSB = 1
    USB = 2
    CW = 3
    FM = 4
    AM = 5
    DATA = 6
    CW_REV = 7
    DATA_REV = 9

    @property
    def label(self) -> str:
        return {
            Mode.LSB: "LSB",
            Mode.USB: "USB",
            Mode.CW: "CW",
            Mode.FM: "FM",
            Mode.AM: "AM",
            Mode.DATA: "DATA",
            Mode.CW_REV: "CW-R",
            Mode.DATA_REV: "DATA-R",
        }[self]

    @property
    def is_voice(self) -> bool:
        return self in (Mode.LSB, Mode.USB, Mode.AM, Mode.FM)

    @property
    def is_data(self) -> bool:
        return self in (Mode.DATA, Mode.DATA_REV)

    @property
    def is_cw(self) -> bool:
        return self in (Mode.CW, Mode.CW_REV)


class DataSubmode(Enum):
    DATA_A = 0   # sound-card data (FT8 and friends)
    AFSK_A = 1
    FSK_D = 2
    PSK_D = 3

    @property
    def label(self) -> str:
        return {0: "DATA A", 1: "AFSK A", 2: "FSK D", 3: "PSK D"}[self.value]


# Band numbers for BN (Programmer's Reference p.8).
BAND_NUMBERS = {
    0: "160m", 1: "80m", 2: "60m", 3: "40m", 4: "30m", 5: "20m",
    6: "17m", 7: "15m", 8: "12m", 9: "10m", 10: "6m",
}

# S-meter (SM, basic K30 scale 0-15) to dB relative to S9. The anchors at 6
# (S9), 9 (+20), 12 (+40), 15 (+60) are Elecraft's; values below S9 follow
# Hamlib's calibration table (elecraft.h K3_SM_CAL).
SM_DB_K30 = [-54, -42, -36, -24, -12, -6, 0, 10, 15, 20, 30, 35, 40, 50, 55, 60]


# --- Allow-list -----------------------------------------------------------------

ALLOWED = re.compile(
    r"^(?:"
    r"ID|OM|RVM|RVD|IF|TQ|SM|PO|SW|PC|MD|DT|BW|FA|FB|K2|K3|AI|PS|BN"  # GETs
    r"|FA\d{11}|MD[12345679]|DT[0-3]|BW\d{4}|PC\d{3}|BN(?:0\d|10)"  # SETs
    r"|K2[0-3]|AI[0-3]"                                             # restore meta state
    r"|RX"                                                          # stop transmitting
    r");$"
)


def is_allowed(command: str) -> bool:
    return bool(ALLOWED.match(command))


# --- Command builders -------------------------------------------------------------

def set_frequency(hz: int) -> str:
    if not 0 < hz < 100_000_000_000:
        raise ValueError(f"frequency out of range: {hz}")
    return f"FA{int(hz):011d};"


def set_mode(mode: Mode) -> str:
    return f"MD{mode.value};"


def set_data_submode(sub: DataSubmode) -> str:
    return f"DT{sub.value};"


def set_bandwidth(hz: int) -> str:
    tens = max(0, min(9999, round(hz / 10)))
    return f"BW{tens:04d};"


def set_band(number: int) -> str:
    """Band change through the radio's own band memory (BN, 00-10 = 160-6 m)."""
    if number not in BAND_NUMBERS:
        raise ValueError(f"no such band number: {number}")
    return f"BN{number:02d};"


def parse_bn(frame: str) -> int | None:
    return _digits(frame, "BN", 2)


def set_power(watts: float) -> str:
    """Basic-format power request, whole watts (K20 mode)."""
    w = max(0, min(15, int(round(watts))))
    return f"PC{w:03d};"


# --- Reply parsing ----------------------------------------------------------------

class FrameSplitter:
    """Accumulates serial bytes and yields complete ';'-terminated frames.

    Decodes as latin-1 because DS/IC replies carry bytes >= 0x80.
    Leading garbage (line noise, a partial frame from before we opened the
    port) stays attached to the first frame; parsers match by prefix and
    length, so it is simply ignored.
    """

    def __init__(self) -> None:
        self._buf = bytearray()

    def feed(self, data: bytes) -> list[str]:
        self._buf.extend(data)
        frames: list[str] = []
        while True:
            idx = self._buf.find(TERMINATOR)
            if idx < 0:
                break
            raw = bytes(self._buf[: idx + 1])
            del self._buf[: idx + 1]
            frames.append(raw.decode("latin-1").strip("\r\n\x00 "))
        if len(self._buf) > 4096:  # never grow without bound on a noisy line
            self._buf.clear()
        return frames


def frame_kind(frame: str) -> str:
    """The command letters of a reply frame, e.g. 'FA', 'IF', 'SM', '?'."""
    if frame == "?;":
        return "?"
    m = re.match(r"([A-Z][A-Z0-9])", frame)
    return m.group(1) if m else ""


def _digits(frame: str, prefix: str, width: int | None = None) -> int | None:
    if width is None:
        m = re.fullmatch(rf"{prefix}(\d+);", frame)
    else:
        m = re.fullmatch(rf"{prefix}(\d{{{width}}});", frame)
    return int(m.group(1)) if m else None


def parse_fa(frame: str) -> int | None:
    return _digits(frame, "FA", 11)


def parse_fb(frame: str) -> int | None:
    return _digits(frame, "FB", 11)


def parse_md(frame: str) -> Mode | None:
    v = _digits(frame, "MD", 1)
    try:
        return Mode(v) if v is not None else None
    except ValueError:
        return None


def parse_dt(frame: str) -> DataSubmode | None:
    v = _digits(frame, "DT", 1)
    try:
        return DataSubmode(v) if v is not None else None
    except ValueError:
        return None


def parse_bw(frame: str) -> int | None:
    """Filter bandwidth in Hz (reply is in 10 Hz units)."""
    v = _digits(frame, "BW", 4)
    return v * 10 if v is not None else None


def parse_pc(frame: str) -> float | None:
    """Requested power in watts. Handles basic PCnnn and K22 PCnnnx forms."""
    m = re.fullmatch(r"PC(\d{3})([01])?;", frame)
    if not m:
        return None
    value = int(m.group(1))
    if m.group(2) == "0":  # K22 low range: tenths of a watt
        return value / 10.0
    return float(value)


def parse_po(frame: str) -> float | None:
    """Actual output power estimate in watts (KX3 reports tenths)."""
    v = _digits(frame, "PO", 3)
    return v / 10.0 if v is not None else None


def parse_sw(frame: str) -> float | None:
    """SWR (reply is SWR x 10, firmware 2.93+)."""
    v = _digits(frame, "SW", 3)
    return v / 10.0 if v is not None else None


def parse_sm(frame: str) -> int | None:
    return _digits(frame, "SM", 4)


def parse_tq(frame: str) -> bool | None:
    v = _digits(frame, "TQ", 1)
    return None if v is None else v == 1


def parse_k2(frame: str) -> int | None:
    return _digits(frame, "K2", 1)


def parse_k3(frame: str) -> int | None:
    return _digits(frame, "K3", 1)


def parse_ai(frame: str) -> int | None:
    return _digits(frame, "AI", 1)


def parse_id(frame: str) -> int | None:
    return _digits(frame, "ID", 3)


def parse_rv(frame: str) -> float | None:
    """Firmware revision from an RVM/RVD reply, e.g. 'RVM02.93;' -> 2.93."""
    m = re.fullmatch(r"RV[MD](\d+\.\d+);?", frame)
    return float(m.group(1)) if m else None


@dataclass(frozen=True)
class Options:
    product_id: int
    atu: bool        # KXAT3 internal tuner
    pa100: bool      # KXPA100 amplifier
    roofing: bool    # KXFL3 roofing filter
    battery: bool    # KXBC3 charger

    @property
    def is_kx3(self) -> bool:
        return self.product_id == 2


def parse_om(frame: str) -> Options | None:
    """OM reply, KX3 format 'OM APF---TBXI02;' (fixed offsets, '-' when absent)."""
    if not frame.startswith("OM") or len(frame) != 16 or not frame.endswith(";"):
        return None
    body = frame
    pid = body[13:15]
    if not _digits_only(pid):
        return None
    return Options(
        product_id=int(pid),
        atu=body[3] == "A",
        pa100=body[4] == "P",
        roofing=body[5] == "F",
        battery=body[10] == "B",
    )


@dataclass(frozen=True)
class Info:
    """The IF reply: frequency, mode, and transmit/split state in one frame."""

    frequency: int
    rit_offset: int
    rit_on: bool
    xit_on: bool
    transmitting: bool
    mode: Mode | None
    vfo_b_rx: bool
    split: bool


def parse_if(frame: str) -> Info | None:
    """IF reply, 38 bytes: IF[f]*****+yyyyrx*00tmvspbd1*; (Programmer's Ref p.14)."""
    if len(frame) != 38 or not frame.startswith("IF") or frame[37] != ";":
        return None
    freq = frame[2:13]
    sign, offset = frame[18], frame[19:23]
    if not _digits_only(freq) or sign not in "+- " or not _digits_only(offset):
        return None
    try:
        mode = Mode(int(frame[29]))
    except ValueError:
        mode = None
    off = int(offset) * (-1 if sign == "-" else 1)
    return Info(
        frequency=int(freq),
        rit_offset=off,
        rit_on=frame[23] == "1",
        xit_on=frame[24] == "1",
        transmitting=frame[28] == "1",
        mode=mode,
        vfo_b_rx=frame[30] == "1",
        split=frame[32] == "1",
    )


def smeter_db(raw: int, k31: bool = False) -> float:
    """S-meter reading as dB relative to S9."""
    if k31:
        # K31 scale 0-21: S9 = 9, +20 = 13, +40 = 17, +60 = 21 (5 dB per count above S9).
        if raw >= 9:
            return (raw - 9) * 5.0
        return (raw - 9) * 6.0
    raw = max(0, min(15, raw))
    return float(SM_DB_K30[raw])


def smeter_label(db_over_s9: float) -> str:
    """'S5', 'S9', 'S9+20' style label (6 dB per S-unit below S9)."""
    if db_over_s9 >= 5:
        return f"S9+{int(round(db_over_s9 / 10.0) * 10)}"
    s = 9 + int(round(db_over_s9 / 6.0))
    return f"S{max(0, s)}"
