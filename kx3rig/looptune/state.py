"""Where the AlexLoop is tuned, and whether the dial has left it.

Pure logic. A magnetic loop is resonant at one frequency at a time; its usable
width is a few tens of kilohertz (docs/references.md, "AlexLoop"). KX3-Rig
cannot see the loop's capacitor, so it remembers where the operator last
finished the Loop Tune guide and compares the dial with that.

    tuned     within a quarter of the loop's 2:1 SWR width: nothing to do
    touch-up  inside the 2:1 width but off the peak: receive is weaker, a
              quick peak on receive noise restores it
    retune    outside the 2:1 width, another band, or never tuned since the
              app started: tune before transmitting, and before Smartscan
    no-loop   a band the AlexLoop does not cover (160, 80, 60, 6 m)
"""

from __future__ import annotations

from dataclasses import dataclass

from .. import bandplan

# Approximate 2:1 SWR bandwidth, Hz. 40/30/20/15/10 m measured by VE3WDM
# (docs/references.md); 17 m and 12 m interpolated between their neighbours.
BANDWIDTH_HZ = {
    "40m": 10_000,
    "30m": 15_000,
    "20m": 35_000,
    "17m": 42_000,
    "15m": 50_000,
    "12m": 55_000,
    "10m": 60_000,
}

TUNED, TOUCH_UP, RETUNE, NO_LOOP = "tuned", "touch-up", "retune", "no-loop"


@dataclass(frozen=True)
class Need:
    level: str            # TUNED, TOUCH_UP, RETUNE, or NO_LOOP
    band: bandplan.Band | None
    tuned_hz: int         # where the loop was tuned (0 when unknown)
    offset_hz: int        # dial minus tuned frequency (0 when unknown or another band)

    @property
    def wants_action(self) -> bool:
        return self.level in (TOUCH_UP, RETUNE)

    def short(self) -> str:
        """Tag text for the Radio view."""
        return {TUNED: "Loop Tuned", TOUCH_UP: "Peak Loop", RETUNE: "Tune Loop",
                NO_LOOP: "No Loop Band"}[self.level]

    def explain(self) -> str:
        """One sentence: why, and what to do."""
        if self.level == NO_LOOP:
            band = self.band.label if self.band else "This frequency"
            return f"{band} is outside the AlexLoop's 40-10 m range. Use another antenna here."
        if self.tuned_hz <= 0:
            return "The loop hasn't been tuned since KX3-Rig started. Tune it for this frequency."
        where = f"{self.tuned_hz / 1e6:.3f} MHz"
        if self.level == TUNED:
            return f"The loop is tuned at {where}."
        tuned_band = bandplan.band_for(self.tuned_hz)
        if self.band is None or tuned_band is not self.band:
            return f"The loop is tuned for {tuned_band.label if tuned_band else where}. Retune it for this band."
        away = f"{abs(self.offset_hz) / 1000:.0f} kHz"
        if self.level == TOUCH_UP:
            return f"{away} from where the loop was peaked ({where}). Peak it on receive noise for full strength."
        return f"{away} from where the loop was tuned ({where}), outside its usable width. Retune before transmitting."


def need(dial_hz: int, tuned_hz: int) -> Need:
    band = bandplan.band_for(dial_hz)
    width = BANDWIDTH_HZ.get(band.name) if band else None
    if band is None or width is None:
        return Need(NO_LOOP, band, tuned_hz, 0)
    if tuned_hz <= 0 or bandplan.band_for(tuned_hz) is not band:
        return Need(RETUNE, band, tuned_hz, 0)
    offset = dial_hz - tuned_hz
    if abs(offset) <= width / 4:
        return Need(TUNED, band, tuned_hz, offset)
    if abs(offset) <= width / 2:
        return Need(TOUCH_UP, band, tuned_hz, offset)
    return Need(RETUNE, band, tuned_hz, offset)


def covers(band: bandplan.Band | None) -> bool:
    return band is not None and band.name in BANDWIDTH_HZ
