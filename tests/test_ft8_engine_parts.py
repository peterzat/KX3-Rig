"""FT8 encode/decode pieces, including a real round trip through WSJT-X tools."""

import shutil
import time
import wave
from datetime import datetime, timezone

import numpy as np
import pytest

from kx3rig.ft8 import adif, encode, grid
from kx3rig.ft8.decode import Jt9, SlotRecorder, parse_jt9_line, wav_name, write_wav

needs_wsjtx = pytest.mark.skipif(not (shutil.which("ft8code") and shutil.which("jt9")),
                                 reason="WSJT-X ft8code/jt9 not installed")

FT8CODE_OUTPUT = """    Message                               Decoded                             Err i3.n3
----------------------------------------------------------------------------------------------------
 1. CQ K1ABC FN42                         CQ K1ABC FN42                            1.  Standard msg

Source-encoded message, 77 bits:
00000000000000000000000000100000010011011110111100011010100010100001100110001

14-bit CRC:
00101100101110

83 Parity bits:
10101000001001000110111100001111000000111010010110111110100110100100001010010100110

Channel symbols (79 tones):
  Sync               Data               Sync               Data               Sync
3140652 00000000100547670460602153343 3140652 73601104751700733474545513354 3140652
"""
CQ_TONES = "3140652000000001005476704606021533433140652736011047517007334745455133543140652"


def test_parse_ft8code_fixture():
    requested, sent, lossy, tones = encode.parse_ft8code(FT8CODE_OUTPUT)
    assert requested == sent == "CQ K1ABC FN42"
    assert not lossy
    assert "".join(map(str, tones)) == CQ_TONES


def test_parse_jt9_lines():
    d = parse_jt9_line("130000  -1  0.5 1159 ~  ZL1ABC EA3ABC -19")
    assert (d.snr, d.dt, d.freq, d.message, d.low_confidence) == (-1, 0.5, 1159, "ZL1ABC EA3ABC -19", False)
    d = parse_jt9_line("170005 -24 -0.0 1200 ~  K1ABC W1AW -12                      ? a3")
    assert d.message == "K1ABC W1AW -12" and d.low_confidence and d.ap == "a3"
    assert parse_jt9_line("<DecodeFinished>   0  30        0") is None
    assert parse_jt9_line("") is None


def test_wav_name_is_utc_hhmmss():
    t = datetime(2026, 10, 10, 21, 45, 15, tzinfo=timezone.utc).timestamp()
    assert wav_name(t) == "261010_214515.wav"


def test_write_wav_format(tmp_path):
    path = str(tmp_path / "x.wav")
    write_wav(path, np.sin(np.arange(12000) / 10).astype(np.float32))
    with wave.open(path) as w:
        assert (w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()) == (1, 2, 12000, 12000)


def test_waveform_shape_and_spectrum():
    tones = [int(c) for c in CQ_TONES]
    w = encode.waveform(tones, 12000, 1500.0)
    assert len(w) == 79 * 1920
    assert np.max(np.abs(w)) <= 1.0
    # Energy sits between 1500 and 1500 + 7 * 6.25 Hz.
    spec = np.abs(np.fft.rfft(w))
    peak_hz = np.argmax(spec) * 12000 / len(w)
    assert 1490 < peak_hz < 1560


def test_recorder_aligns_to_wall_clock():
    rec = SlotRecorder(seconds=10)
    t0 = 1_000_000.0
    chunk = 240
    for i in range(200):  # 4 s of a ramp signal
        samples = np.arange(i * chunk, (i + 1) * chunk, dtype=np.float32)
        rec.feed(samples, t0 + (i + 1) * chunk / 12000)
    out, present = rec.extract(t0 + 1.0, 1.0)
    assert present == pytest.approx(1.0)
    assert out[0] == pytest.approx(12000, abs=2)
    out, present = rec.extract(t0 + 3.5, 1.0)   # runs past the newest sample
    assert present == pytest.approx(0.5, abs=0.01)
    assert out[-1] == 0


def test_grid_math():
    d = grid.distance_km("DM79", "FN31")
    assert 2500 < d < 2900
    assert grid.compass(grid.bearing_deg("DM79", "FN31")) == "E"
    assert grid.to_latlon("ZZ99") is None
    assert grid.to_latlon("FN42hn") is not None


def test_adif_record(tmp_path):
    path = str(tmp_path / "log.adi")
    on = datetime(2026, 10, 10, 21, 45, 0, tzinfo=timezone.utc)
    entry = adif.LogEntry(call="W1AW", grid="FN31", rst_sent=-12, rst_rcvd=-8, time_on=on, time_off=on,
                          band="20m", dial_hz=14_074_000, station_call="K1ABC", my_grid="FN42hn", tx_power_w=5)
    adif.append(path, entry)
    adif.append(path, entry)
    text = open(path).read()
    assert text.count("<eoh>") == 1
    assert "<call:4>W1AW" in text and "<rst_sent:3>-12" in text and "<freq:9>14.074000" in text
    assert "<qso_date:8>20261010" in text and "<time_on:6>214500" in text
    assert adif.count(path) == 2


@needs_wsjtx
@pytest.mark.parametrize("message", ["CQ K1ABC FN42", "W1AW K1ABC R-09", "K1ABC W1AW RR73"])
def test_encode_rejects_nothing_valid(message):
    assert encode.encode(message).sent == message


@needs_wsjtx
@pytest.mark.parametrize("message,reason", [
    ("", "empty"),
    ("W1AW K1ABC RR73 EXTRA", "can't be sent"),
    ("HELLO WORLD 123", "would arrive"),
])
def test_encode_refuses_mangled_messages(message, reason):
    with pytest.raises(encode.EncodeError, match=reason):
        encode.encode(message)


@needs_wsjtx
def test_round_trip_through_jt9(tmp_path):
    """Synthesize two signals the way we transmit them; jt9 must decode both."""
    rate = 12000
    period = np.random.default_rng(1).normal(0, 0.05, 15 * rate).astype(np.float32)
    for text, f0 in (("CQ K1ABC FN42", 1500.0), ("K1ABC W1AW -12", 800.0)):
        w = encode.waveform(encode.encode(text).tones, rate, f0)
        start = int(0.5 * rate)
        period[start:start + len(w)] += 0.3 * w
    jt9 = Jt9(str(tmp_path))
    t0 = time.time() // 15 * 15
    decodes = jt9.decode(period, t0, "K1ABC")
    found = {(d.message, round(d.freq / 10)) for d in decodes}
    assert ("CQ K1ABC FN42", 150) in found
    assert ("K1ABC W1AW -12", 80) in found
    assert all(abs(d.dt) < 0.3 for d in decodes)
