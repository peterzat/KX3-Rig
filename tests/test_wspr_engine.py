"""The WSPR engine against the KX3 emulator."""

import time

import numpy as np
import pytest
from gi.repository import GLib

from kx3rig import config
from kx3rig.cat import DataSubmode, Mode
from kx3rig.controller import Station
from kx3rig.wspr import protocol as wspr
from kx3rig.wspr.engine import WsprEngine


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
    s = Station(config.Settings(callsign="K1ABC", grid="FN42", license_class="General"), demo=True)
    s.start()
    assert pump(lambda: s.connected and s.radio.frequency == 14_074_000 and s.radio.power_set is not None)
    yield s
    s.halt_all()
    s.link.stop()
    s._demo_source.stop()


@pytest.fixture
def eng(station, tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    e = WsprEngine(station, demo=True)
    yield e
    e.stop()


def _on_wspr(station):
    station.go_dial(wspr.DIALS["20m"])
    assert pump(lambda: station.radio.frequency == 14_095_600 and station.radio.mode is Mode.DATA
                and station.radio.data_submode is DataSubmode.DATA_A and not station.link.tuning_pending)


def test_beacon_needs_a_wspr_frequency(station, eng):
    assert "WSPR frequency" in eng.start_beacon().reason
    _on_wspr(station)
    assert eng.start_beacon(30).allowed and eng.beacon_on


def test_compound_calls_are_refused(station, eng):
    _on_wspr(station)
    station.settings.callsign = "K1ABC/P"
    assert not eng.check_tx().allowed


def test_beacon_transmits_in_scheduled_periods_only(station, eng, monkeypatch):
    _on_wspr(station)
    assert eng.start_beacon(60).allowed
    monkeypatch.setattr(eng.scheduler, "transmit_in", lambda slot: slot == 1000)
    sent = []
    monkeypatch.setattr(station, "play_data", lambda samples, rate, on_done, limit_s: (
        sent.append((len(samples) / rate, limit_s)), __import__("kx3rig.bandplan", fromlist=["x"]).TxCheck(True))[1])
    eng._maybe_transmit(999 * 120 + 0.7, 999, 0.7)
    assert not sent
    eng._maybe_transmit(1000 * 120 + 0.7, 1000, 0.7)
    assert eng.transmitting and len(sent) == 1
    seconds, limit = sent[0]
    assert seconds == pytest.approx(0.3 + wspr.DURATION_S, abs=0.05) and limit > seconds
    eng._maybe_transmit(1000 * 120 + 1.0, 1000, 1.0)
    assert len(sent) == 1                         # once per period
    eng._tx_done(True)
    assert not eng.transmitting and eng.beacon_on


def test_beacon_ends_by_itself(station, eng):
    _on_wspr(station)
    eng.start_beacon(30)
    eng.beacon_until = time.time() - 1
    eng._tick()
    assert not eng.beacon_on


def test_failed_transmission_stops_the_beacon(station, eng):
    _on_wspr(station)
    eng.start_beacon(30)
    eng.transmitting = True
    eng._tx_done(False)
    assert not eng.beacon_on


def test_spots_get_distance_and_upload_fields(station, eng):
    _on_wspr(station)
    spots = eng._demo_spots(500, station.radio.frequency) or [
        wspr.Spot("1200", -20, 0.1, 14_097_100, 0, "JA1WSP PM95 37", "JA1WSP", "PM95", 37)]
    got = []
    eng.connect("spots", lambda e, slot, heard: got.extend(heard))
    eng._on_spots(500, "20m", spots)
    assert got and all(h.km is not None and h.km > 0 for h in got)
    n, far = eng.summary()
    assert n == len({h.spot.call for h in got}) and far is not None
    forms = eng.upload_fields(500, got, station.radio.frequency)
    assert forms[0]["rcall"] == "K1ABC" and forms[0]["rgrid"] == "FN42" and forms[0]["function"] == "wspr"
    assert all(len(f["rgrid"]) == 4 for f in forms)


def test_upload_uses_the_dial_the_slot_was_recorded_on(station, eng, monkeypatch):
    from kx3rig.wspr import engine as wspr_engine

    started = []

    class FakeThread:
        def __init__(self, target=None, args=(), **kw):
            started.append(args)

        def start(self):
            pass

    monkeypatch.setattr(wspr_engine.threading, "Thread", FakeThread)   # nothing goes online
    eng.demo = False
    eng.settings.wspr_upload = True
    _on_wspr(station)
    station.go_dial(wspr.DIALS["40m"])            # the operator retunes while wsprd runs
    assert pump(lambda: station.radio.frequency == wspr.DIALS["40m"])
    spot = wspr.Spot("1200", -10, 0.0, 14_097_100, 0, "JA1WSP PM95 37", "JA1WSP", "PM95", 37)
    eng._on_spots(500, "20m", [spot], wspr.DIALS["20m"])
    assert started and started[0][2] == wspr.DIALS["20m"]


def test_our_own_call_is_not_listed(station, eng):
    eng._on_spots(1, "20m", [wspr.Spot("1200", -10, 0.0, 14_097_100, 0, "K1ABC FN42 30", "K1ABC", "FN42", 30)])
    assert eng.heard == []


def test_stop_beacon_unkeys(station, eng, monkeypatch):
    _on_wspr(station)
    eng.start_beacon(30)
    monkeypatch.setattr(eng.scheduler, "transmit_in", lambda slot: True)
    now = time.time()
    slot = wspr.slot_of(now) + 1
    eng._maybe_transmit(slot * 120 + 0.7, slot, 0.7)
    assert eng.transmitting and station.data_transmitting
    eng.stop_beacon()
    assert not eng.transmitting and not station.data_transmitting and not eng.beacon_on


def test_one_self_keying_activity_at_a_time(station, eng, tmp_path):
    from kx3rig.keyboard.engine import KeyboardEngine

    kb = KeyboardEngine(station)
    _on_wspr(station)
    assert eng.start_beacon(30).allowed
    assert "WSPR beacon" in kb.check_tx("hello").reason
    eng.stop_beacon()
    assert "WSPR beacon" not in kb.check_tx("hello").reason


def test_beacon_stops_when_the_band_changes(station, eng, monkeypatch):
    _on_wspr(station)
    assert eng.start_beacon(30).allowed
    events = []
    eng.connect("event", lambda e, kind, msg: events.append((kind, msg)))
    station.go_dial(wspr.DIALS["40m"])
    assert pump(lambda: station.radio.frequency == wspr.DIALS["40m"] and not station.link.tuning_pending)
    monkeypatch.setattr(eng.scheduler, "transmit_in", lambda slot: True)
    slot = wspr.slot_of(time.time()) + 1
    eng._maybe_transmit(slot * 120 + 0.7, slot, 0.7)
    assert not eng.transmitting and not station.data_transmitting and not eng.beacon_on
    assert events and "band changed" in events[-1][1]
