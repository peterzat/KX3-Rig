"""Recently heard: stations Smartscan found, merged across sweeps.

Pure logic. The same station is heard on every sweep (and sometimes in two
overlapping steps), so detections close in frequency and of the same kind
update one entry instead of adding another. Each entry keeps the clip from
its strongest hearing, so replaying it shows why it was worth stopping for.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ..cat import Mode

MERGE_HZ = {"voice": 1_500, "cw": 150}
FORGET_S = 15 * 60          # drop a station not heard for this long
MAX_ENTRIES = 12


@dataclass
class Heard:
    tune_hz: int                 # where to put the dial to listen
    kind: str                    # "voice" or "cw"
    mode: Mode                   # mode to listen in
    first_seen: float
    last_seen: float
    snr_db: float                # best seen
    smeter_db: float             # KX3 S-meter at that hearing (dB over S9)
    times: int = 1               # dwells it was heard in
    clip: np.ndarray | None = field(default=None, repr=False)   # 12 kHz mono audio
    clip_dial: int = 0           # dial frequency the clip was recorded at
    id: int = 0
    spot: str = ""               # gathering place it is on ("QRP calling"), if any

    @property
    def is_sstv(self) -> bool:
        return self.spot == "SSTV"

    def age_text(self, now: float) -> str:
        seconds = now - self.last_seen
        if seconds < 90:
            return "just now"
        minutes = int(seconds // 60)
        return f"{minutes} min ago"


class HeardList:
    def __init__(self) -> None:
        self.entries: list[Heard] = []
        self._next_id = 1

    def add(self, tune_hz: int, kind: str, mode: Mode, snr_db: float, smeter_db: float, now: float,
            clip: np.ndarray | None = None, clip_dial: int = 0, spot: str = "") -> Heard:
        """Record a hearing; returns the entry it created or updated."""
        tolerance = MERGE_HZ.get(kind, 500)
        match = min((e for e in self.entries if e.kind == kind and abs(e.tune_hz - tune_hz) <= tolerance),
                    key=lambda e: abs(e.tune_hz - tune_hz), default=None)
        if match is None:
            match = Heard(tune_hz, kind, mode, now, now, snr_db, smeter_db, id=self._next_id, spot=spot)
            self._next_id += 1
            self.entries.append(match)
            stronger = True
        else:
            match.times += 1
            match.last_seen = now
            stronger = snr_db >= match.snr_db
            if stronger:
                # The strongest hearing has the best frequency estimate (an edge
                # step sees only part of a voice) and the best clip.
                match.tune_hz, match.snr_db = tune_hz, snr_db
                match.spot = spot or match.spot
            match.smeter_db = max(match.smeter_db, smeter_db)
        if clip is not None and (stronger or match.clip is None):
            match.clip, match.clip_dial = clip, clip_dial
        self.prune(now)
        return match

    def prune(self, now: float) -> None:
        self.entries = [e for e in self.entries if now - e.last_seen < FORGET_S]
        if len(self.entries) > MAX_ENTRIES:
            # Keep the freshest; ties go to the stronger.
            self.entries.sort(key=lambda e: (e.last_seen, e.snr_db), reverse=True)
            del self.entries[MAX_ENTRIES:]

    def ordered(self) -> list[Heard]:
        """Newest hearing first, then strongest; SSTV (pictures, not a
        conversation) after everything else."""
        return sorted(self.entries, key=lambda e: (e.is_sstv, -round(e.last_seen / 30), -e.snr_db))

    def get(self, entry_id: int) -> Heard | None:
        return next((e for e in self.entries if e.id == entry_id), None)

    def clear(self) -> None:
        self.entries.clear()
