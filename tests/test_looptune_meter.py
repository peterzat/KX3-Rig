"""The receive-noise meter that guides peaking the loop."""

import numpy as np

from kx3rig.looptune.meter import NoiseMeter, Reading
from kx3rig.smartscan.detect import RATE


def noise(seconds, amp, rng):
    return rng.normal(0, amp, int(seconds * RATE)).astype(np.float32)


def run(meter, amps, rng, seconds=0.75):
    states = []
    for amp in amps:
        audio = noise(seconds, amp, rng)
        for i in range(0, len(audio), 600):     # 50 ms blocks, like the audio thread
            r = meter.feed(audio[i:i + 600])
            if r is not None:
                states.append(r)
    return states


def test_flat_noise_stays_searching():
    rng = np.random.default_rng(1)
    readings = run(NoiseMeter(), [0.02] * 6, rng)
    assert readings and all(r.state == "searching" for r in readings)


def test_finds_the_peak_and_notices_turning_past_it():
    rng = np.random.default_rng(2)
    meter = NoiseMeter()
    # The capacitor sweeps through resonance: noise rises about 12 dB, then falls.
    amps = [0.01, 0.014, 0.02, 0.03, 0.04, 0.04, 0.03, 0.02, 0.012]
    readings = run(meter, amps, rng)
    states = [r.state for r in readings]
    assert "peak" in states
    assert states[-1] == "past"
    best = readings[-1].best_db
    assert best - readings[-1].low_db > 9
    # Turning back onto the peak reads as the peak again.
    readings = run(meter, [0.04, 0.04], rng)
    assert readings[-1].state == "peak"


def test_a_steady_signal_does_not_lift_the_noise_reading():
    rng = np.random.default_rng(3)
    meter = NoiseMeter()
    base = run(meter, [0.02] * 3, rng)[-1].level_db
    t = np.arange(int(1.5 * RATE)) / RATE
    tone = (0.3 * np.sin(2 * np.pi * 1000 * t)).astype(np.float32)
    with_tone = None
    audio = noise(1.5, 0.02, rng) + tone
    for i in range(0, len(audio), 600):
        with_tone = meter.feed(audio[i:i + 600]) or with_tone
    assert abs(with_tone.level_db - base) < 2


def test_reset_and_bar_fraction():
    rng = np.random.default_rng(4)
    meter = NoiseMeter()
    run(meter, [0.02, 0.04], rng)
    assert meter.reading is not None
    meter.reset()
    assert meter.reading is None
    r = Reading(level_db=-50, best_db=-50, low_db=-52, state="searching")
    assert r.fraction() == 1.0
    assert 0.0 <= Reading(-60, -50, -62, "past").fraction() < 0.3
