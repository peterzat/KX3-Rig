"""Smartscan driving the real link code against the KX3 emulator and demo band."""

import time

import pytest
from gi.repository import GLib

from kx3rig import config
from kx3rig.cat import Mode
from kx3rig.controller import Station
from kx3rig.smartscan import engine as engine_mod
from kx3rig.smartscan.engine import Smartscan


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
def scan(station):
    sc = Smartscan(station, demo=True)
    events = []
    sc.connect("event", lambda o, kind, msg: events.append(msg))
    sc.events = events
    yield sc
    sc.stop(restore=False)


def _on(station, hz, mode):
    station.tune_to(hz)
    station.select_mode(mode)
    assert pump(lambda: station.radio.frequency == hz and station.radio.mode is mode)


def test_sweeps_in_the_scan_mode_and_restores_on_stop(station, scan):
    assert scan.start() == ""
    assert scan.plan.kind == "voice" and scan.plan.scan_mode is Mode.USB   # from DATA on 20 m
    assert station.scanning
    first = scan.position
    assert pump(lambda: scan.position != first, timeout=4)
    assert station.radio.mode is Mode.USB
    assert scan.plan.low <= station.radio.frequency + 2_800 and station.radio.frequency <= scan.plan.high
    scan.stop()
    assert not station.scanning
    assert pump(lambda: station.radio.frequency == 14_074_000 and station.radio.mode is Mode.DATA)


def test_transmit_is_refused_while_scanning(station, scan):
    _on(station, 14_300_000, Mode.USB)
    assert scan.start() == ""
    check = station.can_transmit(Mode.USB)
    assert not check.allowed and "Smartscan" in check.reason
    assert not station.voice_check().allowed


def test_operator_tuning_takes_over(station, scan):
    _on(station, 14_300_000, Mode.USB)
    assert scan.start() == ""
    assert pump(lambda: scan._phase == "listen", timeout=3)
    station._fake.frequency = 14_123_450        # the operator turns the VFO knob
    assert pump(lambda: not scan.active, timeout=4)
    assert any("you tuned" in m for m in scan.events)
    assert not station.scanning
    pump(lambda: False, timeout=0.6)
    assert station.radio.frequency == 14_123_450   # left where the operator put it


def test_finds_a_demo_station_with_a_clip(station, scan, monkeypatch):
    # A station that is always on, in the middle of a short sweep.
    from kx3rig import demo

    always = demo.DemoStation(14_250_000, "voice", 0.07, 1e6, 1, 0, 140)
    station._demo_source._stations = [always]
    station._demo_source.loop.tuned_hz = 14_250_000     # the operator peaked the loop here
    _on(station, 14_249_000, Mode.USB)
    assert scan.start() == ""
    assert pump(lambda: any(abs(e.tune_hz - 14_250_000) <= 300 for e in scan.heard.entries), timeout=20)
    entry = next(e for e in scan.heard.entries if abs(e.tune_hz - 14_250_000) <= 300)
    assert entry.kind == "voice" and entry.mode is Mode.USB
    assert pump(lambda: entry.clip is not None, timeout=10)
    assert len(entry.clip) >= 4 * 12_000
    scan.tune(entry.id)
    assert not scan.active
    assert pump(lambda: station.radio.frequency == entry.tune_hz and station.radio.mode is Mode.USB)


def test_cw_mode_sweeps_the_cw_segment_in_usb(station, scan):
    _on(station, 14_040_000, Mode.CW)
    assert scan.start() == ""
    assert scan.plan.kind == "cw" and scan.plan.ranges == ((14_025_000, 14_070_000),)
    assert pump(lambda: station.radio.mode is Mode.USB)
    scan.stop()
    assert pump(lambda: station.radio.mode is Mode.CW and station.radio.frequency == 14_040_000)


def test_refuses_60m_and_when_disconnected(station, scan):
    _on(station, 5_357_000, Mode.USB)
    assert "60 m" in scan.start()
    assert not scan.active and not station.scanning


def test_demo_outlook_never_touches_the_network(station, scan, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("network used in demo mode")
    monkeypatch.setattr(engine_mod.conditions, "fetch", boom)
    _on(station, 14_300_000, Mode.USB)
    assert scan.start() == ""
    assert pump(lambda: scan.outlook is not None, timeout=4)
    assert scan.outlook["20m"].level == "open"


def test_live_fetch_is_rate_limited(station, monkeypatch):
    calls = []

    def fake_fetch(url, timeout=20.0):
        calls.append(url)
        if "pskreporter" in url:
            return b'<?xml version="1.0"?><receptionReports></receptionReports>'
        return b'[{"estimated_kp": 3.0}]'
    monkeypatch.setattr(engine_mod.conditions, "fetch", fake_fetch)
    monkeypatch.setitem(engine_mod._last_fetch, "psk", 0.0)
    monkeypatch.setitem(engine_mod._last_fetch, "kp", 0.0)
    sc = Smartscan(station, demo=False)
    sc._maybe_fetch()
    assert pump(lambda: not sc.fetching and sc.kp == 3.0)
    assert len(calls) == 2
    sc._maybe_fetch()
    sc._maybe_fetch()
    pump(lambda: False, timeout=0.3)
    assert len(calls) == 2, "a second query inside five minutes"


def test_calling_frequency_is_revisited_and_labelled(station, scan):
    from kx3rig import demo

    station._demo_source._stations = [demo.DemoStation(14_285_000, "voice", 0.07, 1e6, 1, 0, 140)]
    station._demo_source.loop.tuned_hz = 14_300_000
    _on(station, 14_330_000, Mode.USB)       # far from 14.285: only a revisit finds it quickly
    assert scan.start() == ""
    visited = []
    scan.connect("changed", lambda o: visited.append(scan.position))
    assert pump(lambda: 14_285_000 in visited, timeout=15)
    assert pump(lambda: any(e.spot == "QRP calling" for e in scan.heard.entries), timeout=10), [(e.tune_hz, e.spot, e.times) for e in scan.heard.entries]
