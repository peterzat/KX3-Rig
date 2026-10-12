"""Smartscan's signal detector on synthetic receive audio."""

import numpy as np
import pytest

from kx3rig.demo import synth_cw, synth_voice
from kx3rig.smartscan.detect import detect, noise_floor_db

RATE = 12_000
SECONDS = 1.6


def band_noise(rng, seconds=SECONDS, level=0.08):
    """Receiver noise through a 250-2900 Hz IF filter."""
    n = rng.normal(0, level, int(seconds * RATE))
    f = np.fft.rfft(n)
    freqs = np.fft.rfftfreq(len(n), 1 / RATE)
    f[(freqs < 250) | (freqs > 2900)] *= 0.05
    return np.fft.irfft(f, len(n)).astype(np.float32)


def carrier(freq, amp, seconds=SECONDS):
    t = np.arange(int(seconds * RATE)) / RATE
    return (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)


SEEDS = range(8)


@pytest.mark.parametrize("seed", SEEDS)
def test_noise_alone_finds_nothing(seed):
    assert detect(band_noise(np.random.default_rng(seed))) == []


@pytest.mark.parametrize("seed", SEEDS)
def test_voice_is_found_where_it_is(seed):
    rng = np.random.default_rng(seed)
    audio = band_noise(rng) + synth_voice(SECONDS, RATE, center_hz=1100, amp=0.05, rng=rng)
    found = detect(audio)
    assert [d.kind for d in found] == ["voice"]
    v = found[0]
    assert v.low_hz < 1100 < v.high_hz and v.high_hz - v.low_hz >= 400
    assert v.is_contact and v.snr_db > 3


@pytest.mark.parametrize("seed", SEEDS)
def test_cw_is_keyed_and_narrow(seed):
    rng = np.random.default_rng(seed)
    found = detect(band_noise(rng) + synth_cw(SECONDS, RATE, freq=700, amp=0.03))
    assert [d.kind for d in found] == ["cw"]
    assert abs(found[0].peak_hz - 700) < 30


@pytest.mark.parametrize("seed", SEEDS)
def test_steady_carrier_is_not_a_contact(seed):
    found = detect(band_noise(np.random.default_rng(seed)) + carrier(1234, 0.02))
    assert [d.kind for d in found] == ["carrier"]
    assert not found[0].is_contact


@pytest.mark.parametrize("seed", SEEDS)
def test_voice_beside_a_carrier(seed):
    rng = np.random.default_rng(seed)
    audio = band_noise(rng) + synth_voice(SECONDS, RATE, center_hz=1000, amp=0.05, rng=rng) + carrier(2600, 0.02)
    kinds = sorted(d.kind for d in detect(audio))
    assert kinds == ["carrier", "voice"]


def test_too_short_finds_nothing():
    assert detect(np.zeros(1000, np.float32)) == []
    assert noise_floor_db(np.zeros(1000, np.float32)) is None


def test_noise_floor_follows_level():
    rng = np.random.default_rng(1)
    loud = noise_floor_db(band_noise(rng, level=0.08))
    quiet = noise_floor_db(band_noise(rng, level=0.02))
    assert loud - quiet == pytest.approx(12.0, abs=1.5)
