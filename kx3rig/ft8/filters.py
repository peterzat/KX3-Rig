"""Which decodes to show: doubtful decodes, worked stations, and CQs only.

After WSJT-X Improved (DG2YCB, https://wsjt-x-improved.sourceforge.io): its
"False Decodes Reduction" hides implausible weak decodes, and its filters hide
stations already worked or show only CQs. KX3-Rig's version is a post-filter on
stock jt9 output, so it cannot use their decoder-side checks:

- jt9's own low-confidence mark ("?", an a-priori decode with low quality).
- Weak decodes (-20 dB or below, where false decodes cluster) whose calls do
  not look like real callsigns, or carry an unresolved hash or a suffix pair
  no station uses (/P with /R).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .messages import base_call
from .sequencer import Decode

WEAK_DB = -20
# A plain amateur callsign: prefix of 1-3 characters ending in a digit, then 1-4 letters.
_STRICT_CALL = re.compile(r"^(?:[A-Z0-9]{1,3}[0-9]|[A-Z][0-9]?[A-Z]?[0-9])[A-Z]{1,4}$")


def plausible_call(call: str) -> bool:
    call = call.strip("<>").upper()
    if not call or call == "...":
        return False
    parts = call.split("/")
    if len(parts) > 3 or ("P" in parts[1:] and "R" in parts[1:]):
        return False
    return bool(_STRICT_CALL.match(base_call(call)))


def doubtful(d: Decode) -> bool:
    if d.low_confidence:
        return True
    if d.snr > WEAK_DB:
        return False
    m = d.message
    if m.free_text:
        return True
    calls = [c for c in (m.to, m.de) if c]
    return any(c == "<...>" or not plausible_call(c) for c in calls)


@dataclass
class DecodeFilter:
    cq_only: bool = False
    hide_worked: bool = False
    hide_doubtful: bool = True
    hidden_calls: set[str] = field(default_factory=set)

    def shows(self, d: Decode, my_call: str, worked: set[tuple[str, str]], band: str) -> bool:
        m = d.message
        if m.addressed_to(my_call):
            return True                       # anything sent to us is always shown
        if self.hide_doubtful and doubtful(d):
            return False
        sender = base_call(m.de) if m.de else ""
        if sender and sender in self.hidden_calls:
            return False
        if self.cq_only and not m.is_cq:
            return False
        if self.hide_worked and sender and (sender, band) in worked:
            return False
        return True
