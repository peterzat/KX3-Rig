"""FT4 encode and waveform (ported from WSJT-X), and a round trip through jt9 -5."""

import shutil
import subprocess
import time

import numpy as np
import pytest

from kx3rig.ft8 import ft4
from kx3rig.ft8.decode import wav_name, write_wav

from .test_ft8_engine_parts import FT8CODE_OUTPUT

needs_wsjtx = pytest.mark.skipif(not (shutil.which("ft8code") and shutil.which("jt9")),
                                 reason="WSJT-X ft8code/jt9 not installed")


def _printed(label):
    lines = FT8CODE_OUTPUT.splitlines()
    return [int(c) for c in lines[lines.index(label) + 1]]


def test_crc_and_parity_match_ft8code():
    # FT8 and FT4 share the LDPC(174,91) code, so ft8code's printout checks the port.
    bits = ft4.parse_bits77(FT8CODE_OUTPUT)
    cw = ft4.encode174_91(bits)
    assert len(cw) == 174 and cw[:77] == bits
    assert cw[77:91] == _printed("14-bit CRC:")
    assert cw[91:] == _printed("83 Parity bits:")


def test_tone_frame():
    t = ft4.tones(ft4.parse_bits77(FT8CODE_OUTPUT))
    assert len(t) == ft4.NSYM == 103 and set(t) <= {0, 1, 2, 3}
    for pos, costas in zip((0, 33, 66, 99), ft4.COSTAS):
        assert t[pos:pos + 4] == costas


def test_waveform_length_amplitude_and_ends():
    t = ft4.tones(ft4.parse_bits77(FT8CODE_OUTPUT))
    w = ft4.waveform(t, 12_000, 1000.0)
    assert len(w) == 105 * 576 == 60_480             # 5.04 s
    assert np.max(np.abs(w)) <= 1.0
    assert abs(w[0]) < 1e-6 and abs(w[-1]) < 0.01
    assert np.max(np.abs(w[:20])) < 0.01               # raised-cosine ramp-up


def test_each_symbol_sits_on_its_tone():
    rate, f0 = 12_000, 1000.0
    t = ft4.tones(ft4.parse_bits77(FT8CODE_OUTPUT))
    w = ft4.waveform(t, rate, f0)
    nsps = 576
    freqs = np.fft.rfftfreq(nsps * 8, 1 / rate)
    for j in (0, 5, 20, 40, 70, 102):
        seg = w[(j + 1) * nsps: (j + 2) * nsps] * np.hanning(nsps)
        spec = np.abs(np.fft.rfft(seg, nsps * 8))
        peak = freqs[np.argmax(spec)]
        assert round((peak - f0) / ft4.TONE_SPACING_HZ) == t[j]


def test_parse_jt9_ft4_line():
    d = ft4.parse_jt9_ft4_line("130007  -5  0.2 1159 +  CQ K1ABC FN42")
    assert (d.hhmmss, d.snr, d.dt, d.freq, d.message, d.low_confidence) == \
        ("130007", -5, 0.2, 1159, "CQ K1ABC FN42", False)
    d = ft4.parse_jt9_ft4_line("130007 -18  0.1 1200 +  K1ABC W1AW -12                      ? a2")
    assert d.message == "K1ABC W1AW -12" and d.low_confidence and d.ap == "a2"
    assert ft4.parse_jt9_ft4_line("130000  -1  0.5 1159 ~  ZL1ABC EA3ABC -19") is None   # FT8
    assert ft4.parse_jt9_ft4_line("<DecodeFinished>   0  30        0") is None


@needs_wsjtx
def test_encode_matches_ft8code_packing():
    e = ft4.encode("CQ K1ABC FN42")
    assert e.sent == "CQ K1ABC FN42" and len(e.tones) == 103


@needs_wsjtx
def test_round_trip_through_jt9_ft4(tmp_path):
    rate = 12_000
    period = np.random.default_rng(2).normal(0, 0.05, ft4.DECODE_SAMPLES).astype(np.float32)
    for text, f0 in (("CQ K1ABC FN42", 1500.0), ("K1ABC W1AW -12", 800.0)):
        w = ft4.waveform(ft4.encode(text).tones, rate, f0)
        start = int(0.5 * rate) - 576          # ramp symbol first, data at 0.5 s (ft4sim.f90)
        period[start:start + len(w)] += 0.3 * w
    t0 = time.time() // 15 * 15
    path = tmp_path / wav_name(t0)
    write_wav(str(path), period)
    out = subprocess.run(["jt9", "-5", "-d", "2", "-c", "K1ABC", "-a", str(tmp_path), "-t", str(tmp_path),
                          str(path)], cwd=tmp_path, capture_output=True, text=True, timeout=30).stdout
    decodes = [d for d in (ft4.parse_jt9_ft4_line(line) for line in out.splitlines()) if d]
    found = {(d.message, round(d.freq / 10)) for d in decodes}
    assert ("CQ K1ABC FN42", 150) in found
    assert ("K1ABC W1AW -12", 80) in found
