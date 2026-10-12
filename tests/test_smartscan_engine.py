"""Smartscan driving the real link code against the KX3 emulator and demo band."""

import time

import numpy as np

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


def test_stops_when_radio_audio_goes_away(station, scan):
    from kx3rig.controller import AudioStatus

    _on(station, 14_300_000, Mode.USB)
    assert scan.start() == ""
    assert pump(lambda: scan._phase == "listen", timeout=3)
    station._set_audio(AudioStatus(rx=False, tx=True, error="Receive audio stopped"))
    assert pump(lambda: not scan.active, timeout=2)
    assert any("audio stopped" in m for m in scan.events)
    assert not station.scanning


def test_stops_when_receive_audio_stalls(station, scan):
    _on(station, 14_300_000, Mode.USB)
    assert scan.start() == ""
    assert pump(lambda: scan._phase == "listen", timeout=3)
    station._demo_source.stop()                  # no more audio, though the status still says rx
    limit = engine_mod.SETTLE_S + engine_mod.CLIP_S + engine_mod.AUDIO_STALL_S + 1
    assert pump(lambda: not scan.active, timeout=limit)
    assert any("audio stopped" in m for m in scan.events)


def test_audio_kept_is_bounded_by_time(station, scan):
    rate = 12_000
    chunk = np.zeros(16, np.float32)             # a very small buffer
    for i in range(20_000):
        scan._feed(chunk, 1_000.0 + (i + 1) * len(chunk) / rate)
    kept = sum(len(s) for _, s in scan._samples) / rate
    assert engine_mod.KEEP_AUDIO_S - 0.1 <= kept <= engine_mod.KEEP_AUDIO_S + 0.1


def test_start_from_cw_plans_for_the_scan_modes_filter(station, scan):
    from kx3rig import bandplan
    from kx3rig.smartscan.plan import make_plan

    _on(station, 14_040_000, Mode.CW)
    assert pump(lambda: station.radio.bandwidth == 400)
    assert scan.start() == ""
    assert pump(lambda: scan._phase == "listen" and station.radio.mode is Mode.USB, timeout=4)
    usb = make_plan(bandplan.BY_NAME["20m"], Mode.CW, "General", bandwidth_hz=2800)
    assert scan.plan.kind == "cw" and scan.plan.steps == usb.steps
    assert scan.position in usb.steps


def test_a_cw_signal_in_a_voice_sweep_is_heard_in_cw(station, scan):
    from kx3rig.smartscan.detect import Detection

    _on(station, 7_200_000, Mode.LSB)
    assert scan.start() == ""
    assert scan.plan.kind == "voice" and scan.plan.scan_mode is Mode.LSB
    assert pump(lambda: scan._phase == "listen", timeout=3)
    dial = scan.position
    cw = Detection("cw", 1_000, 1_040, 1_020, 12, 0.5)
    voice = Detection("voice", 1_300, 2_700, 1_800, 12, 0.5)
    scan._finish_step(np.zeros(12_000, np.float32), [cw, voice])
    by_kind = {e.kind: e for e in scan.heard.entries}
    assert by_kind["cw"].mode is Mode.CW and by_kind["cw"].tune_hz == dial - 1_020
    assert by_kind["voice"].mode is Mode.LSB


def test_an_old_clip_is_recorded_again(station, scan):
    from kx3rig import bandplan
    from kx3rig.smartscan.detect import Detection
    from kx3rig.smartscan.plan import make_plan

    scan.plan = make_plan(bandplan.BY_NAME["20m"], Mode.USB, "General")
    scan.position = 14_229_000
    d = Detection("voice", 1_300, 2_900, 1_800, 12, 0.5)
    hz = scan.plan.tune_frequency(scan.position, d)
    now = time.time()
    entry = scan.heard.add(hz, "voice", Mode.USB, 12, -6, now - engine_mod.CLIP_REFRESH_S - 10,
                           clip=np.ones(10, np.float32))
    entry.last_seen = now                        # heard on every sweep since
    assert scan._needs_clip([d])
    entry.clip_at = now - 10
    assert not scan._needs_clip([d])


def test_restarting_the_same_sweep_keeps_a_cw_entry_heard_first(station, scan):
    _on(station, 14_300_000, Mode.USB)
    assert scan.start() == ""
    assert scan.plan.kind == "voice"
    scan.heard.add(14_030_000, "cw", Mode.CW, 12, -6, time.time())
    assert scan.heard.entries[0].kind == "cw"
    scan.stop()
    assert pump(lambda: station.radio.frequency == 14_300_000 and station.radio.mode is Mode.USB)
    assert scan.start() == ""
    assert [e.kind for e in scan.heard.entries] == ["cw"], "same band and sweep: the list stays"
    scan.stop(restore=False)
    _on(station, 7_200_000, Mode.LSB)
    assert scan.start() == ""
    assert scan.heard.entries == [], "another band starts a new list"
