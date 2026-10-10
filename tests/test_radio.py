"""Drive the real RadioLink against the KX3 emulator."""

import time

import pytest

from kx3rig import cat
from kx3rig.cat import DataSubmode, Mode
from kx3rig.fakeradio import FakeKX3
from kx3rig.radio import Link, PortError, RadioLink

PORT = "/dev/serial/by-id/usb-Silicon_Labs_CP2102N_test-if00-port0"


def wait_for(predicate, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


class Harness:
    def __init__(self, fake=None, find_port=lambda: PORT, holders=lambda p: [], factory=None):
        self.fake = fake or FakeKX3()
        self.states = []
        self.events = []
        self.link = RadioLink(
            on_state=self.states.append,
            on_event=lambda k, m: self.events.append(k),
            port_factory=factory or (lambda path: self.fake),
            find_port=find_port,
            port_holders=holders,
        )

    def __enter__(self):
        self.link.start()
        return self

    def __exit__(self, *exc):
        self.link.stop()


def test_connects_and_reads_state():
    with Harness() as h:
        assert wait_for(lambda: h.link.state.link is Link.CONNECTED)
        assert wait_for(lambda: h.link.state.frequency == 14_074_000)
        s = h.link.state
        assert s.mode is Mode.DATA
        assert s.power_set == 5
        assert s.options.is_kx3
        assert s.firmware == pytest.approx(2.93)
        assert "connected" in h.events


def test_never_asserts_rts_while_connecting():
    with Harness() as h:
        assert wait_for(lambda: h.link.state.link is Link.CONNECTED)
        time.sleep(0.3)
    assert True not in h.fake.rts_history


def test_first_contact_is_id_and_only_allowed_commands_sent():
    with Harness() as h:
        assert wait_for(lambda: h.link.state.link is Link.CONNECTED)
        time.sleep(0.5)
    assert h.fake.received[0] == "ID;"
    assert all(cat.is_allowed(c) for c in h.fake.received)


def test_restores_k2_and_ai_left_by_other_software():
    fake = FakeKX3(k2=2, ai=1)
    with Harness(fake) as h:
        assert wait_for(lambda: h.link.state.link is Link.CONNECTED)
        assert fake.k2 == 0 and fake.ai == 0
    assert fake.k2 == 2 and fake.ai == 1
    assert fake.closed


def test_radio_off_reports_no_reply_and_sends_nothing_else():
    fake = FakeKX3(powered=False)
    with Harness(fake) as h:
        assert wait_for(lambda: h.link.state.link is Link.NO_REPLY)
        time.sleep(0.3)
    assert set(fake.received) == {"ID;"}


def test_garbled_reply_stops_after_id():
    fake = FakeKX3(garbled=True)
    with Harness(fake) as h:
        assert wait_for(lambda: "garbled" in h.events)
        assert h.link.state.link is Link.NO_REPLY
    assert set(fake.received) == {"ID;"}


def test_radio_turned_on_later_connects():
    fake = FakeKX3(powered=False)
    with Harness(fake) as h:
        assert wait_for(lambda: h.link.state.link is Link.NO_REPLY)
        fake.powered = True
        assert wait_for(lambda: h.link.state.link is Link.CONNECTED, timeout=5)


def test_no_interface():
    with Harness(find_port=lambda: None) as h:
        assert wait_for(lambda: len(h.events) == 0 and h.link.state.link is Link.NO_INTERFACE)


def test_port_held_by_wsjtx_is_busy_and_not_opened():
    opened = []
    h = Harness(holders=lambda p: [(42, "wsjtx")], factory=lambda p: opened.append(p))
    with h:
        assert wait_for(lambda: h.link.state.link is Link.BUSY)
        assert h.link.state.busy_with == "WSJT-X"
    assert opened == []


def test_permission_denied():
    def factory(path):
        raise PortError(Link.PERMISSION, "denied")
    with Harness(factory=factory) as h:
        assert wait_for(lambda: h.link.state.link is Link.PERMISSION)


def test_set_frequency_mode_power_are_verified():
    with Harness() as h:
        assert wait_for(lambda: h.link.state.link is Link.CONNECTED)
        h.link.set_frequency(7_185_000)
        h.link.set_mode(Mode.LSB)
        h.link.set_power(3)
        assert wait_for(lambda: h.fake.frequency == 7_185_000 and h.fake.mode is Mode.LSB and h.fake.power == 3)
        assert wait_for(lambda: h.link.state.mode is Mode.LSB and h.link.state.power_set == 3)
        assert "FA00007185000;" in h.fake.received
        i = h.fake.received.index("FA00007185000;")
        assert h.fake.received[i + 1] == "FA;"   # SET followed by its GET


def test_data_mode_sets_submode_after_md():
    with Harness(FakeKX3(mode=Mode.USB)) as h:
        assert wait_for(lambda: h.link.state.link is Link.CONNECTED)
        h.link.set_mode(Mode.DATA, DataSubmode.DATA_A)
        assert wait_for(lambda: h.link.state.mode is Mode.DATA)
        sent = h.fake.received
        assert sent.index("DT0;") > sent.index("MD6;")


def test_power_is_capped():
    with Harness() as h:
        assert wait_for(lambda: h.link.state.link is Link.CONNECTED)
        h.link.set_power(50)
        assert wait_for(lambda: h.fake.power == 10)


def test_ptt_uses_rts_and_watchdog_releases():
    with Harness() as h:
        assert wait_for(lambda: h.link.state.link is Link.CONNECTED)
        assert h.link.ptt(True, limit_s=0.5)
        assert h.fake.rts is True
        assert wait_for(lambda: h.link.state.transmitting)
        assert wait_for(lambda: h.fake.rts is False, timeout=3)
        assert "watchdog" in h.events
        assert wait_for(lambda: not h.link.state.transmitting)


def test_ptt_refused_when_not_connected():
    with Harness(FakeKX3(powered=False)) as h:
        assert wait_for(lambda: h.link.state.link is Link.NO_REPLY)
        assert h.link.ptt(True) is False
        assert h.fake.rts is False


def test_stop_while_transmitting_unkeys():
    fake = FakeKX3()
    with Harness(fake) as h:
        assert wait_for(lambda: h.link.state.link is Link.CONNECTED)
        h.link.ptt(True, limit_s=30)
    assert fake.rts is False
    assert "RX;" in fake.received


def test_radio_switched_off_while_connected():
    fake = FakeKX3()
    with Harness(fake) as h:
        assert wait_for(lambda: h.link.state.link is Link.CONNECTED)
        fake.powered = False
        assert wait_for(lambda: h.link.state.link is Link.NO_REPLY)
