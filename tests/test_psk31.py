"""PSK31: Varicode and the software modem, against synthetic band audio."""

import math
import string

import numpy as np

from kx3rig.keyboard import psk31, varicode

RATE = 12_000
TEXT = "CQ CQ DE N0CALL N0CALL PSE K"


def _noisy(wave: np.ndarray, snr_db: float, seed: int = 1) -> np.ndarray:
    """Add white noise so the signal is snr_db above the noise in 3 kHz."""
    rng = np.random.default_rng(seed)
    sig_power = float(np.mean(wave.astype(np.float64) ** 2))
    noise_3k = sig_power / 10 ** (snr_db / 10)
    sigma = math.sqrt(noise_3k * (RATE / 2) / 3000)
    return (wave + rng.normal(0, sigma, wave.size)).astype(np.float32)


def _decode(audio: np.ndarray, freq: float, chunk: int = 2048) -> str:
    d = psk31.Decoder(RATE, freq)
    out = []
    for i in range(0, audio.size, chunk):
        out.append(d.feed(audio[i:i + chunk]))
    return "".join(out)


def test_varicode_table_properties():
    assert len(varicode.CODES) == 128
    assert len(set(varicode.CODES)) == 128
    for code in varicode.CODES:
        assert "00" not in code and code[0] == "1" and code[-1] == "1"
    assert varicode.CODES[ord(" ")] == "1" and varicode.CODES[ord("e")] == "11"


def test_varicode_round_trip_printable_ascii():
    text = "".join(ch for ch in string.printable if ord(ch) < 128)
    dec = varicode.Decoder()
    out = [dec.push(b) for b in "00" + varicode.encode(text)]
    assert "".join(c for c in out if c) == text


def test_modulate_bounds_and_edges():
    wave = psk31.modulate(TEXT, RATE, 1000)
    assert wave.dtype == np.float32
    assert np.max(np.abs(wave)) <= 1.0
    assert abs(wave[0]) < 1e-3 and abs(wave[-1]) < 1e-3
    assert wave.size == round(psk31.duration_s(TEXT) * RATE)


def test_char_times_monotonic_and_inside_duration():
    times = psk31.char_times(TEXT)
    assert [c for c, _ in times] == list(TEXT)
    starts = [t for _, t in times]
    assert all(b > a for a, b in zip(starts, starts[1:]))
    assert 0.9 < starts[0] < 1.1
    assert starts[-1] < psk31.duration_s(TEXT) - 0.5


def test_decodes_through_noise():
    audio = _noisy(psk31.modulate(TEXT, RATE, 1500), snr_db=10)
    text = _decode(audio, 1500)
    assert text.endswith(TEXT[2:]) and TEXT[2:] in text


def test_afc_pulls_in_a_mistuned_signal():
    audio = _noisy(psk31.modulate(TEXT, RATE, 1207), snr_db=10)
    d = psk31.Decoder(RATE, 1200)
    text = "".join(d.feed(audio[i:i + 4096]) for i in range(0, audio.size, 4096))
    assert TEXT[4:] in text
    assert abs(d.freq - 1207) < 1.0


def test_chunk_size_does_not_matter():
    audio = _noisy(psk31.modulate("TEST 73", RATE, 900), snr_db=15)
    results = {_decode(audio, 900, chunk) for chunk in (1, 37, 4096)}
    assert len(results) == 1 and "TEST 73" in results.pop()


def test_noise_alone_prints_nothing():
    rng = np.random.default_rng(3)
    audio = rng.normal(0, 0.1, RATE * 10).astype(np.float32)
    d = psk31.Decoder(RATE, 1000)
    assert "".join(d.feed(audio[i:i + 2048]) for i in range(0, audio.size, 2048)) == ""
    assert not d.active


def test_browser_finds_and_decodes_two_stations():
    audio = psk31.demo_signal([("CQ DE K1ABC K", 1000), ("TNX FER CALL W2XYZ", 1200)], 30, RATE,
                              snr_db=12, seed=4)
    b = psk31.Browser(RATE)
    for i in range(0, audio.size, 2400):
        b.feed(audio[i:i + 2400])
    texts = {round(c.freq / 100) * 100: c.text for c in b.channels}
    assert "K1ABC" in texts.get(1000, "")
    assert "W2XYZ" in texts.get(1200, "")
