"""Keyboard modes (PSK31, CW) against the KX3 emulator."""

import time

import pytest
from gi.repository import GLib

from kx3rig import bandplan, config
from kx3rig.cat import Mode
from kx3rig.controller import Station
from kx3rig.keyboard import cw, psk31
from kx3rig.keyboard.engine import (CW, PSK31, PSK_DIALS, PSK_OFFSET_HZ, KeyboardEngine, cw_dial, expand,
                                   heard_call)


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


def test_tune_radio_refused_during_an_ft8_contact(station, kb, monkeypatch, tmp_path):
    from kx3rig.ft8.engine import Ft8Engine

    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    ft8 = Ft8Engine(station, demo=True)
    ft8.sequencer.call_cq(tx_even=True)
    assert station.auto_keying(exclude=kb)
    assert not kb.tune_radio(bandplan.BY_NAME["20m"])
    pump(lambda: False, timeout=0.3)
    assert station.radio.frequency == 14_074_000


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
    # Fed by hand, not start(): the demo's own audio would interleave with this.
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


def test_log_a_cw_contact(station, kb, monkeypatch, tmp_path):
    from kx3rig.ft8 import adif

    kb.log_path = str(tmp_path / "log.adi")
    kb.set_mode(CW)
    with pytest.raises(ValueError):
        kb.log_contact()
    kb.set_their_call("k7cw")
    assert kb.macro("{call} DE {me} K") == "K7CW DE N0CALL K"
    entry = kb.log_contact("579", "599", name="Ann")
    text = open(kb.log_path).read()
    assert "<mode:2>CW" in text and "<rst_sent:3>579" in text and "<name:3>Ann" in text
    assert entry.dial_hz == station.radio.frequency + 700 and kb.their_call == ""
    assert ("K7CW", "20m") in adif.worked(kb.log_path)


def test_no_psk31_default_lands_in_an_ft8_or_ft4_window():
    from kx3rig.ft8.protocol import PROTOCOLS

    for name, dial in PSK_DIALS.items():
        band = bandplan.BY_NAME[name]
        lo, hi = dial + PSK_OFFSET_HZ - 30, dial + PSK_OFFSET_HZ + 30
        for proto in PROTOCOLS.values():
            d = proto.dial(band)
            if d is not None:
                assert hi < d + 200 or lo > d + 3000, (name, proto.name)


def test_demo_plays_ft8_not_psk31_on_digital_dials():
    from kx3rig.demo import DemoAudio
    from kx3rig.ft8.protocol import FT4, FT8

    for proto, name in ((FT8, "17m"), (FT4, "12m"), (FT8, "30m")):
        assert DemoAudio._keyboard_kind(proto.dial(bandplan.BY_NAME[name])) == ""
    assert DemoAudio._keyboard_kind(PSK_DIALS["20m"]) == PSK31
