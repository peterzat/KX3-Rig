"""Keyboard modes (PSK31, CW) against the KX3 emulator."""

import time

import pytest
from gi.repository import GLib

from kx3rig import bandplan, config
from kx3rig.cat import Mode
from kx3rig.controller import Station
from kx3rig.keyboard import cw, psk31
from kx3rig.keyboard.engine import CW, PSK31, KeyboardEngine, cw_dial, expand, heard_call


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
def kb(station):
    k = KeyboardEngine(station)
    yield k
    k.halt()
    k.stop()


def test_heard_call_and_macros():
    assert heard_call("cq cq de W7PSK W7PSK pse k", "N0CALL") == "W7PSK"
    assert heard_call("N0CALL de K9ABC k", "N0CALL") == "K9ABC"
    assert heard_call("nothing here") == ""
    assert expand("{call} de {me} k", "N0CALL", "W7PSK", "CN87", "") == "W7PSK de N0CALL k"


def test_cw_dial_puts_the_tone_on_the_calling_frequency():
    assert cw_dial(bandplan.BY_NAME["20m"]) == 14_060_000 - 700


def test_tune_radio_and_send_psk31(station, kb):
    assert kb.tune_radio(bandplan.BY_NAME["20m"])
    assert pump(lambda: station.radio.frequency == 14_070_000 and station.radio.mode is Mode.DATA)
    events, sent = [], []
    kb.connect("sending", lambda e, on, t: events.append(on))
    kb.connect("sent-text", lambda e, t: sent.append(t))
    assert kb.send("cq test").allowed
    assert kb.busy and not kb.send("again").allowed
    assert pump(lambda: events == [True, False], timeout=8)
    assert "".join(sent).strip() == "cq test"
    assert kb.lines[-1].ours


def test_cw_is_checked_as_cw(station, kb):
    kb.set_mode(CW)
    station.tune_to(14_259_300)               # phone segment: no data, but CW is fine
    assert pump(lambda: station.radio.frequency == 14_259_300)
    assert kb.check_tx("test").allowed
    kb.set_mode(PSK31)
    assert not kb.check_tx("test").allowed


def test_long_messages_and_wrong_mode_are_refused(station, kb):
    assert "too long" in kb.check_tx("x" * 600).reason
    station.select_mode(Mode.USB)
    assert pump(lambda: station.radio.mode is Mode.USB)
    assert "DATA" in kb.check_tx("hi").reason


def test_receives_psk31_and_cw(station, kb):
    got = []
    kb.connect("received", lambda e, t: got.append(t))
    kb.start()
    audio = psk31.demo_signal([("cq cq de W7PSK W7PSK k", 1000)], 12, snr_db=15, seed=1)
    for i in range(0, len(audio), 1200):
        kb._feed(audio[i:i + 1200], 0.0)
    kb._drain()
    assert "W7PSK" in "".join(got)
    assert kb.suggested_call() == "W7PSK"
    kb.set_mode(CW)
    got.clear()
    audio = cw.demo_signal([("CQ DE K7CW K7CW K", 20, 700)], 15, snr_db=15, seed=2)
    for i in range(0, len(audio), 1200):
        kb._feed(audio[i:i + 1200], 0.0)
    kb._drain()
    assert "K7CW" in "".join(got)


def test_halt_stops_sending(station, kb):
    kb.tune_radio(bandplan.BY_NAME["20m"])
    assert pump(lambda: station.radio.frequency == 14_070_000 and station.radio.mode is Mode.DATA)
    assert kb.send("a long message that takes a while to send").allowed
    kb.halt()
    assert not kb.busy and not station.data_transmitting


def test_find_cw_tone(station, kb):
    kb.set_mode(CW)
    audio = cw.demo_signal([("TEST TEST", 20, 850)], 4, snr_db=15, seed=3)
    for i in range(0, len(audio), 1200):
        kb._feed(audio[i:i + 1200], 0.0)
    assert kb.find_cw_tone() == pytest.approx(850, abs=10)
    assert kb.offset_hz == pytest.approx(850, abs=10)
