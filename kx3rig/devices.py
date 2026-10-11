"""Find the Digirig on this machine: its serial port and its PipeWire audio nodes.

The Digirig Mobile is a USB hub with two functions: a Silicon Labs CP2102N serial
bridge (CAT and RTS push-to-talk) and a C-Media CM108 sound card (radio audio).
Matching helpers are pure functions so the tests can run without hardware; the
collectors at the bottom do the I/O.
"""

from __future__ import annotations

import glob
import json
import logging
import os
import re
from dataclasses import dataclass

log = logging.getLogger(__name__)

BYID_DIR = "/dev/serial/by-id"
PW_DUMP = ["pw-dump"]
PW_DUMP_TIMEOUT_S = 5

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


def pick_mic(default_source: str | None, nodes: list[AudioNode]) -> str | None:
    """Choose the voice-transmit microphone: never the Digirig input.

    The Digirig input carries the radio's own audio (KX3 PHONES); sending it to
    the KX3 MIC would loop it back on air. Use the default source unless it is
    the Digirig (or unknown), else any other source, else None (no microphone).
    """
    if default_source and not DIGIRIG_NODE_RE.search(default_source):
        return default_source
    others = [n for n in nodes if n.is_source and not n.is_digirig]
    return others[0].name if others else None


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


def scan_audio_nodes(on_done) -> None:
    """List PipeWire audio nodes with `pw-dump`, without blocking the main loop.

    Calls on_done(nodes) on the main loop, or on_done(None) when the scan fails
    or takes longer than PW_DUMP_TIMEOUT_S. Discovery runs in a separate process
    because an in-process GStreamer DeviceMonitor deadlocks once a pipewiresrc
    in the same process is streaming (reproduced with PipeWire 1.0.5 and the
    Digirig, 2026-10-11).
    """
    from gi.repository import Gio, GLib

    try:
        proc = Gio.Subprocess.new(PW_DUMP, Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_SILENCE)
    except GLib.Error as exc:
        log.warning("audio device scan failed: %s", exc.message)
        GLib.idle_add(on_done, None)
        return
    cancel = Gio.Cancellable()
    state = {"timer": 0}

    def expired() -> bool:
        state["timer"] = 0
        cancel.cancel()
        proc.force_exit()
        return False

    def finished(p, result) -> None:
        if state["timer"]:
            GLib.source_remove(state["timer"])
        try:
            _, out, _ = p.communicate_utf8_finish(result)
            nodes = parse_pw_dump(out or "")
        except Exception as exc:   # anything (e.g. RecursionError from json): on_done must still run
            log.warning("audio device scan failed: %s", getattr(exc, "message", exc))
            nodes = None
        on_done(nodes)

    state["timer"] = GLib.timeout_add_seconds(PW_DUMP_TIMEOUT_S, expired)
    proc.communicate_utf8_async(None, cancel, finished)


def parse_pw_dump(text: str) -> list[AudioNode]:
    """Audio sources and sinks from `pw-dump` JSON. Raises ValueError if it isn't pw-dump output."""
    data = json.loads(text)
    if not isinstance(data, list):
        raise ValueError("pw-dump output is not a list")
    nodes: list[AudioNode] = []
    for obj in data:
        if not isinstance(obj, dict) or obj.get("type") != "PipeWire:Interface:Node":
            continue
        info = obj.get("info")
        props = info.get("props") if isinstance(info, dict) else None
        if not isinstance(props, dict):
            continue
        name, media_class = props.get("node.name"), props.get("media.class")
        if not isinstance(name, str) or media_class not in ("Audio/Source", "Audio/Sink"):
            continue
        description = props.get("node.description")
        nodes.append(AudioNode(name, media_class, description if isinstance(description, str) else ""))
    return nodes
