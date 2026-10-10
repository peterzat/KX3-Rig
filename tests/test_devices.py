import os

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
