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
        # Waterfall rows (normalized 0..1) produced on the audio thread, drained by the widget.
        self.rows: collections.deque[np.ndarray] = collections.deque(maxlen=256)
        # Raw 12 kHz audio for the FT8 decoder: list of (end_time, samples) chunks.
        self.sample_listeners: list = []
        self._rx_lock = threading.Lock()
        self._rx = None
        self._voice = None
        self._data_tx = None
        self._digirig_audio = None
        self._audio_timer = 0
        self._demo_source = None

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
            self._demo_source.start()
            self._set_audio(AudioStatus(rx=True, tx=True))
        else:
            self._check_audio()
            self._audio_timer = GLib.timeout_add_seconds(2, self._check_audio)

    def shutdown(self) -> None:
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
        if was_tx != is_tx:
            self._apply_listen()
        if state.link is not Link.CONNECTED and self.talking:
            self.stop_talking()
        self.emit("radio-changed", state)
        return False

    def _emit_event(self, kind: str, message: str) -> bool:
        if kind == "watchdog":
            self.stop_talking()
            self.stop_data_tx()
        self.emit("event", kind, message)
        return False

    @property
    def connected(self) -> bool:
        return self.radio.link is Link.CONNECTED

    def tune_to(self, hz: int) -> None:
        if self.connected and hz > 0:
            self.link.set_frequency(hz)

    def select_band(self, band: bandplan.Band) -> None:
        if self.connected:
            self.link.set_band(band.number)

    def select_mode(self, mode: Mode) -> None:
        if not self.connected:
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
        if not self.connected:
            return
        self.link.set_frequency(band.ft8)
        self.link.set_mode(Mode.DATA, DataSubmode.DATA_A)

    # --- transmit policy -----------------------------------------------------------------

    def can_transmit(self, mode: Mode | None = None, audio_low: int | None = None,
                     audio_high: int | None = None) -> TxCheck:
        if not self.connected:
            return TxCheck(False, "The radio isn't connected.")
        if not self.settings.callsign:
            return TxCheck(False, "Add your callsign in Preferences to transmit.")
        if not self.audio.tx:
            return TxCheck(False, "The Digirig audio output isn't available.")
        mode = mode or self.radio.mode
        if mode is None or self.radio.frequency <= 0:
            return TxCheck(False, "Waiting for the radio.")
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
        from .audio import VoiceTransmit, default_node_name

        mic = default_node_name("source")
        if self._digirig_audio and self._digirig_audio.source and mic == self._digirig_audio.source.name:
            mic = None  # never loop the radio's own audio back into its microphone
        try:
            if not self.demo:
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
        if not self.link.ptt(True, limit_s=VOICE_TX_LIMIT_S):
            self._stop_voice_stream()
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
        """Key the radio and play generated audio. Caller has already run can_transmit()."""
        from .audio import DataTransmit

        if self._data_tx is not None:
            return TxCheck(False, "Already transmitting.")

        def finished():
            self._data_tx = None
            self.link.ptt(False)
            if on_done:
                on_done()
            return False

        if not self.link.ptt(True, limit_s=limit_s):
            return TxCheck(False, "The radio did not accept push-to-talk.")
        if self.demo:
            self._data_tx = object()
            GLib.timeout_add(int(len(samples) / rate * 1000), finished)
            return TxCheck(True)
        try:
            self._data_tx = DataTransmit(
                samples, rate, self._digirig_audio.sink.name, self.settings.data_tx_level,
                on_done=finished,
                on_error=lambda msg: self._emit_event("error", f"Transmit audio: {msg}"),
            )
            self._data_tx.start()
        except Exception as exc:
            self._data_tx = None
            self.link.ptt(False)
            return TxCheck(False, f"Could not play transmit audio: {exc}")
        return TxCheck(True)

    def stop_data_tx(self) -> None:
        tx, self._data_tx = self._data_tx, None
        if tx is not None and hasattr(tx, "stop"):
            tx.stop()
        if tx is not None:
            self.link.ptt(False)

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
        try:
            found = devices.find_digirig_audio()
        except Exception as exc:
            log.warning("audio device scan failed: %s", exc)
            return True
        self._digirig_audio = found
        if found.source and self._rx is None:
            self._start_rx(found)
        elif not found.source and self._rx is not None:
            self._stop_rx()
        error = self.audio.error if self._rx is not None or not found.source else ""
        self._set_audio(AudioStatus(rx=self._rx is not None, tx=found.sink is not None, error=error))
        return True

    def _listen_sink(self) -> str | None:
        from .audio import default_node_name

        name = default_node_name("sink")
        if name and devices.DIGIRIG_NODE_RE.search(name):
            # The default output is the Digirig: playing radio audio there would
            # transmit it. Pick any other output instead, or none.
            others = [n for n in devices.list_audio_nodes() if n.is_sink and not n.is_digirig]
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
            self._set_audio(AudioStatus(rx=False, tx=found.sink is not None, error=str(exc)))
            return
        self._rx = rx
        self._apply_listen()

    def _on_rx_error(self, msg: str) -> bool:
        log.warning("receive audio error: %s", msg)
        self._stop_rx()
        self._set_audio(AudioStatus(rx=False, tx=self.audio.tx, error=msg))
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
        self._rx.set_muted(not self.settings.listen or transmitting)
        self._rx.set_volume(self.settings.listen_volume)

    def set_listen(self, on: bool) -> None:
        self.settings.listen = on
        self._apply_listen()
        if self._demo_source:
            self._demo_source.listen = on

    def set_listen_volume(self, volume: float) -> None:
        self.settings.listen_volume = volume
        self._apply_listen()

    def _on_samples(self, samples: np.ndarray, end_time: float) -> None:
        """Audio thread: feed the waterfall and any sample listeners (FT8)."""
        self.rx_level_dbfs = rms_dbfs(samples)
        for row in self.spectrum.feed(samples):
            band = row[self.spectrum.bins_for(0, 3500)]
            self.rows.append(self.level.normalize(band).astype(np.float32))
        for listener in list(self.sample_listeners):
            try:
                listener(samples, end_time)
            except Exception:
                log.exception("sample listener failed")

    @property
    def waterfall_span_hz(self) -> float:
        s = self.spectrum.bins_for(0, 3500)
        return (s.stop - 1) * self.spectrum.bin_hz


def now_utc() -> float:
    return time.time()
