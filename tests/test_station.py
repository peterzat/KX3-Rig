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
