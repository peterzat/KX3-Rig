"""Understand decoded FT8 messages well enough to run a contact.

Standard FT8 exchanges (WSJT-X User Guide 10.1):

    CQ K1ABC FN42          a CQ, optionally "CQ DX ...", "CQ POTA ..."
    K1ABC G0XYZ IO91       answer with grid       (Tx1)
    G0XYZ K1ABC -19        signal report          (Tx2)
    K1ABC G0XYZ R-22       roger + report         (Tx3)
    G0XYZ K1ABC RR73       roger, 73              (Tx4, or RRR)
    K1ABC G0XYZ 73         sign-off               (Tx5)

Anything that does not fit is kept as free text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

GRID_RE = re.compile(r"^[A-R]{2}[0-9]{2}$")
REPORT_RE = re.compile(r"^[+-]\d{2}$")
ROGER_REPORT_RE = re.compile(r"^R[+-]\d{2}$")
# Loose amateur callsign shape: optional prefix/, a digit somewhere, optional /suffix.
# "<...>" is a hashed call the decoder could not resolve.
CALL_RE = re.compile(r"^(?:<\.\.\.>|<?(?:[A-Z0-9]{1,4}/)?[A-Z0-9]*\d[A-Z0-9]*[A-Z](?:/[A-Z0-9]{1,4})?>?)$")


def base_call(call: str) -> str:
    """K1ABC from '<K1ABC>', 'PJ4/K1ABC', 'K1ABC/P'."""
    call = call.strip("<>").upper()
    if "/" in call:
        parts = call.split("/")
        call = max(parts, key=lambda p: (any(c.isdigit() for c in p) and any(c.isalpha() for c in p), len(p)))
    return call


def same_call(a: str | None, b: str | None) -> bool:
    if not a or not b or a == "<...>" or b == "<...>":
        return False
    return base_call(a) == base_call(b)


@dataclass(frozen=True)
class Message:
    text: str
    is_cq: bool = False
    cq_modifier: str = ""      # "DX", "POTA", ... when present
    to: str = ""               # first callsign (addressee)
    de: str = ""               # second callsign (sender)
    grid: str = ""
    report: int | None = None  # plain report: -12
    roger_report: int | None = None  # R-12
    rrr: bool = False
    rr73: bool = False
    seventy_three: bool = False
    free_text: bool = False

    @property
    def sender(self) -> str:
        return self.de

    def addressed_to(self, call: str) -> bool:
        return not self.is_cq and same_call(self.to, call)


def parse(text: str) -> Message:
    t = " ".join(text.upper().split())
    words = t.split(" ")
    if not t:
        return Message(text=t, free_text=True)
    if words[0] == "CQ" and len(words) >= 2:
        rest = words[1:]
        modifier = ""
        if len(rest) >= 2 and not CALL_RE.match(rest[0]) or (len(rest) >= 3):
            modifier, rest = rest[0], rest[1:]
        if not rest or not CALL_RE.match(rest[0]):
            return Message(text=t, free_text=True)
        grid = rest[1] if len(rest) > 1 and GRID_RE.match(rest[1]) and rest[1] != "RR73" else ""
        return Message(text=t, is_cq=True, cq_modifier=modifier, de=rest[0], grid=grid)
    if len(words) in (2, 3) and CALL_RE.match(words[0]) and CALL_RE.match(words[1]):
        msg = dict(text=t, to=words[0], de=words[1])
        if len(words) == 3:
            x = words[2]
            if x == "RR73":
                msg["rr73"] = True
            elif x == "RRR":
                msg["rrr"] = True
            elif x == "73":
                msg["seventy_three"] = True
            elif GRID_RE.match(x):
                msg["grid"] = x
            elif REPORT_RE.match(x):
                msg["report"] = int(x)
            elif ROGER_REPORT_RE.match(x):
                msg["roger_report"] = int(x[1:])
            else:
                return Message(text=t, free_text=True)
        return Message(**msg)
    return Message(text=t, free_text=True)


def format_report(snr: int) -> str:
    """WSJT-X %+2.2d: -12, +05, +00; clamped to the packable range -50..+49."""
    snr = max(-50, min(49, int(snr)))
    return f"{snr:+03d}"
