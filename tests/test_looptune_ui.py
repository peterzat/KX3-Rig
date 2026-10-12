"""Text the Loop Tune guide shows."""

from kx3rig.looptune.meter import Reading
from kx3rig.ui.looptune import PEAK_TEXT, done_text


def test_done_text_names_the_frequency_and_the_retune_distance():
    text = done_text(14_285_000, 35_000, rx_only=False)
    assert "with TUNE at 14.285 MHz" in text
    assert "8.75 kHz" in text and "17.5 kHz" in text
    rx = done_text(7_185_000, 10_000, rx_only=True)
    assert "on receive noise" in rx and "TUNE confirms" in rx
    assert "kHz" not in done_text(3_985_000, 0, rx_only=False)


def test_every_meter_state_has_advice():
    for state in ("searching", "rising", "peak", "past"):
        assert PEAK_TEXT[Reading(0, 0, 0, state).state]
