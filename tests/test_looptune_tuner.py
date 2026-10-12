"""Loop Tune against the KX3 emulator and the demo's simulated loop."""

import time

import pytest
from gi.repository import GLib

from kx3rig import config
from kx3rig.cat import Mode
from kx3rig.controller import Station
from kx3rig.looptune.state import RETUNE, TOUCH_UP, TUNED
from kx3rig.looptune.tuner import LoopTuner


def pump(predicate, timeout=4.0):
    ctx = GLib.MainContext.default()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        while ctx.pending():
            ctx.iteration(False)
        if predicate():
            return True
        time.sleep(0.005)
    return False


@pytest.fixture
def station():
    s = Station(config.Settings(callsign="N0CALL", grid="CN87", license_class="General"), demo=True)
    s.start()
    assert pump(lambda: s.connected and s.radio.frequency == 14_074_000)
    yield s
    s.halt_all()
    s.link.stop()
    s._demo_source.stop()


@pytest.fixture
def tuner(station):
    t = LoopTuner(station, demo_loop=station._demo_source.loop)
    yield t
    t.stop_meter()
    t.demo_hold_tune(False)


def _tune(station, hz, mode=Mode.USB):
    station.tune_to(hz)
    station.select_mode(mode)
    assert pump(lambda: station.radio.frequency == hz and station.radio.mode is mode)


def test_untuned_at_start_then_follows_the_dial(station, tuner):
    _tune(station, 14_285_000)
    assert tuner.need.level == RETUNE
    changes = []
    tuner.connect("need-changed", lambda t: changes.append(t.need.level))
    tuner.mark_tuned()
    assert tuner.tuned_hz == 14_285_000 and tuner.need.level == TUNED
    _tune(station, 14_300_000)
    assert pump(lambda: tuner.need.level == TOUCH_UP)
    _tune(station, 7_200_000, Mode.LSB)
    assert pump(lambda: tuner.need.level == RETUNE)
    assert TUNED in changes and TOUCH_UP in changes


def test_advice_holds_still_while_smartscan_sweeps(station, tuner):
    _tune(station, 14_285_000)
    tuner.mark_tuned()
    station.scanning = True
    _tune(station, 14_330_000)
    pump(lambda: False, timeout=0.3)
    assert tuner.need.level == TUNED, "the sweep moved the dial, not the operator"
    station.scanning = False
    _tune(station, 14_331_000)
    assert pump(lambda: tuner.need.level == RETUNE)


def test_reads_the_operators_tune_carrier(station, tuner):
    _tune(station, 14_285_000)
    station._fake.power = 10
    tuner.demo_knob(0)                      # the loop is resonant on the dial
    events = []
    tuner.connect("carrier", lambda t: events.append(t.keyed))
    tuner.demo_hold_tune(True)
    assert pump(lambda: tuner.keyed and tuner.best_swr is not None, timeout=3)
    assert tuner.max_power == pytest.approx(1.0)       # TUN PWR, lower than PWR
    assert tuner.best_swr == pytest.approx(1.3, abs=0.05)
    assert not tuner.tune_power_high
    tuner.demo_hold_tune(False)
    assert pump(lambda: not tuner.keyed, timeout=3)
    assert tuner.carrier_seen and events[0] is True and events[-1] is False


def test_tune_power_following_pwr_is_flagged(station, tuner):
    _tune(station, 14_285_000)
    station._fake.power = 10
    station._fake.tune_power = 10          # TUN PWR left at NOR
    tuner.demo_hold_tune(True)
    assert pump(lambda: tuner.tune_power_high, timeout=3)


def test_off_resonance_swr_is_high(station, tuner):
    _tune(station, 14_285_000)
    tuner.demo_knob(30_000)                # nearly a full bandwidth away
    tuner.demo_hold_tune(True)
    assert pump(lambda: tuner.best_swr is not None, timeout=3)
    assert tuner.best_swr > 2.5


def test_the_noise_meter_peaks_where_the_loop_resonates(station, tuner):
    _tune(station, 14_285_000)
    readings = []
    tuner.connect("reading", lambda t, r: readings.append(r))
    tuner.start_meter()
    levels = {}
    for offset in (60_000, 20_000, 0):
        tuner.demo_knob(offset)
        tuner.restart_meter()
        readings.clear()
        assert pump(lambda: len(readings) >= 4, timeout=4)
        levels[offset] = readings[-1].level_db
    assert levels[0] > levels[20_000] > levels[60_000]
    assert levels[0] - levels[60_000] > 6
    tuner.stop_meter()
    assert tuner._feed not in station.sample_listeners


def test_tune_check_follows_privileges(station, tuner):
    _tune(station, 14_285_000)
    assert tuner.tx_check().allowed
    station.settings.license_class = "Technician"
    assert not tuner.tx_check().allowed


def test_guide_refuses_while_ft8_may_key(station, tuner):
    import types

    assert tuner.open_refusal(types.SimpleNamespace(busy=False)) == ""
    assert "FT8" in tuner.open_refusal(types.SimpleNamespace(busy=True))
    assert tuner.open_refusal() == ""


def test_last_tune_swr_never_seeds_the_next(station, tuner):
    _tune(station, 14_285_000)
    assert tuner.swr_readable                 # the emulator reports firmware 2.93
    tuner.demo_knob(0)
    tuner.demo_hold_tune(True)
    assert pump(lambda: tuner.best_swr is not None, timeout=3)
    assert tuner.best_swr < 1.5
    tuner.demo_hold_tune(False)
    assert pump(lambda: not tuner.keyed, timeout=3)
    assert station.radio.swr is None and station.radio.power_out is None
    tuner.reset_carrier()
    tuner.demo_knob(30_000)                   # far off resonance this time
    tuner.demo_hold_tune(True)
    assert pump(lambda: tuner.keyed and tuner.best_swr is not None, timeout=3)
    assert tuner.best_swr > 2.5
