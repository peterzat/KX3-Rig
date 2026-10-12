"""Contact log in ADIF, the format every logbook (LoTW, QRZ, Log4OM) imports.

Fields follow what WSJT-X writes for an FT8 contact (logbook/logbook.cpp).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone

from .. import __version__


@dataclass(frozen=True)
class LogEntry:
    call: str
    grid: str
    rst_sent: int | str | None      # FT8 report in dB, or an RST such as "599"
    rst_rcvd: int | str | None
    time_on: datetime
    time_off: datetime
    band: str            # "20m"
    dial_hz: int
    station_call: str
    my_grid: str
    tx_power_w: float | None = None
    mode: str = "FT8"
    submode: str = ""    # ADIF puts FT4 under MFSK and PSK31 under PSK
    name: str = ""
    comment: str = ""


def _field(name: str, value) -> str:
    text = str(value)
    return f"<{name}:{len(text)}>{text} "


def _report(value: int | str | None) -> str:
    if isinstance(value, str):
        return value.strip()
    return "" if value is None else f"{value:+03d}"


def record(e: LogEntry) -> str:
    on = e.time_on.astimezone(timezone.utc)
    off = e.time_off.astimezone(timezone.utc)
    parts = [
        _field("call", e.call),
        _field("gridsquare", e.grid) if e.grid else "",
        _field("mode", e.mode),
        _field("submode", e.submode) if e.submode else "",
        _field("rst_sent", _report(e.rst_sent)) if e.rst_sent is not None else "",
        _field("rst_rcvd", _report(e.rst_rcvd)) if e.rst_rcvd is not None else "",
        _field("qso_date", on.strftime("%Y%m%d")),
        _field("time_on", on.strftime("%H%M%S")),
        _field("qso_date_off", off.strftime("%Y%m%d")),
        _field("time_off", off.strftime("%H%M%S")),
        _field("band", e.band),
        _field("freq", f"{e.dial_hz / 1e6:.6f}"),
        _field("station_callsign", e.station_call),
        _field("my_gridsquare", e.my_grid) if e.my_grid else "",
        _field("tx_pwr", f"{e.tx_power_w:g}") if e.tx_power_w else "",
        _field("name", e.name) if e.name else "",
        _field("comment", e.comment) if e.comment else "",
    ]
    return "".join(p for p in parts if p) + "<eor>\n"


def header(now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    return (
        "KX3-Rig contact log\n"
        + _field("adif_ver", "3.1.4")
        + _field("created_timestamp", now.strftime("%Y%m%d %H%M%S"))
        + _field("programid", "KX3-Rig")
        + _field("programversion", __version__)
        + "<eoh>\n"
    )


def append(path: str, entry: LogEntry) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    new = not os.path.exists(path) or os.path.getsize(path) == 0
    with open(path, "a", encoding="utf-8") as f:
        if new:
            f.write(header())
        f.write(record(entry))


def worked(path: str) -> set[tuple[str, str]]:
    """(CALL, band) for every contact in the log, for marking stations not worked before."""
    import re

    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return set()
    out = set()
    for rec in text.split("<eor>")[:-1] if "<eor>" in text else []:
        call = re.search(r"<call:(\d+)>", rec, re.I)
        band = re.search(r"<band:(\d+)>", rec, re.I)
        if call:
            c = rec[call.end():call.end() + int(call.group(1))].upper()
            b = rec[band.end():band.end() + int(band.group(1))].lower() if band else ""
            out.add((c, b))
    return out


def count(path: str) -> int:
    try:
        with open(path, encoding="utf-8") as f:
            return f.read().lower().count("<eor>")
    except OSError:
        return 0
