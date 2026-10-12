"""Which bands are open from here, right now: an at-a-glance outlook.

Sources (docs/references.md, "Smartscan"):

* PSKReporter: reception reports from stations in our grid square over the
  last 15 minutes. That is a direct measurement: if receivers around CN87 are
  hearing 60 stations on 20 m, 20 m is open from Seattle. It is mostly FT8,
  heard on other people's antennas, so it says where to hunt, not what the
  loop will hear. The service asks for no more than one query every five
  minutes.
* NOAA SWPC: the estimated planetary K index (geomagnetic activity), as
  context. A storm explains fading and closed high bands; it does not
  override the measurement.
* The sun's elevation at our grid, computed here: day, night, or greyline.

Parsing and grading are pure functions; fetch() is the only network code and
runs on a worker thread.
"""

from __future__ import annotations

import gzip
import io
import json
import math
import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass

from .. import __version__, bandplan
from ..ft8 import grid as maidenhead

DEFAULT_GRID = "CN87"            # Seattle, used until Preferences has a grid
PSKREPORTER_URL = "https://retrieve.pskreporter.info/query"
KP_URL = "https://services.swpc.noaa.gov/json/planetary_k_index_1m.json"
WINDOW_S = 900
PSKREPORTER_EVERY_S = 300        # "no more often than once every five minutes"
KP_EVERY_S = 900
MAX_BYTES = 4_000_000
USER_AGENT = f"KX3-Rig/{__version__} (+https://github.com/peterzat/KX3-Rig)"

OPEN_SENDERS = 5                 # this many distinct stations heard nearby: open
DX_KM = 3_000                    # or a couple heard from this far: open

OPEN, FAIR, QUIET, UNKNOWN = "open", "fair", "quiet", "unknown"
LEVEL_TEXT = {OPEN: "Open", FAIR: "Some activity", QUIET: "Quiet", UNKNOWN: "No reports"}

_GRID4 = re.compile(r"^[A-R]{2}[0-9]{2}$")


@dataclass(frozen=True)
class Report:
    sender: str
    sender_grid: str
    receiver: str
    frequency: int
    mode: str
    when: int
    where: str                   # sender's country (DXCC), for "as far as Japan"


@dataclass(frozen=True)
class BandOutlook:
    band: bandplan.Band
    level: str
    senders: int = 0
    receivers: int = 0
    reports: int = 0
    farthest_km: float = 0.0
    farthest_where: str = ""

    def tooltip(self, grid: str) -> str:
        if self.level == UNKNOWN:
            return f"{self.band.label}: no reports yet"
        if not self.senders:
            return f"{self.band.label}: nothing heard near {grid} in the last 15 minutes"
        text = (f"{self.band.label}: {LEVEL_TEXT[self.level]}. {self.senders} station{'s' if self.senders != 1 else ''} "
                f"heard by {self.receivers} near {grid} in the last 15 minutes")
        if self.farthest_where:
            text += f", as far as {self.farthest_where} ({self.farthest_km:,.0f} km)"
        return text + "."


# --- parsing --------------------------------------------------------------------------

def grid4(grid: str) -> str:
    g = (grid or "").strip()[:4].upper()
    return g if _GRID4.match(g) else DEFAULT_GRID


def pskreporter_url(grid: str) -> str:
    query = {
        "receiverCallsign": grid4(grid),
        "modify": "grid",            # the "callsign" is a grid square prefix
        "flowStartSeconds": -WINDOW_S,
        "rronly": 1,                 # reception reports only
        "noactive": 1,               # not the list of active monitors
    }
    return f"{PSKREPORTER_URL}?{urllib.parse.urlencode(query)}"


def parse_pskreporter(xml_bytes: bytes) -> list[Report]:
    root = ET.fromstring(xml_bytes)
    out = []
    for el in root.iter("receptionReport"):
        a = el.attrib
        try:
            freq = int(a.get("frequency", "0"))
            when = int(a.get("flowStartSeconds", "0"))
        except ValueError:
            continue
        sender = a.get("senderCallsign", "").strip().upper()
        if not sender or freq <= 0:
            continue
        out.append(Report(sender, a.get("senderLocator", "").strip(), a.get("receiverCallsign", "").strip().upper(),
                          freq, a.get("mode", ""), when, a.get("senderDXCC", "").strip()))
    return out


def parse_kp(json_bytes: bytes) -> float | None:
    """Latest estimated planetary K from SWPC's 1-minute product."""
    rows = json.loads(json_bytes)
    if not isinstance(rows, list):
        return None
    for row in reversed(rows):
        if isinstance(row, dict):
            for key in ("estimated_kp", "kp_index"):
                value = row.get(key)
                if isinstance(value, (int, float)) and math.isfinite(value):
                    return float(value)
    return None


def _grid_for_distance(locator: str) -> str:
    g = locator.strip()
    return g[:6] if len(g) >= 6 else g[:4]


def grade(reports: list[Report], my_grid: str, now: float | None = None) -> dict[str, BandOutlook]:
    """Per-band outlook from reception reports heard near my_grid."""
    now = time.time() if now is None else now
    me = grid4(my_grid)
    by_band: dict[str, list[Report]] = {}
    for r in reports:
        if now - r.when > WINDOW_S + 120:
            continue
        band = bandplan.band_for(r.frequency)
        if band is not None:
            by_band.setdefault(band.name, []).append(r)
    any_reports = bool(by_band)
    out: dict[str, BandOutlook] = {}
    for band in bandplan.BANDS:
        rs = by_band.get(band.name, [])
        if not rs:
            # With no reports on any band, the monitors may simply be off: say
            # "unknown" rather than calling every band closed.
            out[band.name] = BandOutlook(band, QUIET if any_reports else UNKNOWN)
            continue
        senders = {r.sender for r in rs}
        far_km, far_where = 0.0, ""
        for r in rs:
            km = maidenhead.distance_km(me, _grid_for_distance(r.sender_grid)) if r.sender_grid else None
            if km is not None and km > far_km:
                far_km, far_where = km, r.where
        dx = len(senders) >= 2 and far_km >= DX_KM
        level = OPEN if len(senders) >= OPEN_SENDERS or dx else FAIR
        out[band.name] = BandOutlook(band, level, len(senders), len({r.receiver for r in rs}), len(rs),
                                     far_km, far_where)
    return out


# --- the sun --------------------------------------------------------------------------

def sun_elevation(lat: float, lon: float, when: float) -> float:
    """Solar elevation in degrees (NOAA approximation, about a degree)."""
    t = time.gmtime(when)
    day = t.tm_yday
    hours = t.tm_hour + t.tm_min / 60 + t.tm_sec / 3600
    decl = math.radians(23.44) * math.sin(2 * math.pi * (284 + day) / 365)
    b = 2 * math.pi * (day - 81) / 364
    eot = 9.87 * math.sin(2 * b) - 7.53 * math.cos(b) - 1.5 * math.sin(b)   # minutes
    solar_minutes = hours * 60 + eot + 4 * lon
    hour_angle = math.radians(solar_minutes / 4 - 180)
    phi = math.radians(lat)
    s = math.sin(phi) * math.sin(decl) + math.cos(phi) * math.cos(decl) * math.cos(hour_angle)
    return math.degrees(math.asin(max(-1.0, min(1.0, s))))


def daylight(grid: str, when: float | None = None) -> str:
    """'day', 'night', or 'greyline' at the grid's center."""
    pos = maidenhead.to_latlon(grid4(grid))
    if pos is None:
        return "day"
    elev = sun_elevation(pos[0], pos[1], time.time() if when is None else when)
    if elev > 6:
        return "day"
    if elev < -6:
        return "night"
    return "greyline"


# --- summary --------------------------------------------------------------------------

def kp_text(kp: float | None) -> str:
    if kp is None:
        return ""
    if kp >= 5:
        return f"Geomagnetic storm (Kp {kp:.0f}): expect fading, especially on the high bands"
    if kp >= 4:
        return f"Unsettled geomagnetic field (Kp {kp:.0f})"
    return f"Quiet geomagnetic field (Kp {kp:.0f})"


SUN_TEXT = {"day": "Daytime", "night": "Night", "greyline": "Greyline (sunrise or sunset)"}


def summary(outlook: dict[str, BandOutlook] | None, current: bandplan.Band | None, grid: str,
            kp: float | None, sun: str) -> tuple[str, str]:
    """(headline, details) in plain words for the Smartscan panel."""
    g = grid4(grid)
    context = " · ".join(t for t in (kp_text(kp), SUN_TEXT.get(sun, "")) if t)
    if not outlook:
        return f"Checking which bands are open near {g}…", context
    known = [o for o in outlook.values() if o.level != UNKNOWN]
    if not known:
        return f"No reports from stations near {g} in the last 15 minutes.", context
    ranked = sorted((o for o in known if o.senders), key=lambda o: o.senders, reverse=True)
    open_bands = [o for o in ranked if o.level == OPEN]
    here = outlook.get(current.name) if current else None
    if here and here.level == OPEN:
        head = f"{here.band.label} is open: {here.senders} stations heard near {g} in the last 15 minutes"
        head += f", as far as {here.farthest_where}." if here.farthest_where else "."
    elif open_bands:
        names = [o.band.label for o in open_bands[:3]]
        listed = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]
        where = current.label if current else "This band"
        state = "quiet" if not here or not here.senders else "slow"
        head = f"{where} is {state} near {g}. Best now: {listed}."
    else:
        head = f"Bands are slow near {g}: " + (
            f"most activity on {ranked[0].band.label}." if ranked else "nothing heard in the last 15 minutes.")
    return head, context


# --- network ----------------------------------------------------------------------------

def fetch(url: str, timeout: float = 20.0) -> bytes:
    """GET a URL (gzip accepted), refusing anything over MAX_BYTES."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept-Encoding": "gzip"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise ValueError("response too large")
        if response.headers.get("Content-Encoding", "").lower() == "gzip":
            with gzip.GzipFile(fileobj=io.BytesIO(raw)) as z:
                raw = z.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES:
                raise ValueError("response too large")
        return raw
