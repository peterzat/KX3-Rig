"""Text the Smartscan panel shows for heard stations."""

from kx3rig.cat import Mode
from kx3rig.smartscan.heard import HeardList
from kx3rig.ui.smartscan import frequency_text, heard_subtitle


def test_frequency_text():
    assert frequency_text(14_230_000, "voice") == "14.230 MHz"
    assert frequency_text(14_250_700, "voice") == "14.2507 MHz"
    assert frequency_text(14_060_150, "cw") == "14.0602 MHz"


def test_heard_subtitle():
    h = HeardList()
    e = h.add(14_285_000, "voice", Mode.USB, 12, 20, now=100, spot="QRP calling")
    h.add(14_285_000, "voice", Mode.USB, 10, 0, now=130)
    assert heard_subtitle(e, 140) == "Voice · QRP calling · S9+20 · just now · heard 2 times"
    s = h.add(14_230_000, "voice", Mode.USB, 12, -18, now=100, spot="SSTV")
    assert heard_subtitle(s, 400) == "Voice · SSTV pictures · S6 · 5 min ago"
    c = h.add(14_060_000, "cw", Mode.CW, 12, -30, now=100)
    assert heard_subtitle(c, 100).startswith("CW · S4")
