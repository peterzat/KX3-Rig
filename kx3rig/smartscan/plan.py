"""The sweep: which dial frequencies Smartscan visits, and where a heard
signal really is.

Pure logic. The receiver hears an audio window of roughly 300-2800 Hz beside
the dial: above it on upper sideband, below it on lower sideband. A sweep
steps the dial so consecutive windows overlap slightly and together cover
every RF range in the plan.

CW is swept in USB with the voice filter (2.8 kHz wide), so one step covers
dozens of CW channels instead of one; the radio switches to CW only when you
tune to a station.
"""

from __future__ import annotations

from dataclasses import dataclass

from .. import bandplan
from ..cat import Mode
from .detect import Detection

AUDIO_LOW = 300
AUDIO_HIGH = 2_800
OVERLAP = 100
SSB_CARRIER_BELOW_VOICE = 300   # SSB transmit audio starts about 300 Hz from the carrier


@dataclass(frozen=True)
class Plan:
    band: bandplan.Band
    kind: str                       # "voice" or "cw": what we are listening for
    ranges: tuple[tuple[int, int], ...]
    scan_mode: Mode                 # the mode the radio sweeps in
    steps: tuple[int, ...]          # dial frequencies, in sweep order
    audio_high: int = AUDIO_HIGH    # top of the heard audio window (narrower filters lower it)
    hot_steps: tuple[int, ...] = () # extra dial positions for calling frequencies, revisited often
    spots: tuple[bandplan.HotSpot, ...] = ()   # every known spot in the band, for labels

    def spot_label(self, tune_hz: int, kind: str) -> str:
        """Name of the gathering place a station is on, if any ("QRP calling")."""
        tolerance = 1_000 if kind == "voice" else 300
        near = [h for h in self.spots if abs(h.hz - tune_hz) <= tolerance
                and (h.kind == kind or h.kind == "sstv" and kind == "voice")]
        return min(near, key=lambda h: abs(h.hz - tune_hz)).label if near else ""

    @property
    def lower_sideband(self) -> bool:
        return self.scan_mode is Mode.LSB

    @property
    def low(self) -> int:
        return self.ranges[0][0]

    @property
    def high(self) -> int:
        return self.ranges[-1][1]

    @property
    def tune_mode(self) -> Mode:
        """The mode to listen to a station in once found."""
        return Mode.CW if self.kind == "cw" else self.scan_mode

    def mode_for(self, kind: str) -> Mode:
        """The mode to listen to a detection of this kind in: CW for CW (a CW
        signal heard in a voice sweep), the scan sideband for voice."""
        return Mode.CW if kind == "cw" else self.scan_mode

    def label(self) -> str:
        what = "CW" if self.kind == "cw" else "voice"
        return f"{self.band.label} {what}, {self.low / 1e6:.3f}–{self.high / 1e6:.3f} MHz"

    def audio_window(self, dial: int) -> tuple[int, int]:
        """RF span heard at a dial frequency (low, high)."""
        if self.lower_sideband:
            return dial - self.audio_high, dial - AUDIO_LOW
        return dial + AUDIO_LOW, dial + self.audio_high

    def rf(self, dial: int, audio_hz: float) -> int:
        return int(round(dial - audio_hz if self.lower_sideband else dial + audio_hz))

    def detection_rf(self, dial: int, d: Detection) -> tuple[int, int]:
        """RF span (low, high) a detection occupies."""
        a, b = self.rf(dial, d.low_hz), self.rf(dial, d.high_hz)
        return min(a, b), max(a, b)

    def tune_frequency(self, dial: int, d: Detection) -> int:
        """Where to put the dial to listen to a detected station.

        CW: on the signal (the KX3 then plays it at its sidetone pitch).
        Voice: the suppressed carrier, about 300 Hz outside the voice's edge
        nearest the dial, snapped to a whole kHz when close to one (most SSB
        stations sit on round frequencies) and to 100 Hz otherwise.
        """
        if d.kind != "voice":
            return self.rf(dial, d.peak_hz)
        edge = self.rf(dial, d.low_hz)
        carrier = edge + SSB_CARRIER_BELOW_VOICE if self.lower_sideband else edge - SSB_CARRIER_BELOW_VOICE
        nearest_khz = round(carrier / 1000) * 1000
        if abs(carrier - nearest_khz) <= 400:
            return nearest_khz
        return round(carrier / 100) * 100


def make_plan(band: bandplan.Band, mode: Mode | None, license_class: str,
              bandwidth_hz: int | None = None) -> Plan | None:
    """The sweep for the band the radio is on, following its mode: CW modes
    hunt CW, everything else hunts voice. A band with nothing of that kind to
    sweep (30 m has no voice) falls back to the other. None when neither
    exists (60 m) or the class has no privileges there."""
    kind = "cw" if mode is not None and mode.is_cw else "voice"
    ranges = bandplan.scan_ranges(band, kind, license_class)
    if not ranges:
        kind = "voice" if kind == "cw" else "cw"
        ranges = bandplan.scan_ranges(band, kind, license_class)
    if not ranges:
        return None
    scan_mode = band.voice_mode if kind == "voice" else Mode.USB
    lsb = scan_mode is Mode.LSB
    high_audio = AUDIO_HIGH
    if bandwidth_hz:
        high_audio = max(AUDIO_LOW + 800, min(AUDIO_HIGH, 200 + int(bandwidth_hz)))
    step = high_audio - AUDIO_LOW - OVERLAP
    steps: list[int] = []
    for low, high in ranges:
        # First window starts at the range's low edge; walk up until covered.
        rf_low = low
        while True:
            dial = rf_low + high_audio if lsb else rf_low - AUDIO_LOW
            steps.append(int(dial))
            if rf_low + (high_audio - AUDIO_LOW) >= high:
                break
            rf_low += step
    # Calling frequencies get a dial position of their own: on the spot for
    # voice (the voice then fills the window), mid-window for CW.
    spots = tuple(bandplan.hot_spots(band))
    hot: list[int] = []
    for h in spots:
        if h.kind != kind or not any(lo <= h.hz <= hi for lo, hi in ranges):
            continue
        dial = h.hz if kind == "voice" else h.hz - (AUDIO_LOW + high_audio) // 2
        if not hot or abs(dial - hot[-1]) > 1_500:
            hot.append(dial)
    return Plan(band, kind, tuple(ranges), scan_mode, tuple(steps), high_audio, tuple(hot), spots)
