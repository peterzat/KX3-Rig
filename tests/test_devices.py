import json
import os
import time

import pytest
from gi.repository import GLib

from kx3rig import devices
from kx3rig.devices import AudioNode, pick_digirig_audio, pick_serial_port

DIGIRIG_IN = "alsa_input.usb-C-Media_Electronics_Inc._USB_PnP_Sound_Device-00.mono-fallback"
DIGIRIG_OUT = "alsa_output.usb-C-Media_Electronics_Inc._USB_PnP_Sound_Device-00.analog-stereo"
BUILTIN_IN = "alsa_input.pci-0000_00_1f.3.analog-stereo"
BUILTIN_OUT = "alsa_output.pci-0000_00_1f.3.analog-stereo"
CP2102N = "usb-Silicon_Labs_CP2102N_USB_to_UART_Bridge_Controller_a4b1-if00-port0"


def test_serial_prefers_cp2102_byid():
    names = ["usb-FTDI_FT232R-if00-port0", CP2102N]
    assert pick_serial_port(names, ["/dev/ttyUSB0", "/dev/ttyUSB1"]) == f"/dev/serial/by-id/{CP2102N}"


def test_serial_falls_back_to_ttyusb_only_without_byid():
    assert pick_serial_port([], ["/dev/ttyUSB1", "/dev/ttyUSB0"]) == "/dev/ttyUSB0"


def test_serial_ignores_other_usb_serial_devices():
    # A different adapter is present; do not guess it is the Digirig.
    assert pick_serial_port(["usb-FTDI_FT232R-if00-port0"], ["/dev/ttyUSB0"]) is None


def test_serial_none_when_nothing_plugged_in():
    assert pick_serial_port([], []) is None


def test_digirig_audio_picks_cmedia_not_builtin():
    nodes = [
        AudioNode(BUILTIN_IN, "Audio/Source"),
        AudioNode(BUILTIN_OUT, "Audio/Sink"),
        AudioNode(DIGIRIG_IN, "Audio/Source"),
        AudioNode(DIGIRIG_OUT, "Audio/Sink"),
    ]
    found = pick_digirig_audio(nodes)
    assert found.source.name == DIGIRIG_IN
    assert found.sink.name == DIGIRIG_OUT
    assert found.complete


def test_digirig_audio_skips_monitor_sources():
    nodes = [AudioNode(DIGIRIG_OUT + ".monitor", "Audio/Source"), AudioNode(DIGIRIG_OUT, "Audio/Sink")]
    found = pick_digirig_audio(nodes)
    assert found.source is None
    assert not found.complete


def test_digirig_audio_absent():
    found = pick_digirig_audio([AudioNode(BUILTIN_IN, "Audio/Source")])
    assert found.source is None and found.sink is None


def test_processes_holding_finds_owner(tmp_path):
    proc = tmp_path / "proc"
    target = tmp_path / "ttyUSB0"
    target.write_text("")
    for pid, comm, holds in [(101, "wsjtx", True), (202, "bash", False)]:
        fd = proc / str(pid) / "fd"
        fd.mkdir(parents=True)
        (proc / str(pid) / "comm").write_text(comm + "\n")
        os.symlink(target if holds else tmp_path / "other", fd / "3")
    assert devices.processes_holding(str(target), str(proc)) == [(101, "wsjtx")]


def test_friendly_app_name():
    assert devices.friendly_app_name("wsjtx") == "WSJT-X"
    assert devices.friendly_app_name("mystery") == "mystery"


def test_pick_mic_keeps_non_digirig_default():
    nodes = [AudioNode(BUILTIN_IN, "Audio/Source"), AudioNode(DIGIRIG_IN, "Audio/Source")]
    assert devices.pick_mic(BUILTIN_IN, nodes) == BUILTIN_IN


def test_pick_mic_never_uses_digirig_input():
    nodes = [
        AudioNode(DIGIRIG_IN, "Audio/Source"),
        AudioNode(DIGIRIG_OUT + ".monitor", "Audio/Source"),
        AudioNode(BUILTIN_OUT, "Audio/Sink"),
        AudioNode(BUILTIN_IN, "Audio/Source"),
    ]
    assert devices.pick_mic(DIGIRIG_IN, nodes) == BUILTIN_IN
    assert devices.pick_mic(None, nodes) == BUILTIN_IN


def test_pick_mic_none_when_only_digirig():
    nodes = [AudioNode(DIGIRIG_IN, "Audio/Source"), AudioNode(BUILTIN_OUT + ".monitor", "Audio/Source")]
    assert devices.pick_mic(DIGIRIG_IN, nodes) is None
    assert devices.pick_mic(None, []) is None


# Trimmed from `pw-dump` on this machine with the Digirig attached (PipeWire 1.0.5).
PW_DUMP_SAMPLE = json.dumps([
    {"id": 0, "type": "PipeWire:Interface:Core", "info": {"props": {}}},
    {"id": 68, "type": "PipeWire:Interface:Device",
     "info": {"props": {"device.description": "CM108 Audio Controller", "media.class": "Audio/Device"}}},
    {"id": 51, "type": "PipeWire:Interface:Node",
     "info": {"props": {"node.name": BUILTIN_OUT, "media.class": "Audio/Sink",
                        "node.description": "Built-in Audio Analog Stereo"}}},
    {"id": 52, "type": "PipeWire:Interface:Node",
     "info": {"props": {"node.name": BUILTIN_IN, "media.class": "Audio/Source"}}},
    {"id": 65, "type": "PipeWire:Interface:Node",
     "info": {"props": {"node.name": DIGIRIG_IN, "media.class": "Audio/Source",
                        "node.description": "CM108 Audio Controller Mono"}}},
    {"id": 67, "type": "PipeWire:Interface:Node",
     "info": {"props": {"node.name": DIGIRIG_OUT, "media.class": "Audio/Sink"}}},
    {"id": 59, "type": "PipeWire:Interface:Node",
     "info": {"props": {"node.name": "speech-dispatcher-dummy", "media.class": "Stream/Output/Audio"}}},
    {"id": 70, "type": "PipeWire:Interface:Node", "info": {"props": {"media.class": "Audio/Sink"}}},
    {"id": 71, "type": "PipeWire:Interface:Node", "info": None},
    "not an object",
])


def test_parse_pw_dump_finds_audio_nodes():
    nodes = devices.parse_pw_dump(PW_DUMP_SAMPLE)
    assert [(n.name, n.media_class) for n in nodes] == [
        (BUILTIN_OUT, "Audio/Sink"), (BUILTIN_IN, "Audio/Source"),
        (DIGIRIG_IN, "Audio/Source"), (DIGIRIG_OUT, "Audio/Sink"),
    ]
    assert nodes[2].description == "CM108 Audio Controller Mono"
    found = pick_digirig_audio(nodes)
    assert found.source.name == DIGIRIG_IN and found.sink.name == DIGIRIG_OUT


@pytest.mark.parametrize("bad", ["", "not json", "{}", '{"type": "PipeWire:Interface:Node"}'])
def test_parse_pw_dump_rejects_other_output(bad):
    with pytest.raises(ValueError):
        devices.parse_pw_dump(bad)


def _scan(monkeypatch, command, timeout_s=5):
    monkeypatch.setattr(devices, "PW_DUMP", command)
    monkeypatch.setattr(devices, "PW_DUMP_TIMEOUT_S", timeout_s)
    results = []
    devices.scan_audio_nodes(results.append)
    ctx = GLib.MainContext.default()
    deadline = time.monotonic() + timeout_s + 3
    while not results and time.monotonic() < deadline:
        ctx.iteration(False) or time.sleep(0.01)
    return results


def test_scan_reports_nodes(monkeypatch, tmp_path):
    dump = tmp_path / "dump.json"
    dump.write_text(PW_DUMP_SAMPLE)
    results = _scan(monkeypatch, ["cat", str(dump)])
    assert len(results) == 1 and [n.name for n in results[0]][2] == DIGIRIG_IN


@pytest.mark.parametrize("command", [["true"], ["kx3rig-no-such-program"]])
def test_scan_failure_reports_none(monkeypatch, command):
    assert _scan(monkeypatch, command) == [None]


def test_scan_reports_none_when_parsing_raises_other_errors(monkeypatch):
    def boom(text):
        raise RecursionError("deeply nested")
    monkeypatch.setattr(devices, "parse_pw_dump", boom)
    assert _scan(monkeypatch, ["true"]) == [None]


def test_scan_that_hangs_times_out(monkeypatch):
    start = time.monotonic()
    assert _scan(monkeypatch, ["sleep", "30"], timeout_s=1) == [None]
    assert time.monotonic() - start < 4
