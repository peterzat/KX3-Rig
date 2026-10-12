"""Software CW: Morse timing, keyed-tone audio, and the receive decoder."""

import time

import numpy as np
import pytest

from kx3rig.keyboard import cw

RATE = 12_000
TEXT = "CQ CQ DE N0CALL N0CALL K"


def keyed(text, wpm, snr_db, seed=1, jitter=0.0, f=700.0, lead_s=1.5):
    """Hard-keyed test signal: a tone of power 1 plus white noise at snr_db in 3 kHz."""
    rng = np.random.default_rng(seed)
    runs = cw.timing(text, wpm)
    if jitter:
        runs = [(down, s * (1 + rng.uniform(-jitter, jitter))) for down, s in runs]
    env = [np.zeros(int(lead_s * RATE))]
    env += [np.full(int(round(s * RATE)), 1.0 if down else 0.0) for down, s in runs]
    env.append(np.zeros(RATE))
    env = np.concatenate(env)
    x = np.sqrt(2) * env * np.sin(2 * np.pi * f * np.arange(env.size) / RATE)
    sigma = np.sqrt(10 ** (-snr_db / 10) * (RATE / 2) / 3000)
    return (x + rng.normal(0, sigma, x.size)).astype(np.float32)


def decode(x, **kw):
    d = cw.Decoder(**kw)
    return d, " ".join((d.feed(x) + d.flush()).split())


def char_errors(got, want):
    """Levenshtein distance, for 'at most one error'."""
    prev = list(range(len(want) + 1))
    for i, a in enumerate(got, 1):
        cur = [i]
        for j, b in enumerate(want, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (a != b)))
        prev = cur
    return prev[-1]


def test_paris_is_fifty_units():
    runs = cw.timing("PARIS", 20)
    dot = 1.2 / 20
    # 43 units from the first element to the last, plus the 7-unit word gap that ends it.
    assert sum(s for _, s in runs) / dot == pytest.approx(43)
    assert sum(s for _, s in cw.timing("PARIS PARIS", 20)) / dot == pytest.approx(43 + 7 + 43)
    assert cw.normalize("cq de n0call #~") == "CQ DE N0CALL"
    assert cw.tokens("73 <sk>") == ["7", "3", " ", "<SK>"]


def test_farnsworth_stretches_only_the_gaps():
    fast = cw.timing("PARIS PARIS", 20, farnsworth_wpm=10)
    marks = sum(s for down, s in fast if down)
    assert marks == pytest.approx(sum(s for down, s in cw.timing("PARIS PARIS", 20) if down))
    assert sum(s for _, s in fast) > sum(s for _, s in cw.timing("PARIS PARIS", 20)) * 1.5


def test_modulate_is_bounded_and_shaped():
    rate = 48_000
    x = cw.modulate("E", wpm=20, rate=rate, f0=700, rise_ms=5)
    assert np.max(np.abs(x)) <= 1.0
    assert x[0] == 0 and x[-1] == 0
    nz = np.flatnonzero(np.abs(x) > 1e-6)
    first_full = np.flatnonzero(np.abs(x) > 0.99)[0]
    assert (first_full - nz[0]) / rate >= 0.0045          # the edge takes about rise_ms
    assert len(x) / rate == pytest.approx(cw.duration_s("E", 20), abs=0.002)
    times = cw.char_times("CQ K", 20)
    assert [t for t, _ in times] == ["C", "Q", " ", "K"]
    assert times[0][1] == pytest.approx(cw.LEAD_S)


@pytest.mark.parametrize("wpm", [13, 20, 30])
def test_decodes_a_cq_at_10_db(wpm):
    d, text = decode(keyed(TEXT, wpm, 10))
    assert char_errors(text, TEXT) <= 1
    assert d.wpm == pytest.approx(wpm, rel=0.15)


def test_decodes_hand_keying():
    _, text = decode(keyed(TEXT, 20, 10, jitter=0.10))
    assert char_errors(text, TEXT) <= 1


def test_weak_signal_at_0_db():
    _, text = decode(keyed(TEXT, 20, 0, seed=2))
    assert char_errors(text, TEXT) <= 1


def test_chunk_size_does_not_change_the_text():
    x = keyed(TEXT, 20, 5)
    whole = cw.Decoder().feed(x)
    d = cw.Decoder()
    rng = np.random.default_rng(0)
    out, i = "", 0
    while i < x.size:
        n = int(rng.integers(1, 3000))
        out += d.feed(x[i:i + n])
        i += n
    assert out == whole


def test_noise_alone_prints_almost_nothing():
    for seed in range(3):
        n = np.random.default_rng(seed).normal(0, 0.1, 10 * RATE).astype(np.float32)
        d = cw.Decoder()
        assert len(d.feed(n).strip()) <= 2
        assert not d.active


def test_follows_a_speed_change():
    a = keyed("VVV DE N0CALL VVV", 12, 10)
    b = keyed("VVV DE N0CALL VVV TEST", 35, 10, seed=3, lead_s=0.3)
    d = cw.Decoder(wpm=12)
    text = d.feed(np.concatenate([a, b]))
    assert text.rstrip().endswith("DE N0CALL VVV TEST")
    assert d.wpm == pytest.approx(35, rel=0.15)


def test_prosigns():
    _, text = decode(keyed("<SK> <AR> <BT> <KN> <BK> ? /", 20, 10))
    assert text == "<SK> <AR> <BT> <KN> <BK> ? /"
    # Punctuation sharing a prosign's code prints as the prosign.
    _, text = decode(keyed("= + (", 20, 10))
    assert text == "<BT> <AR> <KN>"


def test_strongest_tone():
    assert cw.strongest_tone(keyed(TEXT, 20, 0, f=733)) == pytest.approx(733, abs=10)
    assert cw.strongest_tone(np.random.default_rng(1).normal(0, 0.1, 3 * RATE)) is None


def test_demo_stations_decode_on_their_own_tones():
    y = cw.demo_signal([("CQ DE W7DEM K", 18, 650), ("TEST N0XYZ", 25, 900)], 20)
    assert "W7DEM" in cw.Decoder(freq=650).feed(y)
    assert "N0XYZ" in cw.Decoder(freq=900).feed(y)


def test_decoder_is_cheap():
    x = keyed(TEXT, 20, 10)
    t = time.perf_counter()
    cw.Decoder().feed(x)
    assert (time.perf_counter() - t) / (x.size / RATE) < 0.05      # under 5% of real time
