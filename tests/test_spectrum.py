import numpy as np
import pytest

from kx3rig.spectrum import AutoLevel, Spectrum, audio_to_rf, rms_dbfs


def tone(freq, seconds=1.0, rate=12000, amp=0.5):
    t = np.arange(int(seconds * rate)) / rate
    return (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def test_tone_peaks_in_the_right_bin():
    spec = Spectrum()
    rows = spec.feed(tone(1500.0))
    assert rows, "a second of audio must yield rows"
    peak_hz = int(np.argmax(rows[-1])) * spec.bin_hz
    assert abs(peak_hz - 1500.0) <= spec.bin_hz


def test_row_rate_matches_hop():
    spec = Spectrum(fft_size=2048, hop=512)
    rows = spec.feed(np.zeros(2048 + 512 * 9, dtype=np.float32))
    assert len(rows) == 10


def test_feed_accumulates_partial_chunks():
    spec = Spectrum(fft_size=2048, hop=512)
    assert spec.feed(np.zeros(1000, dtype=np.float32)) == []
    assert len(spec.feed(np.zeros(1048, dtype=np.float32))) == 1


def test_full_scale_sine_is_near_zero_db():
    spec = Spectrum()
    row = spec.feed(tone(1000.0, amp=1.0))[-1]
    assert -1.5 < row.max() < 0.5


def test_bad_hop_rejected():
    with pytest.raises(ValueError):
        Spectrum(fft_size=1024, hop=2048)


def test_bins_for_range():
    spec = Spectrum(fft_size=2048)
    s = spec.bins_for(0, 3000)
    assert s.start == 0 and abs((s.stop - 1) * spec.bin_hz - 3000) < spec.bin_hz


def test_autolevel_puts_noise_low_and_signal_high():
    level = AutoLevel(span_db=50, below_floor_db=6)
    row = np.full(1000, -80.0)
    row[500] = -30.0
    out = level.normalize(row)
    assert out[0] < 0.2
    assert out[500] > 0.9


def test_autolevel_tracks_floor_slowly():
    level = AutoLevel(smoothing=0.1)
    level.normalize(np.full(10, -80.0))
    level.normalize(np.full(10, -40.0))
    assert -80.0 < level.floor < -70.0


def test_rms_dbfs():
    assert rms_dbfs(tone(1000, amp=1.0)) == pytest.approx(-3.01, abs=0.05)
    assert rms_dbfs(np.zeros(0, dtype=np.float32)) == -120.0


def test_audio_to_rf_sidebands():
    assert audio_to_rf(1500, 14_074_000, lower_sideband=False) == 14_075_500
    assert audio_to_rf(1500, 7_200_000, lower_sideband=True) == 7_198_500
