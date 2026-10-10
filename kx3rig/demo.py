"""Synthetic receive audio for demo mode (`kx3-rig --demo`).

Produces 12 kHz audio in real time that resembles what the KX3 PHONES output
carries: receiver noise shaped by the IF filter, plus signals appropriate to the
current mode. In DATA mode on an FT8 dial frequency it transmits real FT8
messages (when the FT8 encoder is available) so the decoder can be exercised
end to end without a radio.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

import numpy as np

from .cat import Mode

RATE = 12_000
CHUNK = 256


class DemoAudio:
    def __init__(self, on_samples: Callable[[np.ndarray, float], None], radio_state: Callable[[], object]):
        self._on_samples = on_samples
        self._radio_state = radio_state
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._rng = np.random.default_rng(7)
        self.listen = True
        self._ft8_slot = None
        self._ft8_audio = np.zeros(0, np.float32)
        self._ft8_messages: list[tuple[str, float, float]] = []
        self._noise_state = np.zeros(2)
        # Bandpass shaping for receiver noise, roughly 250-2900 Hz.
        self._fir = self._design_bandpass(250, 2900)

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="demo-audio", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)

    @staticmethod
    def _design_bandpass(lo: float, hi: float, taps: int = 129) -> np.ndarray:
        n = np.arange(taps) - (taps - 1) / 2
        h = (np.sinc(2 * hi / RATE * n) * 2 * hi / RATE) - (np.sinc(2 * lo / RATE * n) * 2 * lo / RATE)
        return (h * np.hamming(taps)).astype(np.float32)

    def _run(self) -> None:
        t_next = time.monotonic()
        tail = np.zeros(len(self._fir) - 1, np.float32)
        sample_index = 0
        while not self._stop.is_set():
            now = time.monotonic()
            if now < t_next:
                time.sleep(min(0.01, t_next - now))
                continue
            noise = self._rng.normal(0, 0.02, CHUNK).astype(np.float32)
            block = np.concatenate([tail, noise])
            shaped = np.convolve(block, self._fir, mode="valid").astype(np.float32)
            tail = block[-(len(self._fir) - 1):]
            t = (sample_index + np.arange(CHUNK)) / RATE
            signal = self._signals(t, time.time())
            out = shaped * 4.0 + signal
            sample_index += CHUNK
            self._on_samples(out.astype(np.float32), time.time())
            t_next += CHUNK / RATE

    def _signals(self, t: np.ndarray, wall: float) -> np.ndarray:
        state = self._radio_state()
        mode = getattr(state, "mode", None)
        freq = getattr(state, "frequency", 0)
        out = np.zeros_like(t, dtype=np.float32)
        if getattr(state, "ptt", False) or getattr(state, "transmitting", False):
            return out
        if mode is not None and mode.is_data:
            out += self._ft8_like(t, wall)
        elif mode is not None and mode.is_cw:
            # A CW station sending dits at 600 Hz.
            keyed = (np.floor(t * 8) % 3 != 2).astype(np.float32) * (np.floor(t / 4) % 2 == 0)
            out += 0.08 * keyed * np.sin(2 * np.pi * 620 * t)
        elif mode in (Mode.USB, Mode.LSB, Mode.AM):
            # Two voice-like stations: band-limited tones with a syllabic envelope.
            for base, rate, amp in ((900, 3.1, 0.09), (2300, 4.3, 0.04)):
                env = np.clip(np.sin(2 * np.pi * rate * t) * np.sin(2 * np.pi * 0.37 * t), 0, None)
                tone = sum(np.sin(2 * np.pi * (base + k * 140 + 40 * np.sin(2 * np.pi * 1.7 * t)) * t) / (k + 1) for k in range(5))
                out += amp * env * tone
        _ = freq
        return out.astype(np.float32)

    def _ft8_like(self, t: np.ndarray, wall: float) -> np.ndarray:
        slot = int(wall // 15)
        if slot != self._ft8_slot:
            self._ft8_slot = slot
            self._ft8_audio = self._render_slot(slot)
        offset = int(((wall % 15.0) - (t[-1] - t[0])) * RATE)
        offset = max(0, offset)
        seg = self._ft8_audio[offset: offset + len(t)]
        if len(seg) < len(t):
            seg = np.concatenate([seg, np.zeros(len(t) - len(seg), np.float32)])
        return seg

    def _render_slot(self, slot: int) -> np.ndarray:
        """One 15 s FT8 cycle of demo signals."""
        try:
            from . import ft8
        except ImportError:
            return np.zeros(15 * RATE, np.float32)

        rng = np.random.default_rng(slot)
        audio = np.zeros(15 * RATE, np.float32)
        try:
            messages = ft8.demo_messages(slot)
        except AttributeError:
            return audio
        for text, offset_hz, snr_db in messages:
            try:
                wave = ft8.synthesize(text, offset_hz, RATE)
            except Exception:
                continue
            amp = 0.02 * 4.0 * 10 ** (snr_db / 20.0) * 3.0
            start = int((0.5 + rng.uniform(-0.1, 0.3)) * RATE)
            end = min(len(audio), start + len(wave))
            audio[start:end] += amp * wave[: end - start]
        return audio
