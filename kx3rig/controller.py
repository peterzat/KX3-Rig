"""Station controller: the one object the UI talks to.

It owns the radio link (serial worker thread), the receive audio stream, the
waterfall spectrum, and voice/data transmit. Worker-thread callbacks are
marshalled onto the GLib main loop, so every signal here fires on the UI thread.

Transmit policy lives here, not in the widgets: every transmit path calls
can_transmit() first, which checks the link, the license-class band plan, and
that a callsign is set.
"""

from __future__ import annotations

import collections
import logging
import threading
import time

import gi
import numpy as np

gi.require_version("Gst", "1.0")
from gi.repository import GLib, GObject  # noqa: E402

from . import bandplan, config, devices  # noqa: E402
from .bandplan import TxCheck  # noqa: E402
from .cat import DataSubmode, Mode  # noqa: E402
from .radio import Link, RadioLink, RadioState  # noqa: E402
from .spectrum import AutoLevel, Spectrum, rms_dbfs  # noqa: E402

log = logging.getLogger(__name__)

VOICE_TX_LIMIT_S = 120.0
TUNE_LIMIT_S = 10.0


class AudioStatus:
    """Which radio audio paths are available right now."""

    def __init__(self, rx: bool = False, tx: bool = False, error: str = ""):
        self.rx = rx
        self.tx = tx
        self.error = error

    def __eq__(self, other):
        return isinstance(other, AudioStatus) and (self.rx, self.tx, self.error) == (other.rx, other.tx, other.error)


class Station(GObject.Object):
    __gtype_name__ = "KX3Station"

    __gsignals__ = {
        # RadioState (Python object); fires on the main loop whenever it changes.
        "radio-changed": (GObject.SignalFlags.RUN_FIRST, None, (object,)),
        # (kind, message) for toasts: connected, lost, watchdog, error, ...
        "event": (GObject.SignalFlags.RUN_FIRST, None, (str, str)),
        "audio-changed": (GObject.SignalFlags.RUN_FIRST, None, (object,)),
        # Microphone peak level in dBFS while talking (or testing the mic).
        "mic-level": (GObject.SignalFlags.RUN_FIRST, None, (float,)),
        "talking-changed": (GObject.SignalFlags.RUN_FIRST, None, (bool,)),
    }

    def __init__(self, settings: config.Settings, demo: bool = False):
        super().__init__()
        self.settings = settings
        self.demo = demo
        self.radio = RadioState()
        self.audio = AudioStatus()
        self.talking = False
        self.spectrum = Spectrum(fft_size=2048, hop=512)
        self.level = AutoLevel()
        self.rx_level_dbfs = -120.0
        # Waterfall rows (normalized 0..1) produced on the audio thread; each
        # waterfall widget drains its own queue.
        self._row_queues: list[collections.deque] = []
        # Raw 12 kHz audio for the FT8 decoder: list of (end_time, samples) chunks.
        self.sample_listeners: list = []
        self._rx_lock = threading.Lock()
        self._rx = None
        self._voice = None
        self._data_tx = None
        self._data_tx_token = None
        self._data_tx_finish = None   # finish(ok) of the transmission in flight
        self._digirig_audio = None
        self._audio_nodes: list[devices.AudioNode] = []   # latest PipeWire scan
        self._audio_scan_busy = False
        self._audio_timer = 0
        self._demo_source = None
        self._rx_error = ""
        # Set by Smartscan while it sweeps: the dial moves every second, so
        # nothing may key the radio until the sweep stops.
        self.scanning = False
        self._clip = None

        if demo:
            from .fakeradio import FakeKX3

            self._fake = FakeKX3(frequency=14_074_000, mode=Mode.DATA)
            port_factory = lambda path: self._fake  # noqa: E731
            find_port = lambda: "/dev/serial/by-id/usb-Silicon_Labs_CP2102N_demo-if00-port0"  # noqa: E731
            holders = lambda path: []  # noqa: E731
        else:
            from .radio import open_serial

            port_factory = open_serial
            override = settings.serial_port.strip()
            find_port = (lambda: override) if override else devices.find_serial_port
            holders = devices.processes_holding
        self.link = RadioLink(
            on_state=lambda s: GLib.idle_add(self._on_radio_state, s),
            on_event=lambda k, m: GLib.idle_add(self._emit_event, k, m),
            port_factory=port_factory,
            find_port=find_port,
            port_holders=holders,
            max_power_w=settings.max_power_w,
        )

    # --- lifecycle ------------------------------------------------------------------

    def start(self) -> None:
        self.link.start()
        if self.demo:
            from .demo import DemoAudio

            self._demo_source = DemoAudio(self._on_samples, lambda: self.radio)
            loop = self._demo_source.loop
            self._fake.swr_source = lambda: loop.swr(self._fake.frequency)
            self._demo_source.start()
            self._set_audio(AudioStatus(rx=True, tx=True))
        else:
            self._audio_timer = GLib.timeout_add_seconds(2, self._check_audio)
            self._check_audio()

    def shutdown(self) -> None:
        self.stop_clip()
        self.stop_talking()
        self.stop_data_tx()
        if self._audio_timer:
            GLib.source_remove(self._audio_timer)
            self._audio_timer = 0
        if self._demo_source:
            self._demo_source.stop()
        self._stop_rx()
        self.link.stop()
        config.save(self.settings)

    # --- radio state ------------------------------------------------------------------

    def _on_radio_state(self, state: RadioState) -> bool:
        was_tx = self.radio.ptt or self.radio.transmitting
        self.radio = state
        is_tx = state.ptt or state.transmitting
        if is_tx and self._clip is not None:
            self.stop_clip()   # a replayed clip must never reach the microphone on the air
        if was_tx != is_tx:
            self._apply_listen()
        if state.link is not Link.CONNECTED and self.talking:
            self.stop_talking()
        self.emit("radio-changed", state)
        return False

    def _emit_event(self, kind: str, message: str) -> bool:
        if kind == "watchdog":
            self.stop_talking()
        if kind in ("watchdog", "lost"):
            # The link dropped PTT on its own: end the data transmission and
            # tell its owner (FT8 engine) that it did not complete.
            self._abort_data_tx()
        self.emit("event", kind, message)
        return False

    @property
    def connected(self) -> bool:
        return self.radio.link is Link.CONNECTED

    @property
    def transmitting(self) -> bool:
        return bool(self.radio.ptt or self.radio.transmitting or self.talking or self.data_transmitting)

    # Frequency, band, and mode changes are refused while transmitting: the
    # license-class check ran at key-down for the frequency and mode in use then.

    def tune_to(self, hz: int) -> None:
        if self.connected and hz > 0 and not self.transmitting:
            self.link.set_frequency(hz)

    def select_band(self, band: bandplan.Band) -> None:
        if self.connected and not self.transmitting:
            self.link.set_band(band.number)

    def select_mode(self, mode: Mode) -> None:
        if not self.connected or self.transmitting:
            return
        if mode.is_data:
            self.link.set_mode(mode, DataSubmode.DATA_A)
        else:
            self.link.set_mode(mode)

    def set_power(self, watts: float) -> None:
        self.settings.power_w = watts
        self.link.set_power(watts)

    def go_ft8(self, band: bandplan.Band) -> None:
        """Put the radio on the FT8 dial frequency for a band, DATA A mode."""
        if not self.connected or self.transmitting:
            return
        self.link.set_frequency(band.ft8)
        self.link.set_mode(Mode.DATA, DataSubmode.DATA_A)

    # --- transmit policy -----------------------------------------------------------------

    def can_transmit(self, mode: Mode | None = None, audio_low: int | None = None,
                     audio_high: int | None = None) -> TxCheck:
        if not self.connected:
            return TxCheck(False, "The radio isn't connected.")
        if self.scanning:
            return TxCheck(False, "Smartscan is sweeping the band. Stop it to transmit.")
        if not self.settings.callsign:
            return TxCheck(False, "Add your callsign in Preferences to transmit.")
        if not self.audio.tx:
            return TxCheck(False, "The Digirig audio output isn't available.")
        mode = mode or self.radio.mode
        if mode is None or self.radio.frequency <= 0:
            return TxCheck(False, "Waiting for the radio.")
        power = self.radio.power_set
        if power is None:
            return TxCheck(False, "Waiting for the radio's power setting.")
        if power > self.settings.max_power_w + 0.05:
            return TxCheck(False, f"The KX3 is set to {power:g} W, above your {self.settings.max_power_w:g} W "
                                  "limit. Lower it with the Power control first.")
        if self.radio.split or self.radio.xit_on:
            # The license check only sees VFO A; SPLIT or XIT would transmit elsewhere.
            return TxCheck(False, "Turn off SPLIT and XIT on the KX3 to transmit.")
        return bandplan.tx_check(self.radio.frequency, mode, self.settings.license_class, audio_low, audio_high)

    def voice_check(self) -> TxCheck:
        mode = self.radio.mode
        if mode is not None and mode.is_cw:
            return TxCheck(False, "For CW, use a key on the KX3's KEY jack.")
        if mode is not None and mode.is_data:
            return TxCheck(False, "This is a data mode. Use the FT8 view to transmit.")
        return self.can_transmit()

    # --- voice transmit -------------------------------------------------------------------

    def start_talking(self) -> TxCheck:
        check = self.voice_check()
        if not check.allowed or self.talking:
            return check
        self.stop_clip()   # the mic would pick up the speakers and send the clip on the air
        from .audio import VoiceTransmit, default_node_name

        try:
            if not self.demo:
                # Never loop the radio's own audio back into its microphone, and
                # never leave the mic untargeted (pipewiresrc would then follow
                # the default source, which may be the Digirig).
                mic = default_node_name("source")
                if not mic or devices.DIGIRIG_NODE_RE.search(mic):
                    mic = devices.pick_mic(mic, self._audio_nodes)
                if mic is None:
                    return TxCheck(False, "No microphone found other than the Digirig. Connect a microphone to talk.")
                self._voice = VoiceTransmit(
                    mic_node=mic,
                    digirig_sink_node=self._digirig_audio.sink.name,
                    gain=self.settings.voice_gain,
                    on_level=lambda db: self.emit("mic-level", db),
                    on_error=lambda msg: self._emit_event("error", f"Microphone: {msg}"),
                )
                self._voice.start()
        except Exception as exc:
            self._voice = None
            return TxCheck(False, f"Could not open the microphone: {exc}")
        if not self.link.ptt(True, limit_s=VOICE_TX_LIMIT_S, expect_frequency=self.radio.frequency,
                             expect_mode=self.radio.mode):
            self._stop_voice_stream()
            if self.link.tuning_pending:
                return TxCheck(False, "Still tuning. Try again in a moment.")
            return TxCheck(False, "The radio did not accept push-to-talk.")
        self.talking = True
        self.emit("talking-changed", True)
        return check

    def stop_talking(self) -> None:
        if not self.talking and self._voice is None:
            return
        self.link.ptt(False)
        self._stop_voice_stream()
        if self.talking:
            self.talking = False
            self.emit("talking-changed", False)

    def _stop_voice_stream(self) -> None:
        voice, self._voice = self._voice, None
        if voice is not None:
            voice.stop()

    def set_voice_gain(self, gain: float) -> None:
        self.settings.voice_gain = gain
        if self._voice is not None:
            self._voice.set_gain(gain)

    # --- data transmit (FT8, tune) ------------------------------------------------------------

    def play_data(self, samples: np.ndarray, rate: int, on_done=None, limit_s: float = 16.0) -> TxCheck:
        """Key the radio and play generated audio. Caller has already run can_transmit().

        on_done(ok) runs once on the main loop: ok is True when the audio played
        to the end, False when it failed or was stopped. The radio is unkeyed
        before on_done runs, and a stale completion (from a transmission that
        was already stopped) never unkeys a newer one.
        """
        from .audio import DataTransmit

        if self._data_tx is not None:
            return TxCheck(False, "Already transmitting.")
        token = object()

        def finish(ok: bool) -> bool:
            if self._data_tx_token is not token:
                return False   # stopped already, or superseded
            self._data_tx_token = None
            self._data_tx_finish = None
            self._data_tx = None
            self.link.ptt(False)
            if on_done:
                on_done(ok)
            return False

        def failed(msg: str) -> None:
            tx = self._data_tx
            finish(False)
            if tx is not None and hasattr(tx, "stop"):
                tx.stop()
            self._emit_event("error", f"Transmit audio failed: {msg}")

        if self.link.tuning_pending:
            return TxCheck(False, "Still tuning. Try again in a moment.", retry=True)
        self.stop_clip()
        if not self.link.ptt(True, limit_s=limit_s, expect_frequency=self.radio.frequency,
                             expect_mode=self.radio.mode):
            return TxCheck(False, "The radio did not accept push-to-talk.", retry=True)
        self._data_tx_token = token
        self._data_tx_finish = finish
        if self.demo:
            self._data_tx = object()
            GLib.timeout_add(int(len(samples) / rate * 1000), finish, True)
            return TxCheck(True)
        try:
            self._data_tx = DataTransmit(
                samples, rate, self._digirig_audio.sink.name, self.settings.data_tx_level,
                on_done=lambda: finish(True),
                on_error=failed,
            )
            self._data_tx.start()
        except Exception as exc:
            self._data_tx = None
            self._data_tx_token = None
            self._data_tx_finish = None
            self.link.ptt(False)
            return TxCheck(False, f"Could not play transmit audio: {exc}")
        return TxCheck(True)

    def stop_data_tx(self) -> None:
        tx, self._data_tx = self._data_tx, None
        self._data_tx_token = None   # any pending completion is now stale
        self._data_tx_finish = None
        if tx is not None and hasattr(tx, "stop"):
            tx.stop()
        if tx is not None:
            self.link.ptt(False)

    def _abort_data_tx(self) -> None:
        """End the data transmission in flight and run its on_done(False) once."""
        tx, finish = self._data_tx, self._data_tx_finish
        if finish is None:
            return
        finish(False)
        if tx is not None and hasattr(tx, "stop"):
            tx.stop()

    @property
    def data_transmitting(self) -> bool:
        return self._data_tx is not None

    def halt_all(self) -> None:
        """Escape / Halt: stop every kind of transmission now."""
        self.stop_talking()
        self.stop_data_tx()
        self.link.ptt(False)

    # --- audio -------------------------------------------------------------------------------

    def _set_audio(self, status: AudioStatus) -> None:
        if status != self.audio:
            self.audio = status
            self.emit("audio-changed", status)

    def _check_audio(self) -> bool:
        """Every 2 s: rescan PipeWire in a separate process (never blocks the window)."""
        if not self._audio_scan_busy:
            self._audio_scan_busy = True
            try:
                devices.scan_audio_nodes(self._on_audio_nodes)
            except Exception:
                log.exception("audio device scan failed to start")
                self._audio_scan_busy = False   # retry on the next tick
        return True

    def _on_audio_nodes(self, nodes: list[devices.AudioNode] | None) -> bool:
        """Start or stop receive audio as the Digirig comes and goes."""
        self._audio_scan_busy = False
        if nodes is None or not self._audio_timer:   # scan failed (keep the current state), or shut down
            return False
        self._audio_nodes = nodes
        found = devices.pick_digirig_audio(nodes)
        self._digirig_audio = found
        if found.source and self._rx is None:
            self._start_rx(found)
        elif not found.source and self._rx is not None:
            self._stop_rx()
        if not found.source:
            self._rx_error = ""
        self._set_audio(AudioStatus(rx=self._rx is not None, tx=found.sink is not None,
                                    error=self._rx_error if self._rx is None else ""))
        return False

    def _listen_sink(self) -> str | None:
        from .audio import default_node_name

        name = default_node_name("sink")
        if name and devices.DIGIRIG_NODE_RE.search(name):
            # The default output is the Digirig: playing radio audio there would
            # transmit it. Pick any other output instead, or none.
            others = [n for n in self._audio_nodes if n.is_sink and not n.is_digirig]
            return others[0].name if others else None
        return name

    def _start_rx(self, found: devices.DigirigAudio) -> None:
        from .audio import ReceiveAudio

        try:
            rx = ReceiveAudio(
                source_node=found.source.name,
                listen_sink_node=self._listen_sink(),
                on_samples=self._on_samples,
                on_error=lambda msg: GLib.idle_add(self._on_rx_error, msg),
                volume=self.settings.listen_volume,
            )
            rx.start()
        except Exception as exc:
            log.warning("receive audio failed to start: %s", exc)
            self._rx_error = f"Receive audio failed: {exc}"
            return
        self._rx = rx
        self._rx_error = ""
        self._apply_listen()

    def _on_rx_error(self, msg: str) -> bool:
        log.warning("receive audio error: %s", msg)
        self._stop_rx()
        self._rx_error = f"Receive audio stopped: {msg}"
        self._set_audio(AudioStatus(rx=False, tx=self.audio.tx, error=self._rx_error))
        return False

    def _stop_rx(self) -> None:
        rx, self._rx = self._rx, None
        if rx is not None:
            rx.stop()

    def _apply_listen(self) -> None:
        if self._rx is None:
            return
        transmitting = self.radio.ptt or self.radio.transmitting
        # Mute the speakers while transmitting: the KX3 sends its TX monitor to
        # PHONES, and a laptop mic would pick the speakers up (feedback).
        self._rx.set_muted(not self.settings.listen or transmitting or self._clip is not None)
        self._rx.set_volume(self.settings.listen_volume)

    def set_listen(self, on: bool) -> None:
        self.settings.listen = on
        self._apply_listen()
        if self._demo_source:
            self._demo_source.listen = on

    def set_listen_volume(self, volume: float) -> None:
        self.settings.listen_volume = volume
        self._apply_listen()

    # --- replaying a recorded clip -----------------------------------------------------------

    def play_clip(self, samples: np.ndarray, rate: int, on_done=None) -> str:
        """Play recorded receive audio on this computer's speakers.

        Returns "" when playback started, or why it could not. The clip goes to
        the same output as listening, never the Digirig (that would transmit
        it), and live radio audio is muted until it ends.
        """
        from .audio import ClipPlayer

        self.stop_clip()
        if self.transmitting:
            return "Stop transmitting to replay a recording."
        sink = None
        if self.demo:
            import sys

            # macOS has no PipeWire; its audio has no Digirig to avoid.
            sink = "auto" if sys.platform == "darwin" else self._listen_sink()
        else:
            sink = self._listen_sink()
        if sink is None:
            return "No speaker or headset found to play the clip on."
        token = object()

        def done() -> bool:
            if self._clip is not None and self._clip[0] is token:
                self._clip = None
                self._apply_listen()
                if on_done:
                    on_done()
            return False

        def failed() -> bool:
            if self._clip is not None and self._clip[0] is token:
                self._clip[1].stop()
            return done()

        player = None
        try:
            player = ClipPlayer(samples, rate, sink, self.settings.listen_volume, on_done=done,
                                on_error=lambda msg: GLib.idle_add(failed))
            self._clip = (token, player)
            self._apply_listen()
            player.start()
        except Exception as exc:
            self._clip = None
            if player is not None:
                player.stop()
            self._apply_listen()
            return f"Could not play the clip: {exc}"
        return ""

    def stop_clip(self) -> None:
        clip, self._clip = self._clip, None
        if clip is not None:
            clip[1].stop()
            self._apply_listen()

    @property
    def clip_playing(self) -> bool:
        return self._clip is not None

    def _on_samples(self, samples: np.ndarray, end_time: float) -> None:
        """Audio thread: feed the waterfall and any sample listeners (FT8)."""
        self.rx_level_dbfs = rms_dbfs(samples)
        for row in self.spectrum.feed(samples):
            band = row[self.spectrum.bins_for(0, 3500)]
            normalized = self.level.normalize(band).astype(np.float32)
            for q in self._row_queues:
                q.append(normalized)
        for listener in list(self.sample_listeners):
            try:
                listener(samples, end_time)
            except Exception:
                log.exception("sample listener failed")

    def subscribe_rows(self) -> collections.deque:
        q: collections.deque = collections.deque(maxlen=256)
        self._row_queues.append(q)
        return q

    @property
    def waterfall_span_hz(self) -> float:
        s = self.spectrum.bins_for(0, 3500)
        return (s.stop - 1) * self.spectrum.bin_hz


def now_utc() -> float:
    return time.time()
