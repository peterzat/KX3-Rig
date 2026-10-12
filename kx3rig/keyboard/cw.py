"""Software CW: Morse timing, keyed-tone transmit audio, and a receive decoder.

Transmit is an audio tone keyed on and off, which the KX3 sends in DATA A
(upper sideband), so the RF carrier sits at dial + f0. Receive decodes the
12 kHz PHONES audio that Station.sample_listeners delivers.

Sources:
- ITU-R M.1677-1 (10/2009), "International Morse code": the characters
  (section 1.1) and the timing (section 2: a dash is three dots, one dot
  between the signals of a letter, three between letters, seven between
  words). Read this session from the ITU PDF.
- PARIS timing: one dot lasts 1.2 / WPM seconds (the 50-unit word PARIS sent
  WPM times a minute).
- fldigi src/cw_rtty/cw.cxx (w1hkj/fldigi on GitHub, read this session) for
  the receive design adapted here: an envelope detector with a tracked peak
  and noise floor and a hysteresis threshold between them (cw::rx_FIRprocess),
  a spike filter of a quarter of two dots, and speed tracking that only learns
  from adjacent dot-dash or dash-dot pairs whose ratio is between 2 and 4,
  setting the dot/dash boundary to their mean (cw::handle_event,
  cw::update_tracking). Silence of 2 to 4 dots ends a character.
- fldigi shapes transmit edges with half a raised cosine, 4 ms by default
  (cw::create_edges, CWrisetime in configuration.h). A hard-keyed tone has
  sidebands far from the carrier (key clicks); a few milliseconds of shaped
  edge keeps the signal narrow. 5 ms is used here.

Prosigns share codes with punctuation in M.1677-1: AR is the cross (+), BT
the double hyphen (=), and KN the open bracket ((). On the air the prosign is
the usual meaning, so the decoder prints <AR>, <BT>, and <KN> for those codes.
"""

from __future__ import annotations

import math
import re

import numpy as np

# ITU-R M.1677-1 section 1.1; prosigns as commonly sent (fldigi morse.cxx agrees).
MORSE: dict[str, str] = {
    "A": ".-", "B": "-...", "C": "-.-.", "D": "-..", "E": ".", "F": "..-.", "G": "--.",
    "H": "....", "I": "..", "J": ".---", "K": "-.-", "L": ".-..", "M": "--", "N": "-.",
    "O": "---", "P": ".--.", "Q": "--.-", "R": ".-.", "S": "...", "T": "-", "U": "..-",
    "V": "...-", "W": ".--", "X": "-..-", "Y": "-.--", "Z": "--..",
    "0": "-----", "1": ".----", "2": "..---", "3": "...--", "4": "....-",
    "5": ".....", "6": "-....", "7": "--...", "8": "---..", "9": "----.",
    ".": ".-.-.-", ",": "--..--", "?": "..--..", "/": "-..-.", "=": "-...-", "+": ".-.-.",
    "-": "-....-", ":": "---...", "'": ".----.", '"': ".-..-.", "@": ".--.-.",
    "(": "-.--.", ")": "-.--.-",
    "<AR>": ".-.-.", "<SK>": "...-.-", "<BT>": "-...-", "<KN>": "-.--.", "<BK>": "-...-.-",
}

# Decoding: prosigns win where they share a code with punctuation.
_DECODE: dict[str, str] = {}
for _ch, _code in MORSE.items():
    if _code not in _DECODE or _ch.startswith("<"):
        _DECODE[_code] = _ch

_TOKEN = re.compile(r"<[A-Z]{2,3}>|\s+|.", re.S)


def tokens(text: str) -> list[str]:
    """Sendable characters and prosigns, with single spaces between words."""
    out: list[str] = []
    for tok in _TOKEN.findall(text.upper()):
        if tok.isspace():
            if out and out[-1] != " ":
                out.append(" ")
        elif tok in MORSE:
            out.append(tok)
    while out and out[-1] == " ":
        out.pop()
    return out


def normalize(text: str) -> str:
    """Uppercase, drop what Morse cannot send, collapse spaces."""
    return "".join(tokens(text))


def dot_s(wpm: float) -> float:
    return 1.2 / wpm


def _space_unit(wpm: float, farnsworth_wpm: float | None) -> float:
    """Length of one spacing unit between characters and words.

    Farnsworth spacing sends characters at wpm and stretches only the gaps so
    PARIS (31 units inside its characters, 19 of spacing) takes 60/farnsworth s.
    """
    dot = dot_s(wpm)
    if not farnsworth_wpm or farnsworth_wpm >= wpm:
        return dot
    return max(dot, (60.0 / farnsworth_wpm - 31 * dot) / 19)


def timing(text: str, wpm: float, farnsworth_wpm: float | None = None) -> list[tuple[bool, float]]:
    """(key_down, seconds) runs for the text, starting and ending key-down."""
    dot = dot_s(wpm)
    gap = _space_unit(wpm, farnsworth_wpm)
    runs: list[tuple[bool, float]] = []
    pending = 0.0      # silence owed before the next element
    for tok in tokens(text):
        if tok == " ":
            pending = 7 * gap
            continue
        for i, el in enumerate(MORSE[tok]):
            if runs:
                runs.append((False, pending if i == 0 else dot))
            runs.append((True, dot if el == "." else 3 * dot))
        pending = 3 * gap
    return runs


def duration_s(text: str, wpm: float, farnsworth_wpm: float | None = None) -> float:
    return sum(s for _, s in timing(text, wpm, farnsworth_wpm)) + 2 * LEAD_S


LEAD_S = 0.05


def char_times(text: str, wpm: float, farnsworth_wpm: float | None = None) -> list[tuple[str, float]]:
    """(token, start in seconds) for each character in modulate()'s audio, for send progress."""
    dot = dot_s(wpm)
    gap = _space_unit(wpm, farnsworth_wpm)
    t = LEAD_S
    out: list[tuple[str, float]] = []
    started = False
    pending = 0.0
    for tok in tokens(text):
        if tok == " ":
            out.append((" ", t))
            pending = 7 * gap
            continue
        if started:
            t += pending
        out.append((tok, t))
        started = True
        code = MORSE[tok]
        t += sum(dot if el == "." else 3 * dot for el in code) + dot * (len(code) - 1)
        pending = 3 * gap
    return out


def modulate(text: str, wpm: float = 18, rate: int = 48_000, f0: float = 700.0, rise_ms: float = 5.0,
             farnsworth_wpm: float | None = None) -> np.ndarray:
    """Unit-amplitude keyed tone with raised-cosine edges and 50 ms of silence at each end."""
    runs = timing(text, wpm, farnsworth_wpm)
    lead = int(round(LEAD_S * rate))
    env_parts = [np.zeros(lead)]
    for down, seconds in runs:
        n = int(round(seconds * rate))
        if not down:
            env_parts.append(np.zeros(n))
            continue
        e = np.ones(n)
        k = min(int(round(rise_ms / 1000 * rate)), n // 2)
        if k > 0:
            ramp = 0.5 * (1 - np.cos(np.pi * np.arange(k) / k))
            e[:k] = ramp
            e[n - k:] = ramp[::-1]
        env_parts.append(e)
    env_parts.append(np.zeros(lead))
    env = np.concatenate(env_parts)
    t = np.arange(len(env)) / rate
    return (env * np.sin(2 * np.pi * f0 * t)).astype(np.float32)


# --- receive ---------------------------------------------------------------------------

BLOCK_S = 0.005          # envelope step
HISTORY_S = 3.0          # level statistics window
MIN_HISTORY_S = 1.0      # before this, the squelch stays closed
SQUELCH_RATIO = 6.0      # signal (95th percentile) over noise (20th): noise alone is about 3.7
SQUELCH_CLOSE = 4.5      # hysteresis: stays open down to this ratio
SPIKE_MAX_S = 0.02       # spike filter ceiling, so a jump to fast CW is not filtered out
REPLAY_S = 2.5           # when the squelch opens, decode this much buffered envelope
MIN_WPM, MAX_WPM = 8.0, 45.0


class Decoder:
    """Decode CW on one audio tone. feed() returns new text; spaces mark word gaps."""

    def __init__(self, rate: int = 12_000, freq: float = 700.0, wpm: float = 20.0):
        self.rate = rate
        self._freq = float(freq)
        self._block = max(1, int(round(BLOCK_S * rate)))
        self._n = 0                       # samples consumed (for the mixer phase)
        self._pending = np.zeros(0, np.complex128)   # baseband not yet a whole block
        self._tail = np.zeros(0, np.complex128)      # baseband kept for the moving average
        self._hist: list[float] = []
        self._blk = 0                     # envelope blocks seen
        self._done = 0                    # blocks the timing state machine has consumed
        self._hist_max = int(HISTORY_S / BLOCK_S)
        self._noise = 0.0
        self._peak = 0.0
        self._open = False
        self._blocks_since_stats = 0
        self._two_dots = 2 * dot_s(wpm)
        self._reset_state()

    # --- public ---------------------------------------------------------------------

    @property
    def freq(self) -> float:
        return self._freq

    def set_freq(self, hz: float) -> None:
        self._freq = float(hz)
        self._tail = np.zeros(0, np.complex128)
        self._pending = np.zeros(0, np.complex128)
        self._hist.clear()
        self._open = False
        self._reset_state()

    @property
    def wpm(self) -> float:
        return 1.2 / (self._two_dots / 2)

    @property
    def level(self) -> float:
        """0..1: how far the signal stands above the noise (0 below 10 dB, 1 at 30 dB)."""
        if self._noise <= 0 or self._peak <= 0:
            return 0.0
        db = 20 * math.log10(self._peak / self._noise)
        return min(1.0, max(0.0, (db - 10) / 20))

    @property
    def active(self) -> bool:
        return self._open and self._in_tone

    def feed(self, samples: np.ndarray) -> str:
        x = np.asarray(samples, dtype=np.float64)
        if x.size == 0:
            return ""
        n = np.arange(self._n, self._n + x.size)
        self._n += x.size
        # Phase from the absolute sample index, so chunking never changes the result.
        phase = 2 * np.pi * ((self._freq * n) % self.rate) / self.rate
        bb = np.concatenate([self._pending, x * np.exp(-1j * phase)])
        whole = (bb.size // self._block) * self._block
        self._pending = bb[whole:]
        if whole == 0:
            return ""
        return self._blocks(bb[:whole])

    # --- envelope ---------------------------------------------------------------------

    def _window(self) -> int:
        """Moving-average length: a quarter dot, held to a 60-150 Hz bandwidth."""
        seconds = min(1 / 60, max(1 / 150, self._two_dots / 8))
        return max(self._block, int(round(seconds * self.rate)))

    def _blocks(self, bb: np.ndarray) -> str:
        out = []
        nblocks = bb.size // self._block
        for b in range(nblocks):
            chunk = bb[b * self._block:(b + 1) * self._block]
            L = self._window()
            self._tail = np.concatenate([self._tail, chunk])[-max(L, 200):]
            env = float(abs(self._tail[-L:].mean())) if self._tail.size >= L else 0.0
            out.append(self._envelope(env))
        return "".join(out)

    def _envelope(self, env: float) -> str:
        self._hist.append(env)
        self._blk += 1
        if len(self._hist) > self._hist_max:
            del self._hist[0]
        self._blocks_since_stats += 1
        if self._blocks_since_stats >= 10 or len(self._hist) < 50:
            self._blocks_since_stats = 0
            h = np.asarray(self._hist)
            self._noise = float(np.percentile(h, 20))
            self._peak = float(np.percentile(h, 95))
        enough = len(self._hist) * BLOCK_S >= MIN_HISTORY_S
        ratio = SQUELCH_CLOSE if self._open else SQUELCH_RATIO
        now_open = enough and self._noise > 0 and self._peak > ratio * self._noise
        if now_open and not self._open:
            self._open = True
            # Decode what was buffered before the squelch opened (never twice), with the new thresholds.
            self._reset_state()
            fresh = min(self._blk - self._done, len(self._hist), int(REPLAY_S / BLOCK_S))
            self._done = self._blk
            return "".join(self._step(v) for v in self._hist[len(self._hist) - fresh:])
        if not now_open and self._open:
            self._open = False
            text = self.flush()
            self._reset_state()
            return text
        if not self._open:
            return ""
        self._done = self._blk
        return self._step(env)

    # --- timing ---------------------------------------------------------------------------

    def _reset_state(self) -> None:
        self._t = 0.0                 # state-machine time, s
        self._in_tone = False
        self._mark_start = 0.0
        self._mark_end: float | None = None   # end of a mark not yet committed (spike filter)
        self._last_mark = 0.0         # previous committed mark length, for speed tracking
        self._elements = ""
        self._char_end: float | None = None   # when the last element ended
        self._word_pending = False

    def _step(self, env: float) -> str:
        self._t += BLOCK_S
        span = self._peak - self._noise
        upper = self._noise + 0.55 * span
        lower = self._noise + 0.40 * span
        out = ""
        if not self._in_tone and env > upper:
            if self._mark_end is not None and self._t - self._mark_end < self._spike():
                self._mark_end = None      # a brief dropout inside one mark
            else:
                out += self._commit()
                self._mark_start = self._t
            self._char_end = None          # the silence being timed is over
            self._in_tone = True
        elif self._in_tone and env < lower:
            self._in_tone = False
            self._mark_end = self._t
        if not self._in_tone:
            out += self._silence()
        return out

    def _spike(self) -> float:
        return min(self._two_dots / 4, SPIKE_MAX_S)

    def _commit(self) -> str:
        """Classify the pending mark once the silence after it is longer than a spike."""
        if self._mark_end is None:
            return ""
        length = self._mark_end - self._mark_start
        end = self._mark_end
        self._mark_end = None
        if length < self._spike():
            return ""
        last = self._last_mark
        if last > 0:
            short, long_ = (last, length) if length > last else (length, last)
            if 2 * short < long_ < 4 * short:
                self._track(short, long_)
        self._last_mark = length
        self._elements += "." if length <= self._two_dots else "-"
        self._char_end = end
        if len(self._elements) > 8:
            self._elements = ""        # too long for any character: noise
        return ""

    def _track(self, short: float, long_: float) -> None:
        two = (short + long_) / 2
        lo, hi = 2 * dot_s(MAX_WPM), 2 * dot_s(MIN_WPM)
        if lo <= two <= hi:
            self._two_dots += 0.35 * (two - self._two_dots)

    def _silence(self) -> str:
        out = ""
        if self._mark_end is not None and self._t - self._mark_end >= self._spike():
            out += self._commit()
        if self._char_end is None:
            return out
        quiet = self._t - self._char_end
        dot = self._two_dots / 2
        if self._elements and quiet >= 2 * dot:
            out += _DECODE.get(self._elements, "")
            self._elements = ""
            self._word_pending = True
        if self._word_pending and quiet >= 5 * dot:
            out += " "
            self._word_pending = False
        return out

    def flush(self) -> str:
        """Print a character still being received (for example when the operator retunes)."""
        out = ""
        if self._mark_end is not None:
            out += self._commit()
        if self._elements:
            out += _DECODE.get(self._elements, "")
            self._elements = ""
        return out


def strongest_tone(samples: np.ndarray, rate: int = 12_000, lo: float = 300, hi: float = 1200) -> float | None:
    """Frequency of the strongest steady tone between lo and hi Hz, or None.

    Averages power spectra of 0.34 s segments (about 3 Hz bins), then refines
    the peak by parabolic interpolation. None when nothing stands 10 dB above
    the median of the range.
    """
    x = np.asarray(samples, dtype=np.float64)
    n = 4096 if rate >= 12_000 else 2048
    if x.size < n:
        return None
    win = np.hanning(n)
    segs = [x[i:i + n] * win for i in range(0, x.size - n + 1, n // 2)]
    power = np.mean([np.abs(np.fft.rfft(s)) ** 2 for s in segs], axis=0)
    freqs = np.fft.rfftfreq(n, 1 / rate)
    band = (freqs >= lo) & (freqs <= hi)
    idx = np.flatnonzero(band)
    if idx.size < 3:
        return None
    k = idx[int(np.argmax(power[idx]))]
    if power[k] < 10 * np.median(power[idx]):
        return None
    if 0 < k < len(power) - 1:
        a, b, c = np.log(power[k - 1:k + 2] + 1e-30)
        denom = a - 2 * b + c
        delta = 0.5 * (a - c) / denom if denom != 0 else 0.0
    else:
        delta = 0.0
    return float((k + delta) * rate / n)


def demo_signal(items, seconds: float, rate: int = 12_000, snr_db: float = 10.0, seed: int = 0) -> np.ndarray:
    """Looping CW stations plus white noise, for demo mode and tests.

    items: (text, wpm, offset_hz). Each station repeats its text with a pause,
    with about 5% random variation on every element and gap (hand keying).
    snr_db is each station's power over the noise in a 3 kHz bandwidth.
    """
    rng = np.random.default_rng(seed)
    total = int(seconds * rate)
    out = np.zeros(total)
    for idx, (text, wpm, offset) in enumerate(items):
        env = np.zeros(total)
        t = int(rate * rng.uniform(0.3, 1.5))
        rise = int(0.005 * rate)
        while t < total:
            for down, s in timing(text, wpm):
                n = max(1, int(round(s * (1 + rng.normal(0, 0.05)) * rate)))
                if down:
                    e = np.ones(n)
                    k = min(rise, n // 2)
                    if k:
                        ramp = 0.5 * (1 - np.cos(np.pi * np.arange(k) / k))
                        e[:k], e[n - k:] = ramp, ramp[::-1]
                    end = min(total, t + n)
                    env[t:end] = e[:end - t]
                t += n
                if t >= total:
                    break
            t += int(rate * rng.uniform(1.5, 3.0))
        phase = rng.uniform(0, 2 * np.pi)
        out += np.sqrt(2) * env * np.sin(2 * np.pi * offset * np.arange(total) / rate + phase)
    # Station power is 1 (a sine of amplitude sqrt(2)); noise power in 3 kHz is 10^(-snr/10).
    noise_power_3k = 10 ** (-snr_db / 10)
    sigma = math.sqrt(noise_power_3k * (rate / 2) / 3000)
    out += rng.normal(0, sigma, total)
    peak = np.max(np.abs(out)) or 1.0
    return (0.5 * out / peak).astype(np.float32)
