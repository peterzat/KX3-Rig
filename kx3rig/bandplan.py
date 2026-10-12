"""US amateur bands, license-class privileges, and standard frequencies.

Sources (captured in docs/references.md): 47 CFR Part 97 (97.301, 97.305,
97.307, eCFR current 2026-10-06), the ARRL band chart, the WSJT-X default
frequency list (FT8 dial frequencies), and the KX3 Owner's Manual (sideband
conventions, BN band numbers from the Programmer's Reference).

The KX3 itself only blocks transmit outside the ham bands, so license-class
sub-band enforcement lives here. 60 m is receive-only in this app for now: its
channel/segment rules and ERP limits need more care than v1 gives them, and the
station's AlexLoop does not reach 60 m anyway.
"""

from __future__ import annotations

from dataclasses import dataclass

from .cat import Mode

CW, DATA, PHONE = "cw", "data", "phone"


@dataclass(frozen=True)
class Band:
    name: str          # "20m"
    number: int        # KX3 BN band number
    low: int           # US allocation edges, Hz
    high: int
    lower_sideband: bool   # conventional voice sideband (LSB below 10 MHz except 60 m)
    ft8: int           # FT8 dial frequency (USB), Hz
    voice: int         # a sensible place to land for voice (QRP/SSB calling or activity)

    @property
    def label(self) -> str:
        return self.name.replace("m", " m")

    @property
    def voice_mode(self) -> Mode:
        return Mode.LSB if self.lower_sideband else Mode.USB

    def contains(self, hz: int) -> bool:
        return self.low <= hz <= self.high


BANDS: list[Band] = [
    Band("160m", 0, 1_800_000, 2_000_000, True, 1_840_000, 1_910_000),
    Band("80m", 1, 3_500_000, 4_000_000, True, 3_573_000, 3_985_000),
    Band("60m", 2, 5_330_500, 5_406_500, False, 5_357_000, 5_357_000),
    Band("40m", 3, 7_000_000, 7_300_000, True, 7_074_000, 7_285_000),
    Band("30m", 4, 10_100_000, 10_150_000, False, 10_136_000, 10_136_000),
    Band("20m", 5, 14_000_000, 14_350_000, False, 14_074_000, 14_285_000),
    Band("17m", 6, 18_068_000, 18_168_000, False, 18_100_000, 18_150_000),
    Band("15m", 7, 21_000_000, 21_450_000, False, 21_074_000, 21_385_000),
    Band("12m", 8, 24_890_000, 24_990_000, False, 24_915_000, 24_950_000),
    Band("10m", 9, 28_000_000, 29_700_000, False, 28_074_000, 28_385_000),
    Band("6m", 10, 50_000_000, 54_000_000, False, 50_313_000, 50_125_000),
]

BY_NAME = {b.name: b for b in BANDS}


def band_for(hz: int) -> Band | None:
    return next((b for b in BANDS if b.contains(hz)), None)


def nearest_band(hz: int) -> Band:
    """The band containing hz, or the closest band edge to it."""
    inside = band_for(hz)
    if inside:
        return inside
    return min(BANDS, key=lambda b: min(abs(hz - b.low), abs(hz - b.high)))


@dataclass(frozen=True)
class Segment:
    low: int
    high: int
    kinds: frozenset[str]


def _seg(low_mhz: float, high_mhz: float, *kinds: str) -> Segment:
    return Segment(round(low_mhz * 1e6), round(high_mhz * 1e6), frozenset(kinds))


# CW is allowed anywhere the class has privileges (97.305(a)), so phone
# segments also carry CW.
GENERAL = [
    _seg(1.800, 2.000, CW, DATA, PHONE),
    _seg(3.525, 3.600, CW, DATA),
    _seg(3.800, 4.000, CW, PHONE),
    _seg(7.025, 7.125, CW, DATA),
    _seg(7.175, 7.300, CW, PHONE),
    _seg(10.100, 10.150, CW, DATA),
    _seg(14.025, 14.150, CW, DATA),
    _seg(14.225, 14.350, CW, PHONE),
    _seg(18.068, 18.110, CW, DATA),
    _seg(18.110, 18.168, CW, PHONE),
    _seg(21.025, 21.200, CW, DATA),
    _seg(21.275, 21.450, CW, PHONE),
    _seg(24.890, 24.930, CW, DATA),
    _seg(24.930, 24.990, CW, PHONE),
    _seg(28.000, 28.300, CW, DATA),
    _seg(28.300, 29.700, CW, PHONE),
    _seg(50.000, 50.100, CW),
    _seg(50.100, 54.000, CW, DATA, PHONE),
]

EXTRA = [
    _seg(1.800, 2.000, CW, DATA, PHONE),
    _seg(3.500, 3.600, CW, DATA),
    _seg(3.600, 4.000, CW, PHONE),
    _seg(7.000, 7.125, CW, DATA),
    _seg(7.125, 7.300, CW, PHONE),
    _seg(10.100, 10.150, CW, DATA),
    _seg(14.000, 14.150, CW, DATA),
    _seg(14.150, 14.350, CW, PHONE),
    _seg(18.068, 18.110, CW, DATA),
    _seg(18.110, 18.168, CW, PHONE),
    _seg(21.000, 21.200, CW, DATA),
    _seg(21.200, 21.450, CW, PHONE),
    _seg(24.890, 24.930, CW, DATA),
    _seg(24.930, 24.990, CW, PHONE),
    _seg(28.000, 28.300, CW, DATA),
    _seg(28.300, 29.700, CW, PHONE),
    _seg(50.000, 50.100, CW),
    _seg(50.100, 54.000, CW, DATA, PHONE),
]

TECHNICIAN = [
    _seg(3.525, 3.600, CW),
    _seg(7.025, 7.125, CW),
    _seg(21.025, 21.200, CW),
    _seg(28.000, 28.300, CW, DATA),
    _seg(28.300, 28.500, CW, PHONE),
    _seg(50.000, 50.100, CW),
    _seg(50.100, 54.000, CW, DATA, PHONE),
]

PRIVILEGES = {"General": GENERAL, "Extra": EXTRA, "Technician": TECHNICIAN}

# FM's modulation-index limit below 29.0 MHz (97.307(f)) rules out normal 5 kHz
# deviation FM there, so FM transmit is only offered from 29.0 MHz up.
FM_MIN_HZ = 29_000_000


def emission_kind(mode: Mode) -> str:
    if mode.is_cw:
        return CW
    if mode.is_data:
        return DATA
    return PHONE


def occupied(dial: int, mode: Mode, audio_low: int | None = None, audio_high: int | None = None) -> tuple[int, int]:
    """RF span a transmission occupies, for the segment-confinement check (97.307(b)).

    For sideband modes the audio span (default 0-3 kHz) lands above the dial on
    upper sideband and below it on lower sideband.
    """
    if mode.is_cw:
        return dial - 100, dial + 100
    if mode is Mode.AM:
        return dial - 4_000, dial + 4_000
    if mode is Mode.FM:
        return dial - 8_000, dial + 8_000
    lo = 0 if audio_low is None else audio_low
    hi = 3_000 if audio_high is None else audio_high
    if mode in (Mode.LSB, Mode.DATA_REV):
        return dial - hi, dial - lo
    return dial + lo, dial + hi


@dataclass(frozen=True)
class TxCheck:
    allowed: bool
    reason: str = ""
    retry: bool = False   # refused before keying, likely transient: the caller may try again


def _mhz(hz: int) -> str:
    return f"{hz / 1e6:.3f}".rstrip("0").rstrip(".")


def tx_check(
    dial: int,
    mode: Mode,
    license_class: str = "General",
    audio_low: int | None = None,
    audio_high: int | None = None,
) -> TxCheck:
    """May this station transmit here, in this mode? Returns a friendly reason if not."""
    band = band_for(dial)
    if band is None:
        return TxCheck(False, f"{_mhz(dial)} MHz is outside the amateur bands.")
    if band.name == "60m":
        return TxCheck(False, "Transmitting on 60 m isn't supported yet. Its channel rules need special handling.")
    kind = emission_kind(mode)
    if mode is Mode.FM and dial < FM_MIN_HZ:
        return TxCheck(False, "FM transmit is only allowed from 29.0 MHz up (10 m FM and 6 m).")
    low, high = occupied(dial, mode, audio_low, audio_high)
    segments = PRIVILEGES.get(license_class, TECHNICIAN)  # unknown class: most restrictive
    for seg in segments:
        if kind in seg.kinds and seg.low <= low and high <= seg.high:
            return TxCheck(True)
    allowed = [s for s in segments if kind in s.kinds and band.contains(s.low)]
    what = {CW: "CW", DATA: "data", PHONE: "voice"}[kind]
    if not allowed:
        return TxCheck(False, f"{license_class} class has no {what} privileges on {band.label}.")
    ranges = ", ".join(f"{_mhz(s.low)}–{_mhz(s.high)}" for s in allowed)
    return TxCheck(False, f"Outside {license_class} {what} privileges on {band.label} ({ranges} MHz).")


def privilege_segments(band: Band, license_class: str = "General") -> list[Segment]:
    """Segments inside a band, for drawing the band overview."""
    return [s for s in PRIVILEGES.get(license_class, TECHNICIAN) if band.low <= s.low < band.high]


# Where Smartscan listens, from the ARRL band plan (arrl.org/band-plan, read
# 2026-10-11). Voice: the phone portion where SSB lives; on 10 m it stops at
# the AM window (29.0 MHz) and on 6 m it is the 50.1-50.3 SSB area. CW: the
# bottom of the CW/data segment, below the RTTY/data and FT8 sub-bands, so
# the sweep does not stop on every digital signal. Each range is clipped to
# the operator's privileges at run time (scan_ranges).
SCAN_VOICE: dict[str, tuple[int, int]] = {
    "160m": (1_843_000, 2_000_000),
    "80m": (3_600_000, 4_000_000),
    "40m": (7_125_000, 7_300_000),
    "20m": (14_150_000, 14_350_000),
    "17m": (18_110_000, 18_168_000),
    "15m": (21_200_000, 21_450_000),
    "12m": (24_930_000, 24_990_000),
    "10m": (28_300_000, 29_000_000),
    "6m": (50_100_000, 50_300_000),
}
SCAN_CW: dict[str, tuple[int, int]] = {
    "160m": (1_800_000, 1_838_000),     # below the FT8 dial at 1.840
    "80m": (3_500_000, 3_570_000),
    "40m": (7_000_000, 7_074_000),      # RTTY/data from 7.080; FT8 at 7.074
    "30m": (10_100_000, 10_130_000),
    "20m": (14_000_000, 14_070_000),
    "17m": (18_068_000, 18_100_000),
    "15m": (21_000_000, 21_070_000),
    "12m": (24_890_000, 24_915_000),    # FT8 at 24.915
    "10m": (28_000_000, 28_070_000),
    "6m": (50_000_000, 50_100_000),
}


@dataclass(frozen=True)
class HotSpot:
    hz: int
    kind: str          # "voice", "cw", or "sstv"
    label: str


# Where people gather. AM, SSTV, and 6 m SSB calling frequencies are from the
# ARRL band plan; QRP calling frequencies from two published QRP lists that
# agree (qsl.net/aa3sj/Pages/Freq.html, qsl.net/wb6dwd/QRPFrequencies.htm,
# read 2026-10-11). Smartscan revisits the voice and CW ones between regular
# steps and labels stations heard on them; SSTV ones only label (pictures,
# not a conversation).
HOT_SPOTS: list[HotSpot] = [
    HotSpot(1_810_000, "cw", "QRP calling"), HotSpot(1_910_000, "voice", "QRP calling"),
    HotSpot(3_560_000, "cw", "QRP calling"), HotSpot(3_845_000, "sstv", "SSTV"),
    HotSpot(3_885_000, "voice", "AM calling"), HotSpot(3_985_000, "voice", "QRP calling"),
    HotSpot(7_040_000, "cw", "QRP calling"), HotSpot(7_171_000, "sstv", "SSTV"),
    HotSpot(7_285_000, "voice", "QRP calling"), HotSpot(7_290_000, "voice", "AM calling"),
    HotSpot(10_106_000, "cw", "QRP calling"),
    HotSpot(14_060_000, "cw", "QRP calling"), HotSpot(14_230_000, "sstv", "SSTV"),
    HotSpot(14_285_000, "voice", "QRP calling"), HotSpot(14_286_000, "voice", "AM calling"),
    HotSpot(18_096_000, "cw", "QRP calling"), HotSpot(18_130_000, "voice", "QRP calling"),
    HotSpot(21_060_000, "cw", "QRP calling"), HotSpot(21_385_000, "voice", "QRP calling"),
    HotSpot(24_906_000, "cw", "QRP calling"), HotSpot(24_950_000, "voice", "QRP calling"),
    HotSpot(28_060_000, "cw", "QRP calling"), HotSpot(28_680_000, "sstv", "SSTV"),
    HotSpot(28_885_000, "voice", "QRP calling"),
    HotSpot(50_060_000, "cw", "QRP calling"), HotSpot(50_125_000, "voice", "SSB calling"),
]


def hot_spots(band: Band) -> list[HotSpot]:
    return [h for h in HOT_SPOTS if band.contains(h.hz)]


def scan_ranges(band: Band, kind: str, license_class: str = "General") -> list[tuple[int, int]]:
    """RF ranges Smartscan sweeps on a band for "voice" or "cw", inside the
    class's privileges for that emission. Empty when there is nothing to sweep
    (60 m, or no privileges)."""
    table, emission = (SCAN_VOICE, PHONE) if kind == "voice" else (SCAN_CW, CW)
    if band.name not in table:
        return []
    low, high = table[band.name]
    out = []
    for seg in PRIVILEGES.get(license_class, TECHNICIAN):
        if emission not in seg.kinds:
            continue
        lo, hi = max(low, seg.low), min(high, seg.high)
        if hi - lo >= 1_000:
            if out and out[-1][1] >= lo:
                out[-1] = (out[-1][0], max(out[-1][1], hi))
            else:
                out.append((lo, hi))
    return out


# Tuning step presets per mode (Hz): (fine, coarse). SSB stations align on
# 0.5/1 kHz; CW wants finer steps (KX3 Owner's Manual p.11).
STEPS = {
    CW: (10, 100),
    PHONE: (100, 1_000),
    DATA: (10, 1_000),
}
