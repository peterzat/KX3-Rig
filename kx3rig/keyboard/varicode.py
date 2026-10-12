"""PSK31 Varicode: G3PLX's variable-length character code.

The table is copied from fldigi's src/psk/pskvaricode.cxx (varicodetab1,
entries 0-127; Dave Freese W1HKJ, adapted from gmfsk; GPLv3), fetched
2026-10-12 from
https://raw.githubusercontent.com/w1hkj/fldigi/master/src/psk/pskvaricode.cxx

Every code starts and ends with 1 and never contains "00", so two zeros in a
row always mark the gap between characters (G3PLX, "PSK31: A new radio-
teletype mode", RadCom Dec 1998/Jan 1999).
"""

from __future__ import annotations

CODES: tuple[str, ...] = (
    "1010101011", "1011011011", "1011101101", "1101110111", "1011101011", "1101011111", "1011101111",
    "1011111101", "1011111111", "11101111", "11101", "1101101111", "1011011101", "11111", "1101110101",
    "1110101011", "1011110111", "1011110101", "1110101101", "1110101111", "1101011011", "1101101011",
    "1101101101", "1101010111", "1101111011", "1101111101", "1110110111", "1101010101", "1101011101",
    "1110111011", "1011111011", "1101111111", "1", "111111111", "101011111", "111110101", "111011011",
    "1011010101", "1010111011", "101111111", "11111011", "11110111", "101101111", "111011111", "1110101",
    "110101", "1010111", "110101111", "10110111", "10111101", "11101101", "11111111", "101110111",
    "101011011", "101101011", "110101101", "110101011", "110110111", "11110101", "110111101",
    "111101101", "1010101", "111010111", "1010101111", "1010111101", "1111101", "11101011", "10101101",
    "10110101", "1110111", "11011011", "11111101", "101010101", "1111111", "111111101", "101111101",
    "11010111", "10111011", "11011101", "10101011", "11010101", "111011101", "10101111", "1101111",
    "1101101", "101010111", "110110101", "101011101", "101110101", "101111011", "1010101101",
    "111110111", "111101111", "111111011", "1010111111", "101101101", "1011011111", "1011", "1011111",
    "101111", "101101", "11", "111101", "1011011", "101011", "1101", "111101011", "10111111", "11011",
    "111011", "1111", "111", "111111", "110111111", "10101", "10111", "101", "110111", "1111011",
    "1101011", "11011111", "1011101", "111010101", "1010110111", "110111011", "1010110101",
    "1011010111", "1110110101",
)

_DECODE = {code: chr(i) for i, code in enumerate(CODES)}
MAX_CODE = max(len(c) for c in CODES)


def encode(text: str) -> str:
    """The bit string for text, "00" after each character. Characters outside
    7-bit ASCII are skipped (they have no Varicode)."""
    return "".join(CODES[ord(ch)] + "00" for ch in text if ord(ch) < 128)


class Decoder:
    """Turns received bits back into characters, one bit at a time."""

    def __init__(self) -> None:
        self._bits = ""

    def reset(self) -> None:
        self._bits = ""

    def push(self, bit: int | str) -> str | None:
        self._bits += "1" if bit in (1, "1", True) else "0"
        if self._bits.endswith("00"):
            code = self._bits[:-2].lstrip("0")
            self._bits = ""
            return _DECODE.get(code) if code else None
        if len(self._bits) > MAX_CODE + 2:
            self._bits = ""        # no gap for too long: not Varicode, start over
        return None
