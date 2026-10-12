"""Audio plumbing through PipeWire (via GStreamer).

Three paths:

* Receive: Digirig input (KX3 PHONES) -> 12 kHz mono samples for the waterfall
  and FT8 decoder, and a copy to the laptop speakers so the operator can hear
  the radio (plugging the Digirig into PHONES silences the KX3's own speaker).
* Voice transmit: laptop or headset microphone -> Digirig output (KX3 MIC),
  only while push-to-talk is held.
* Digital transmit: generated samples (FT8 tones) -> Digirig output.

Every stream names its target node explicitly and sets node.dont-reconnect so
PipeWire never silently re-routes it. That matters for safety: the listening
stream must never land on the Digirig output (it would be transmitted), and the
receive stream must never fall back to the laptop microphone.
"""

from __future__ import annotations

import subprocess
import threading
import time
from collections.abc import Callable

import gi
import numpy as np

gi.require_version("Gst", "1.0")
from gi.repository import GLib, Gst  # noqa: E402

DSP_RATE = 12_000
OUT_RATE = 48_000

if not Gst.is_initialized():
    Gst.init(None)


def default_node_name(kind: str) -> str | None:
    """node.name of the default sink ("sink") or source ("source")."""
    target = "@DEFAULT_AUDIO_SINK@" if kind == "sink" else "@DEFAULT_AUDIO_SOURCE@"
    try:
        out = subprocess.run(["wpctl", "inspect", target], capture_output=True, text=True, timeout=3).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    return parse_wpctl_node_name(out)


def parse_wpctl_node_name(text: str) -> str | None:
    for line in text.splitlines():
        line = line.strip().lstrip("*").strip()
        if line.startswith("node.name = "):
            return line.split("=", 1)[1].strip().strip('"')
    return None


def _stream_props(role: str, name: str) -> Gst.Structure:
    s = Gst.Structure.new_empty("props")
    s.set_value("node.dont-reconnect", True)
    s.set_value("media.role", role)
    s.set_value("node.description", name)
    return s


def _make(factory: str, name: str | None = None, **props) -> Gst.Element:
    el = Gst.ElementFactory.make(factory, name)
    if el is None:
        raise RuntimeError(f"GStreamer element {factory} is not installed")
    for key, value in props.items():
        el.set_property(key.replace("_", "-"), value)
    return el


def _link(*elements: Gst.Element) -> None:
    for a, b in zip(elements, elements[1:]):
        if not a.link(b):
            raise RuntimeError(f"cannot link {a.get_name()} -> {b.get_name()}")


def _caps(fmt: str) -> Gst.Element:
    return _make("capsfilter", caps=Gst.Caps.from_string(fmt))


class _Pipeline:
    """A pipeline with a bus watch that reports errors to a callback."""

    def __init__(self, name: str, on_error: Callable[[str], None] | None):
        self.pipe = Gst.Pipeline.new(name)
        self._on_error = on_error
        bus = self.pipe.get_bus()
        bus.add_signal_watch()
        self._watch = bus.connect("message", self._on_message)
        self.on_eos: Callable[[], None] | None = None
        self.on_element: Callable[[Gst.Message], None] | None = None

    def add(self, *elements: Gst.Element) -> None:
        for el in elements:
            self.pipe.add(el)

    def _on_message(self, _bus, msg: Gst.Message) -> None:
        if msg.type == Gst.MessageType.ERROR:
            err, _debug = msg.parse_error()
            if self._on_error:
                self._on_error(err.message)
        elif msg.type == Gst.MessageType.EOS:
            if self.on_eos:
                self.on_eos()
        elif msg.type == Gst.MessageType.ELEMENT and self.on_element:
            self.on_element(msg)

    def start(self) -> None:
        if self.pipe.set_state(Gst.State.PLAYING) == Gst.StateChangeReturn.FAILURE:
            raise RuntimeError(f"{self.pipe.get_name()} failed to start")

    def stop(self) -> None:
        self.pipe.set_state(Gst.State.NULL)
        bus = self.pipe.get_bus()
        bus.disconnect(self._watch)
        bus.remove_signal_watch()


class ReceiveAudio:
    """Digirig input -> DSP callback (12 kHz float32) + laptop speakers.

    on_samples(samples, end_time) runs on a GStreamer streaming thread;
    end_time is the wall-clock time (time.time()) of the last sample.
    """

    def __init__(
        self,
        source_node: str,
        listen_sink_node: str | None,
        on_samples: Callable[[np.ndarray, float], None],
        on_error: Callable[[str], None] | None = None,
        volume: float = 0.6,
    ):
        self._on_samples = on_samples
        self._p = _Pipeline("kx3rig-rx", on_error)
        src = _make("pipewiresrc", target_object=source_node, client_name="KX3-Rig")
        src.set_property("stream-properties", _stream_props("Communication", "KX3-Rig radio receive"))
        tee = _make("tee")
        q_dsp = _make("queue", max_size_time=200_000_000, leaky=2)
        dsp_caps = _caps(f"audio/x-raw,format=F32LE,rate={DSP_RATE},channels=1")
        sink = _make("appsink", emit_signals=True, sync=False, max_buffers=200, drop=True)
        sink.connect("new-sample", self._on_new_sample)
        self._p.add(src, tee, q_dsp, conv1 := _make("audioconvert"), rs1 := _make("audioresample"), dsp_caps, sink)
        _link(src, tee)
        _link(tee, q_dsp, conv1, rs1, dsp_caps, sink)

        self.volume = _make("volume", volume=float(volume))
        if listen_sink_node:
            q_out = _make("queue", max_size_time=100_000_000, leaky=2)
            out = _make("pipewiresink", target_object=listen_sink_node, client_name="KX3-Rig")
            out.set_property("stream-properties", _stream_props("Communication", "KX3-Rig radio audio"))
            out.set_property("sync", False)
            self._p.add(q_out, conv2 := _make("audioconvert"), rs2 := _make("audioresample"), self.volume, out)
            _link(tee, q_out, conv2, rs2, self.volume, out)

    def _on_new_sample(self, sink) -> Gst.FlowReturn:
        sample = sink.emit("pull-sample")
        buf = sample.get_buffer()
        ok, info = buf.map(Gst.MapFlags.READ)
        if not ok:
            return Gst.FlowReturn.OK
        try:
            samples = np.frombuffer(info.data, dtype=np.float32).copy()
        finally:
            buf.unmap(info)
        self._on_samples(samples, time.time())
        return Gst.FlowReturn.OK

    def set_volume(self, volume: float) -> None:
        self.volume.set_property("volume", max(0.0, min(1.5, float(volume))))

    def set_muted(self, muted: bool) -> None:
        self.volume.set_property("mute", bool(muted))

    def start(self) -> None:
        self._p.start()

    def stop(self) -> None:
        self._p.stop()


class VoiceTransmit:
    """Microphone -> Digirig output, for SSB/AM/FM voice while PTT is held.

    Reports the microphone level (peak dBFS) through on_level on the main loop
    so the operator can see they are being heard.
    """

    def __init__(
        self,
        mic_node: str | None,
        digirig_sink_node: str,
        gain: float,
        on_level: Callable[[float], None] | None = None,
        on_error: Callable[[str], None] | None = None,
        to_radio: bool = True,
    ):
        self._p = _Pipeline("kx3rig-voice", on_error)
        props = {"client_name": "KX3-Rig"}
        if mic_node:
            props["target_object"] = mic_node
        src = _make("pipewiresrc", **props)
        src.set_property("stream-properties", _stream_props("Communication", "KX3-Rig microphone"))
        self.gain = _make("volume", volume=float(gain))
        level = _make("level", interval=50_000_000, post_messages=True)
        if to_radio:
            out = _make("pipewiresink", target_object=digirig_sink_node, client_name="KX3-Rig")
            out.set_property("stream-properties", _stream_props("Communication", "KX3-Rig transmit audio"))
        else:
            out = _make("fakesink", sync=False)  # mic test: meter only, nothing sent anywhere
        caps = _caps(f"audio/x-raw,rate={OUT_RATE},channels=1")
        self._p.add(src, c1 := _make("audioconvert"), r1 := _make("audioresample"), caps, self.gain, level,
                    c2 := _make("audioconvert"), out)
        _link(src, c1, r1, caps, self.gain, level, c2, out)
        self._on_level = on_level
        self._p.on_element = self._on_element

    def _on_element(self, msg: Gst.Message) -> None:
        s = msg.get_structure()
        if s is None or s.get_name() != "level" or self._on_level is None:
            return
        peaks = s.get_value("peak")
        if peaks:
            self._on_level(float(max(peaks)))

    def set_gain(self, gain: float) -> None:
        self.gain.set_property("volume", max(0.0, min(2.0, float(gain))))

    def start(self) -> None:
        self._p.start()

    def stop(self) -> None:
        self._p.stop()


class DataTransmit:
    """Plays a block of generated audio (e.g. one FT8 transmission) to the Digirig.

    on_done runs on the main loop when playback finishes or is stopped.
    """

    def __init__(
        self,
        samples: np.ndarray,
        rate: int,
        digirig_sink_node: str,
        level: float,
        on_done: Callable[[], None] | None = None,
        on_error: Callable[[str], None] | None = None,
    ):
        self._done_cb = on_done
        self._finished = threading.Event()
        self._p = _Pipeline("kx3rig-data-tx", on_error)
        data = (np.clip(samples, -1.0, 1.0) * float(level)).astype(np.float32)
        src = _make("appsrc", format=Gst.Format.TIME, is_live=False, block=False)
        src.set_property("caps", Gst.Caps.from_string(f"audio/x-raw,format=F32LE,rate={rate},channels=1,layout=interleaved"))
        out = _make("pipewiresink", target_object=digirig_sink_node, client_name="KX3-Rig")
        out.set_property("stream-properties", _stream_props("Communication", "KX3-Rig transmit audio"))
        self._p.add(src, c := _make("audioconvert"), r := _make("audioresample"), out)
        _link(src, c, r, out)
        self._p.on_eos = self._finish
        buf = Gst.Buffer.new_wrapped(data.tobytes())
        buf.pts = 0
        buf.duration = Gst.util_uint64_scale(len(data), Gst.SECOND, rate)
        self._src = src
        self._buf = buf

    def start(self) -> None:
        self._p.start()
        self._src.emit("push-buffer", self._buf)
        self._src.emit("end-of-stream")

    def _finish(self) -> None:
        if self._finished.is_set():
            return
        self._finished.set()
        self._p.stop()
        if self._done_cb:
            GLib.idle_add(self._done_cb)

    def stop(self) -> None:
        self._finish()


class ClipPlayer:
    """Plays recorded receive audio (a Smartscan clip) to a listening output.

    sink_node is a PipeWire node name, never the Digirig (the caller picks it
    the same way as for listening), or "auto" for the platform default where
    there is no PipeWire (demo mode on macOS). on_done runs on the main loop.
    """

    def __init__(self, samples: np.ndarray, rate: int, sink_node: str, volume: float,
                 on_done: Callable[[], None] | None = None, on_error: Callable[[str], None] | None = None):
        self._done_cb = on_done
        self._finished = threading.Event()
        self._p = _Pipeline("kx3rig-clip", on_error)
        peak = float(np.max(np.abs(samples))) if len(samples) else 0.0
        gain = 0.5 / peak if peak > 0.5 else 1.0
        data = np.clip(np.asarray(samples, np.float32) * gain, -1.0, 1.0).astype(np.float32)
        src = _make("appsrc", format=Gst.Format.TIME, is_live=False, block=False)
        src.set_property("caps", Gst.Caps.from_string(f"audio/x-raw,format=F32LE,rate={rate},channels=1,layout=interleaved"))
        if sink_node == "auto":
            out = _make("autoaudiosink")
        else:
            out = _make("pipewiresink", target_object=sink_node, client_name="KX3-Rig")
            out.set_property("stream-properties", _stream_props("Communication", "KX3-Rig clip replay"))
        vol = _make("volume", volume=max(0.0, min(1.5, float(volume))))
        self._p.add(src, c := _make("audioconvert"), r := _make("audioresample"), vol, out)
        _link(src, c, r, vol, out)
        self._p.on_eos = self._finish
        buf = Gst.Buffer.new_wrapped(data.tobytes())
        buf.pts = 0
        buf.duration = Gst.util_uint64_scale(len(data), Gst.SECOND, rate)
        self._src = src
        self._buf = buf

    def start(self) -> None:
        self._p.start()
        self._src.emit("push-buffer", self._buf)
        self._src.emit("end-of-stream")

    def _finish(self) -> None:
        if self._finished.is_set():
            return
        self._finished.set()
        self._p.stop()
        if self._done_cb:
            GLib.idle_add(self._done_cb)

    def stop(self) -> None:
        if self._finished.is_set():
            return
        self._finished.set()
        self._p.stop()
