"""Find the Digirig on this machine: its serial port and its PipeWire audio nodes.

The Digirig Mobile is a USB hub with two functions: a Silicon Labs CP2102N serial
bridge (CAT and RTS push-to-talk) and a C-Media CM108 sound card (radio audio).
Matching helpers are pure functions so the tests can run without hardware; the
collectors at the bottom do the I/O.
"""

from __future__ import annotations

import glob
import os
import re
from dataclasses import dataclass

BYID_DIR = "/dev/serial/by-id"

# Matches both CP2102 and CP2102N by-id names, e.g.
# usb-Silicon_Labs_CP2102N_USB_to_UART_Bridge_Controller_<serial>-if00-port0
CP210X_RE = re.compile(r"CP2102", re.IGNORECASE)

# PipeWire node names for the Digirig's CM108, e.g.
# alsa_input.usb-C-Media_Electronics_Inc._USB_PnP_Sound_Device-00.mono-fallback
DIGIRIG_NODE_RE = re.compile(r"usb-C-Media|USB_PnP_Sound_Device", re.IGNORECASE)


def pick_serial_port(byid_names: list[str], ttyusb: list[str]) -> str | None:
    """Choose the Digirig serial port.

    Prefers the stable /dev/serial/by-id path of a CP2102; falls back to the
    first /dev/ttyUSB* only when no by-id entries exist at all (some kernels or
    containers lack the by-id symlinks).
    """
    for name in sorted(byid_names):
        if CP210X_RE.search(name):
            return os.path.join(BYID_DIR, name)
    if not byid_names and ttyusb:
        return sorted(ttyusb)[0]
    return None


@dataclass(frozen=True)
class AudioNode:
    name: str          # PipeWire node.name, used as the GStreamer target-object
    media_class: str   # "Audio/Source" or "Audio/Sink"
    description: str = ""

    @property
    def is_source(self) -> bool:
        return self.media_class == "Audio/Source" and not self.name.endswith(".monitor")

    @property
    def is_sink(self) -> bool:
        return self.media_class == "Audio/Sink"

    @property
    def is_digirig(self) -> bool:
        return bool(DIGIRIG_NODE_RE.search(self.name))


@dataclass(frozen=True)
class DigirigAudio:
    source: AudioNode | None   # radio receive audio (KX3 PHONES -> computer)
    sink: AudioNode | None     # radio transmit audio (computer -> KX3 MIC)

    @property
    def complete(self) -> bool:
        return self.source is not None and self.sink is not None


def pick_digirig_audio(nodes: list[AudioNode]) -> DigirigAudio:
    source = next((n for n in nodes if n.is_digirig and n.is_source), None)
    sink = next((n for n in nodes if n.is_digirig and n.is_sink), None)
    return DigirigAudio(source, sink)


def processes_holding(path: str, proc_root: str = "/proc") -> list[tuple[int, str]]:
    """Return (pid, command name) for processes with `path` open.

    Used to explain a busy serial port ("WSJT-X is using the radio"). Only
    processes owned by this user are visible, which covers the cases we care
    about. Unreadable entries are skipped.
    """
    target = os.path.realpath(path)
    found: list[tuple[int, str]] = []
    me = os.getpid()
    for entry in os.listdir(proc_root):
        if not entry.isdigit() or int(entry) == me:
            continue
        fd_dir = os.path.join(proc_root, entry, "fd")
        try:
            fds = os.listdir(fd_dir)
        except OSError:
            continue
        for fd in fds:
            try:
                if os.path.realpath(os.path.join(fd_dir, fd)) == target:
                    break
            except OSError:
                continue
        else:
            continue
        try:
            with open(os.path.join(proc_root, entry, "comm"), encoding="utf-8") as f:
                comm = f.read().strip()
        except OSError:
            comm = "unknown"
        found.append((int(entry), comm))
    return found


def friendly_app_name(comm: str) -> str:
    """Map a process name to what the operator would recognize."""
    known = {
        "wsjtx": "WSJT-X",
        "jt9": "WSJT-X",
        "js8call": "JS8Call",
        "fldigi": "fldigi",
        "flrig": "flrig",
        "rigctld": "rigctld (Hamlib)",
        "rigctl": "rigctl (Hamlib)",
        "ModemManager": "ModemManager",
        "minicom": "minicom",
        "screen": "screen",
    }
    return known.get(comm, comm)


# --- I/O collectors -----------------------------------------------------------

def find_serial_port() -> str | None:
    byid = [os.path.basename(p) for p in glob.glob(os.path.join(BYID_DIR, "*"))]
    return pick_serial_port(byid, glob.glob("/dev/ttyUSB*"))


def list_audio_nodes() -> list[AudioNode]:
    """Enumerate PipeWire audio nodes through GStreamer's device monitor."""
    import gi

    gi.require_version("Gst", "1.0")
    from gi.repository import Gst

    if not Gst.is_initialized():
        Gst.init(None)
    monitor = Gst.DeviceMonitor()
    monitor.add_filter("Audio/Source", None)
    monitor.add_filter("Audio/Sink", None)
    nodes: list[AudioNode] = []
    if not monitor.start():
        return nodes
    try:
        for dev in monitor.get_devices() or []:
            props = dev.get_properties()
            if props is None or not props.has_field("node.name"):
                continue
            media_class = props.get_value("media.class") if props.has_field("media.class") else dev.get_device_class()
            nodes.append(AudioNode(props.get_value("node.name"), media_class, dev.get_display_name()))
    finally:
        monitor.stop()
    return nodes


def find_digirig_audio() -> DigirigAudio:
    return pick_digirig_audio(list_audio_nodes())
