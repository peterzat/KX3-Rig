"""WSPR encoding, audio, wsprd output parsing, and scheduling."""

import shutil
import wave

import numpy as np
import pytest

from kx3rig.wspr import protocol as p

# Channel symbols from a reference build of WSJT-X lib/wsprd/wsprsim_utils.c
# (get_wspr_channel_symbols with fano.c's encoder), commit b4f9a43.
REFERENCE = {
    ("K1ABC", "FN42", 37): "330020001020131222100323133220200032012322002232110233210221321222033030301210212032132003323032203020201023021112330231212221332000010320132222202332323320031222",
    ("W7XYZ", "DM79", 23): "310002201022131222122303313002220012010122220230310011212023101222211230101010230210310201123210223020001023003332312211030201332202232302310000220332121120211022",
    ("K1ABC", "FN42", 0): "330022021022131022120123113022200030012320002230110233210023321022033232321212212232112203303030203222221223021110330231212223312002030122112020222132323122011022",
    ("G4ABC", "IO91", 10): "332000221202333020102101131202220010012302222210112031230203321020033010321232012212330023303212201202223203201312112013210021312220030122330202222312301102231220",
    ("KD7ABC", "CN87", 30): "310000223002111002100323313220202010030320002032330031230003103002013012121212230210310221323212203200203003203112312011012023312222010322312202000312321100011200",
    ("N0CAL", "CN87", 30): "332000021022131022100103333202200010030320200012112013232023301020211012321232032210112201321232221222001223023110110011232023112222230322310022220330321320211222",
    ("W1AW", "FN31", 60): "332022001022333222302101333200020012030120200230332013012023103020013212101010210010112201301010221002001023201332110213212203312220230300312202200330301300033020",
}


@pytest.mark.parametrize("key", list(REFERENCE))
def test_symbols_match_wsjtx(key):
    assert "".join(map(str, p.channel_symbols(*key))) == REFERENCE[key]


def test_sync_bits_are_the_sync_vector():
    sym = p.channel_symbols("K1ABC", "FN42", 37)
    assert len(sym) == p.NSYM and all(0 <= s <= 3 for s in sym)
    assert tuple(s & 1 for s in sym) == p.SYNC


def test_lowercase_input_is_accepted():
    assert p.channel_symbols("k1abc", "fn42", 37) == p.channel_symbols("K1ABC", "FN42", 37)


@pytest.mark.parametrize("call,grid,dbm", [
    ("K1ABC/P", "FN42", 37), ("PJ4/K1ABC", "FN42", 37), ("<K1ABC>", "FN42", 37),
    ("N0CALL", "CN87", 30),        # 7 characters once the digit is aligned
    ("K1ABC", "FN42AB", 37), ("K1ABC", "ZZ99", 37), ("K1ABC", "FN42", 36), ("", "FN42", 37),
    ("ABCDE", "FN42", 37),
])
def test_only_type1_messages(call, grid, dbm):
    with pytest.raises(ValueError):
        p.channel_symbols(call, grid, dbm)


def test_dbm_rounding():
    assert p.watts_to_dbm(5) == 37
    assert p.watts_to_dbm(1) == 30
    assert p.watts_to_dbm(10) == 40
    assert p.watts_to_dbm(0.2) == 23
    assert p.watts_to_dbm(0) == 0
    assert p.watts_to_dbm(2000) == 60
    assert p.dbm_to_watts(37) == pytest.approx(5.01, abs=0.01)
    assert all(d % 10 in (0, 3, 7) for d in p.DBM_VALUES) and len(p.DBM_VALUES) == 19


def test_waveform_length_and_tones():
    sym = p.channel_symbols("K1ABC", "FN42", 37)
    rate = 12_000
    w = p.waveform(sym, rate=rate, f_center=1500.0)
    assert len(w) == 162 * 8192 and abs(p.DURATION_S - 110.592) < 1e-3
    assert np.max(np.abs(w)) <= 1.0 + 1e-6 and abs(w[0]) < 1e-3 and abs(w[-1]) < 1e-2
    assert len(p.waveform(sym, rate=48_000)) == 162 * 8192 * 4
    # Each symbol's strongest bin is its tone (8192-point FFT: one bin per tone).
    freqs = np.fft.rfftfreq(8192, 1 / rate)
    for i, s in enumerate(sym):
        seg = w[i * 8192:(i + 1) * 8192]
        peak = freqs[np.argmax(np.abs(np.fft.rfft(seg)))]
        assert abs(peak - (1500 + (s - 1.5) * p.TONE_HZ)) < 0.8


def test_parse_wsprd_lines():
    line = "%4s %3.0f %4.1f %10.6f %2d  %-s \n" % ("0412", -21.0, 0.3, 14.097063, -1, "K1ABC FN42 37")
    s = p.parse_wsprd_line(line)
    assert s == p.Spot("0412", -21, 0.3, 14_097_063, -1, "K1ABC FN42 37", "K1ABC", "FN42", 37)
    odd = "%4s %3.0f %4.1f %10.6f %2d  %-s \n" % ("0412", -8.0, -1.2, 7.040123, 0, "PJ4/K1ABC 37")
    s = p.parse_wsprd_line(odd)
    assert s.message == "PJ4/K1ABC 37" and s.call == "" and s.dbm is None
    assert p.parse_wsprd_line("<DecodeFinished>") is None
    assert p.parse_wsprd_line("") is None
    assert p.parse_wsprd_line("garbage line") is None


def test_scheduler_percentage_and_spacing():
    sched = p.TxScheduler(20, seed=7)
    picks = [sched.transmit_in(s) for s in range(600)]
    assert 15 <= 100 * sum(picks) / 600 <= 25
    assert not any(a and b for a, b in zip(picks, picks[1:]))
    again = p.TxScheduler(20, seed=7)
    assert [again.transmit_in(s) for s in range(600)] == picks


@pytest.mark.parametrize("pct", [10, 33, 50, 70])
def test_scheduler_other_percentages(pct):
    sched = p.TxScheduler(pct, seed=3)
    picks = [sched.transmit_in(s) for s in range(600)]
    assert abs(100 * sum(picks) / 600 - pct) <= 5
    if pct < 50:
        assert not any(a and b for a, b in zip(picks, picks[1:]))


def test_scheduler_extremes():
    assert not any(p.TxScheduler(0, seed=1).transmit_in(s) for s in range(120))
    assert all(p.TxScheduler(100, seed=1).transmit_in(s) for s in range(120))


def test_wav_file(tmp_path):
    path = tmp_path / p.wav_name(1_760_000_040.0)
    assert path.name == "251009_0854.wav"
    p.write_wav(str(path), np.ones(5 * 12_000, np.float32) * 0.1)
    data = path.read_bytes()
    assert len(data) == 44 + 2 * 114 * 12_000
    with wave.open(str(path)) as w:
        assert (w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()) == (1, 2, 12_000, 114 * 12_000)


def test_dials_are_in_band():
    from kx3rig import bandplan

    for name, hz in p.DIALS.items():
        assert bandplan.band_for(hz) is bandplan.BY_NAME[name]


@pytest.mark.skipif(shutil.which("wsprd") is None, reason="WSJT-X's wsprd isn't installed")
def test_wsprd_round_trip(tmp_path):
    import subprocess

    sym = p.channel_symbols("K1ABC", "FN42", 37)
    rng = np.random.default_rng(0)
    audio = np.zeros(114 * 12_000, np.float32)
    w = p.waveform(sym, rate=12_000, f_center=1500.0)
    start = int(p.TX_START_S * 12_000)
    audio[start:start + len(w)] += 0.1 * w
    audio += rng.normal(0, 0.05, audio.size).astype(np.float32)
    path = tmp_path / "251009_0854.wav"
    p.write_wav(str(path), audio)
    out = subprocess.run(["wsprd", "-a", str(tmp_path), "-f", "14.095600", str(path)],
                         capture_output=True, text=True, timeout=60, cwd=tmp_path).stdout
    spots = [s for s in (p.parse_wsprd_line(line) for line in out.splitlines()) if s]
    assert any(s.call == "K1ABC" and s.grid == "FN42" and s.dbm == 37 for s in spots)
