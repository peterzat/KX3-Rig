"""Where the loop is tuned and when the dial has left it."""

from kx3rig.looptune import state
from kx3rig.looptune.state import NO_LOOP, RETUNE, TOUCH_UP, TUNED, need


def test_never_tuned_asks_for_a_tune():
    n = need(14_285_000, 0)
    assert n.level == RETUNE and n.wants_action
    assert "hasn't been tuned" in n.explain()


def test_thresholds_follow_the_band_width():
    # 20 m: 35 kHz wide. A quarter (8.75 kHz) is still tuned, half (17.5 kHz) needs a peak.
    assert need(14_293_000, 14_285_000).level == TUNED
    assert need(14_300_000, 14_285_000).level == TOUCH_UP
    assert need(14_310_000, 14_285_000).level == RETUNE
    # 40 m is far narrower: 4 kHz away already wants a peak.
    assert need(7_289_000, 7_285_000).level == TOUCH_UP
    assert need(7_200_000, 7_285_000).level == RETUNE


def test_another_band_needs_a_retune():
    n = need(7_200_000, 14_285_000)
    assert n.level == RETUNE
    assert "20 m" in n.explain() and "this band" in n.explain()


def test_bands_outside_the_loop():
    for hz in (3_985_000, 1_910_000, 5_357_000, 50_125_000):
        n = need(hz, 14_285_000)
        assert n.level == NO_LOOP and not n.wants_action
    assert "outside" in need(3_985_000, 0).explain()
    assert need(0, 0).level == NO_LOOP


def test_explanations_name_the_distance():
    assert "15 kHz" in need(14_300_000, 14_285_000).explain()
    assert "tuned at 14.285" in need(14_286_000, 14_285_000).explain()
    assert need(14_286_000, 14_285_000).short() == "Loop Tuned"


def test_every_loop_band_has_a_width_and_the_demo_uses_the_same_table():
    from kx3rig import demo

    assert set(state.BANDWIDTH_HZ) == {"40m", "30m", "20m", "17m", "15m", "12m", "10m"}
    assert demo.LOOP_BANDWIDTH_HZ is state.BANDWIDTH_HZ
