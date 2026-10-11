"""Transmit policy in the Station controller, driven against the KX3 emulator."""

import time

import numpy as np
import pytest
from gi.repository import GLib

from kx3rig import config
from kx3rig.cat import Mode
from kx3rig.controller import Station


def pump(predicate, timeout=4.0):
    ctx = GLib.MainContext.default()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        while ctx.pending():
            ctx.iteration(False)
        if predicate():
            return True
        time.sleep(0.01)
    return False


@pytest.fixture
def station():
    s = Station(config.Settings(callsign="N0CALL", grid="DM79", license_class="General"), demo=True)
    s.start()
    assert pump(lambda: s.connected and s.radio.frequency == 14_074_000)
    yield s
    s.halt_all()
    s.link.stop()
    s._demo_source.stop()


def test_voice_refused_in_data_mode(station):
    check = station.voice_check()
    assert not check.allowed and "data mode" in check.reason


def test_voice_follows_band_plan(station):
    station.select_mode(Mode.USB)
    assert pump(lambda: station.radio.mode is Mode.USB)
    assert not station.voice_check().allowed           # 14.074 USB is in the data segment
    station.tune_to(14_285_000)
    assert pump(lambda: station.radio.frequency == 14_285_000)
    assert station.voice_check().allowed


def test_no_callsign_no_transmit(station):
    station.settings.callsign = ""
    check = station.can_transmit(Mode.DATA, 1500, 1550)
    assert not check.allowed and "callsign" in check.reason


def test_changes_refused_while_transmitting(station):
    done = []
    tone = np.zeros(48_000, np.float32)
    assert station.play_data(tone, 48_000, on_done=done.append).allowed
    station.tune_to(7_074_000)
    station.select_mode(Mode.LSB)
    assert pump(lambda: bool(done), timeout=4)
    assert done == [True]
    assert station.radio.frequency == 14_074_000 and station.radio.mode is Mode.DATA
    assert not station.radio.ptt


def test_stopped_transmission_never_reports_or_unkeys_later(station):
    done = []
    tone = np.zeros(24_000, np.float32)   # 0.5 s
    assert station.play_data(tone, 48_000, on_done=done.append).allowed
    station.stop_data_tx()
    assert not station.radio.ptt
    # A new transmission starts; the first one's timer must not end it.
    assert station.play_data(np.zeros(96_000, np.float32), 48_000, on_done=done.append).allowed
    pump(lambda: False, timeout=0.8)
    assert station.radio.ptt and done == []
    assert pump(lambda: done == [True], timeout=3)


def test_watchdog_ends_data_transmission_and_reports_it_once(station):
    done = []
    tone = np.zeros(96_000, np.float32)   # 2 s, longer than the 0.3 s limit
    assert station.play_data(tone, 48_000, on_done=done.append, limit_s=0.3).allowed
    assert pump(lambda: done == [False], timeout=2)
    assert not station.data_transmitting and not station.radio.ptt
    pump(lambda: False, timeout=2.2)       # the clip's own completion is stale now
    assert done == [False]


@pytest.mark.parametrize("flag", ["split", "xit_on"])
def test_split_or_xit_blocks_transmit(station, flag):
    assert station.can_transmit(Mode.DATA, 1500, 1550).allowed
    setattr(station._fake, flag, True)
    assert pump(lambda: getattr(station.radio, flag))
    check = station.can_transmit(Mode.DATA, 1500, 1550)
    assert not check.allowed and "SPLIT" in check.reason


def test_power_above_limit_blocks_transmit(station):
    station.settings.max_power_w = 3.0
    assert pump(lambda: station.radio.power_set == 5)
    check = station.can_transmit(Mode.DATA, 1500, 1550)
    assert not check.allowed and "5 W" in check.reason


def test_ft8_requires_data_a(station, monkeypatch, tmp_path):
    import kx3rig.ft8.encode
    from kx3rig.cat import DataSubmode
    from kx3rig.ft8.engine import Ft8Engine

    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setattr(kx3rig.ft8.encode, "available", lambda: True)
    engine = Ft8Engine(station, demo=True)
    assert pump(lambda: station.radio.data_submode is DataSubmode.DATA_A)
    assert engine.check_tx().allowed
    station.link.set_mode(Mode.DATA, DataSubmode.AFSK_A)
    assert pump(lambda: station.radio.data_submode is DataSubmode.AFSK_A)
    check = engine.check_tx()
    assert not check.allowed and "DATA A" in check.reason


def gate_writes(fake):
    """Block the link thread in its next write to the emulator until the gate opens."""
    import threading

    gate, blocked = threading.Event(), threading.Event()
    real_write = fake.write

    def write(data):
        if not gate.is_set():
            blocked.set()
            gate.wait(5)
        return real_write(data)

    fake.write = write
    return gate, blocked


def test_link_error_ends_data_transmission(station):
    done = []
    assert station.play_data(np.zeros(96_000, np.float32), 48_000, on_done=done.append).allowed
    assert station._fake.rts
    real_read = station._fake.read
    raised = []

    def read(size=1):
        if not raised:
            raised.append(True)
            raise RuntimeError("simulated link fault")
        return real_read(size)

    station._fake.read = read
    assert pump(lambda: done == [False], timeout=3)
    assert not station.data_transmitting and not station.radio.ptt
    assert station._fake.rts is False


def test_stale_main_loop_copy_never_keys_after_a_tune(station):
    """The link applied a tune the main loop has not seen yet: key-down is refused."""
    keyed = len(station._fake.rts_history)
    station.tune_to(14_230_000)                  # no pump: station.radio stays stale
    deadline = time.monotonic() + 4
    while time.monotonic() < deadline:
        if station.link.state.frequency == 14_230_000 and not station.link.tuning_pending:
            break
        time.sleep(0.01)
    assert station._fake.frequency == 14_230_000 and not station.link.tuning_pending
    assert station.radio.frequency == 14_074_000
    check = station.play_data(np.zeros(4_800, np.float32), 48_000)
    assert not check.allowed
    assert True not in station._fake.rts_history[keyed:]


def test_play_data_refused_while_tuning(station):
    gate, blocked = gate_writes(station._fake)
    try:
        assert blocked.wait(2)
        keyed = len(station._fake.rts_history)
        station.tune_to(14_230_000)
        assert station.link.tuning_pending
        check = station.play_data(np.zeros(4_800, np.float32), 48_000)
        assert not check.allowed and "Still tuning" in check.reason
        assert True not in station._fake.rts_history[keyed:]
    finally:
        gate.set()


def test_ft8_waits_while_tuning(station, monkeypatch, tmp_path):
    import kx3rig.ft8.encode
    from kx3rig.ft8.decode import slot_start
    from kx3rig.ft8.engine import TX_START_S, Ft8Engine

    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setattr(kx3rig.ft8.encode, "available", lambda: True)
    engine = Ft8Engine(station, demo=True)
    events = []
    engine.connect("event", lambda _e, kind, msg: events.append(kind))
    engine.sequencer.call_cq(tx_even=True)
    gate, blocked = gate_writes(station._fake)
    try:
        assert blocked.wait(2)
        keyed = len(station._fake.rts_history)
        station.tune_to(14_074_500)
        assert station.link.tuning_pending
        engine._maybe_transmit(slot_start(1000) + TX_START_S)
        assert engine.sequencer.active and engine.transmitting_text == ""
        assert not station.data_transmitting and events == []
        assert True not in station._fake.rts_history[keyed:]
    finally:
        gate.set()
