"""Smartscan's sweep plan, heard list, and band-conditions grading."""

import calendar
import time

import numpy as np
import pytest

from kx3rig import bandplan
from kx3rig.cat import Mode
from kx3rig.smartscan import conditions as cond
from kx3rig.smartscan.detect import Detection
from kx3rig.smartscan.heard import FORGET_S, HeardList
from kx3rig.smartscan.plan import AUDIO_HIGH, AUDIO_LOW, make_plan

B = bandplan.BY_NAME


# --- scan ranges and plans ----------------------------------------------------------

def test_scan_ranges_follow_privileges():
    assert bandplan.scan_ranges(B["20m"], "voice", "General") == [(14_225_000, 14_350_000)]
    assert bandplan.scan_ranges(B["20m"], "voice", "Extra") == [(14_150_000, 14_350_000)]
    assert bandplan.scan_ranges(B["20m"], "cw", "General") == [(14_025_000, 14_070_000)]
    assert bandplan.scan_ranges(B["40m"], "voice", "General") == [(7_175_000, 7_300_000)]
    assert bandplan.scan_ranges(B["30m"], "voice", "General") == []
    assert bandplan.scan_ranges(B["60m"], "voice", "General") == []
    assert bandplan.scan_ranges(B["20m"], "voice", "Technician") == []
    assert bandplan.scan_ranges(B["10m"], "voice", "Technician") == [(28_300_000, 28_500_000)]


def _covered(plan):
    spans = sorted(plan.audio_window(d) for d in plan.steps)
    return spans


@pytest.mark.parametrize("band,mode", [("20m", Mode.USB), ("40m", Mode.LSB), ("17m", Mode.DATA),
                                       ("20m", Mode.CW), ("80m", Mode.LSB), ("6m", Mode.USB)])
def test_plan_covers_every_range_without_gaps(band, mode):
    plan = make_plan(B[band], mode, "General")
    spans = _covered(plan)
    for low, high in plan.ranges:
        inside = [s for s in spans if s[1] > low and s[0] < high]
        assert inside[0][0] <= low and inside[-1][1] >= high
        for a, b in zip(inside, inside[1:]):
            assert b[0] <= a[1], "consecutive windows must overlap"


def test_plan_follows_mode():
    voice = make_plan(B["40m"], Mode.LSB, "General")
    assert voice.kind == "voice" and voice.scan_mode is Mode.LSB and voice.tune_mode is Mode.LSB
    data = make_plan(B["20m"], Mode.DATA, "General")
    assert data.kind == "voice" and data.scan_mode is Mode.USB
    cw = make_plan(B["40m"], Mode.CW, "General")
    assert cw.kind == "cw" and cw.scan_mode is Mode.USB and cw.tune_mode is Mode.CW
    assert make_plan(B["30m"], Mode.USB, "General").kind == "cw"   # no voice on 30 m
    assert make_plan(B["60m"], Mode.USB, "General") is None


def test_twenty_meter_voice_sweep_size():
    plan = make_plan(B["20m"], Mode.USB, "General")
    # 125 kHz in 2.4 kHz steps.
    assert 50 <= len(plan.steps) <= 54


def test_narrow_filter_means_more_steps():
    wide = make_plan(B["20m"], Mode.USB, "General", bandwidth_hz=2800)
    narrow = make_plan(B["20m"], Mode.USB, "General", bandwidth_hz=1800)
    assert len(narrow.steps) > len(wide.steps)
    assert narrow.audio_high < AUDIO_HIGH


def test_tune_frequency_usb_voice_snaps_to_khz():
    plan = make_plan(B["20m"], Mode.USB, "General")
    # Station on 14.230.000: voice energy from about 14.2303.
    d = Detection("voice", 1_300, 2_900, 1_800, 12, 0.5)
    assert plan.tune_frequency(14_229_000, d) == 14_230_000


def test_tune_frequency_lsb_voice():
    plan = make_plan(B["40m"], Mode.LSB, "General")
    # LSB station on 7.200.000: voice from 7.1997 down; dial at 7.201, so
    # the voice edge nearest the dial is at 1300 Hz audio.
    d = Detection("voice", 1_300, 2_700, 1_800, 12, 0.5)
    assert plan.tune_frequency(7_201_000, d) == 7_200_000


def test_tune_frequency_off_grid_rounds_to_100_hz():
    plan = make_plan(B["20m"], Mode.USB, "General")
    d = Detection("voice", 800, 2_600, 1_500, 12, 0.5)
    assert plan.tune_frequency(14_250_000, d) == 14_250_500


def test_tune_frequency_cw_is_on_the_signal():
    plan = make_plan(B["20m"], Mode.CW, "General")
    d = Detection("cw", 690, 720, 705, 12, 0.5)
    assert plan.tune_frequency(14_030_000, d) == 14_030_705


def test_calling_frequencies_get_their_own_steps_and_labels():
    voice = make_plan(B["20m"], Mode.USB, "General")
    assert 14_285_000 in voice.hot_steps            # QRP calling (14.286 AM shares the dial)
    assert len(voice.hot_steps) == 1
    assert voice.spot_label(14_285_000, "voice") == "QRP calling"
    assert voice.spot_label(14_286_000, "voice") == "AM calling"
    assert voice.spot_label(14_230_000, "voice") == "SSTV"
    assert voice.spot_label(14_300_000, "voice") == ""
    cw = make_plan(B["20m"], Mode.CW, "General")
    assert cw.hot_steps and cw.audio_window(cw.hot_steps[0])[0] < 14_060_000 < cw.audio_window(cw.hot_steps[0])[1]
    assert cw.spot_label(14_060_100, "cw") == "QRP calling"
    # Outside the class's privileges: no revisit (3.985 is General phone, 3.885 is too).
    assert make_plan(B["80m"], Mode.LSB, "General").hot_steps == (3_885_000, 3_985_000)
    assert make_plan(B["80m"], Mode.LSB, "Extra").hot_steps == (3_885_000, 3_985_000)


def test_sstv_sorts_last():
    h = HeardList()
    h.add(14_230_000, "voice", Mode.USB, 30, 0, now=100, spot="SSTV")
    h.add(14_300_000, "voice", Mode.USB, 5, -20, now=50)
    assert [e.spot for e in h.ordered()] == ["", "SSTV"]


# --- heard list -----------------------------------------------------------------------

def test_heard_merges_the_same_station():
    h = HeardList()
    a = h.add(14_230_000, "voice", Mode.USB, 8, -12, now=100)
    b = h.add(14_230_500, "voice", Mode.USB, 12, -6, now=160, clip=np.ones(10, np.float32), clip_dial=14_229_000)
    assert a is b and len(h.entries) == 1
    assert b.times == 2 and b.tune_hz == 14_230_500 and b.clip is not None and b.smeter_db == -6


def test_heard_keeps_the_stronger_clip_and_frequency():
    h = HeardList()
    h.add(14_230_000, "voice", Mode.USB, 15, -6, now=100, clip=np.ones(5, np.float32))
    e = h.add(14_231_000, "voice", Mode.USB, 5, -20, now=130, clip=np.zeros(5, np.float32))
    assert e.tune_hz == 14_230_000 and e.clip[0] == 1.0 and e.last_seen == 130


def test_heard_separates_kinds_and_distant_stations():
    h = HeardList()
    h.add(14_230_000, "voice", Mode.USB, 8, -12, now=100)
    h.add(14_235_000, "voice", Mode.USB, 8, -12, now=100)
    h.add(14_030_000, "cw", Mode.CW, 8, -12, now=100)
    h.add(14_030_400, "cw", Mode.CW, 8, -12, now=100)
    assert len(h.entries) == 4


def test_heard_forgets_old_stations_and_caps_size():
    h = HeardList()
    h.add(14_230_000, "voice", Mode.USB, 8, -12, now=0)
    h.add(14_240_000, "voice", Mode.USB, 8, -12, now=FORGET_S + 10)
    assert [e.tune_hz for e in h.entries] == [14_240_000]
    for i in range(30):
        h.add(14_000_000 + i * 5_000, "voice", Mode.USB, i, -12, now=FORGET_S + 20 + i)
    assert len(h.entries) == 12


def test_heard_order_is_newest_first():
    h = HeardList()
    h.add(14_230_000, "voice", Mode.USB, 20, -12, now=0)
    h.add(14_240_000, "voice", Mode.USB, 5, -12, now=300)
    assert [e.tune_hz for e in h.ordered()] == [14_240_000, 14_230_000]
    assert h.ordered()[0].age_text(310) == "just now"
    assert h.ordered()[1].age_text(310) == "5 min ago"


# --- conditions -------------------------------------------------------------------------

NOW = 1_791_772_800


def _xml(reports):
    rows = "".join(
        f'<receptionReport receiverCallsign="{rx}" receiverLocator="CN87ab" senderCallsign="{tx}" '
        f'senderLocator="{loc}" frequency="{f}" flowStartSeconds="{t}" mode="FT8" senderDXCC="{c}" sNR="-10" />'
        for rx, tx, loc, f, t, c in reports)
    return (f'<?xml version="1.0"?><receptionReports><lastSequenceNumber value="1"/>{rows}'
            f'<receptionReport receiverCallsign="X" senderCallsign="" frequency="7074000" flowStartSeconds="1"/>'
            f'<receptionReport receiverCallsign="X" senderCallsign="Y" frequency="bad" flowStartSeconds="1"/>'
            f'</receptionReports>').encode()


def test_parse_pskreporter_skips_bad_rows():
    reports = cond.parse_pskreporter(_xml([("N7AAA", "JA1AAA", "PM95", 14_074_500, NOW - 60, "Japan")]))
    assert len(reports) == 1
    r = reports[0]
    assert (r.sender, r.frequency, r.where, r.sender_grid) == ("JA1AAA", 14_074_500, "Japan", "PM95")


def test_grade_open_fair_quiet():
    rows = [("N7AAA", f"W{i}AAA", "DM79", 14_074_000 + i, NOW - 60, "United States") for i in range(6)]
    rows += [("N7AAA", "K7BBB", "CN85", 7_074_000, NOW - 60, "United States")]
    out = cond.grade(cond.parse_pskreporter(_xml(rows)), "CN87", now=NOW)
    assert out["20m"].level == cond.OPEN and out["20m"].senders == 6 and out["20m"].receivers == 1
    assert out["40m"].level == cond.FAIR
    assert out["15m"].level == cond.QUIET


def test_grade_dx_makes_a_band_open():
    rows = [("N7AAA", "JA1AAA", "PM95", 18_100_000, NOW - 60, "Japan"),
            ("N7AAA", "VK2AAA", "QF56", 18_101_000, NOW - 60, "Australia")]
    out = cond.grade(cond.parse_pskreporter(_xml(rows)), "CN87", now=NOW)
    o = out["17m"]
    assert o.level == cond.OPEN and o.farthest_where == "Australia" and o.farthest_km > 10_000
    assert "Australia" in o.tooltip("CN87")


def test_grade_ignores_stale_reports_and_says_unknown_when_empty():
    rows = [("N7AAA", "JA1AAA", "PM95", 14_074_000, NOW - 3_600, "Japan")]
    out = cond.grade(cond.parse_pskreporter(_xml(rows)), "CN87", now=NOW)
    assert all(o.level == cond.UNKNOWN for o in out.values())


def test_pskreporter_url_uses_a_safe_grid():
    assert "receiverCallsign=CN87" in cond.pskreporter_url("cn87mm")
    assert "receiverCallsign=CN87" in cond.pskreporter_url("")            # Seattle by default
    assert "receiverCallsign=CN87" in cond.pskreporter_url("&evil=1")
    assert "receiverCallsign=FN31" in cond.pskreporter_url("FN31pr")
    assert "flowStartSeconds=-900" in cond.pskreporter_url("CN87")


def test_parse_kp():
    data = b'[{"time_tag":"2026-10-12T02:35:00","kp_index":2,"estimated_kp":1.67},' \
           b'{"time_tag":"2026-10-12T02:36:00","kp_index":2,"estimated_kp":2.33}]'
    assert cond.parse_kp(data) == pytest.approx(2.33)
    assert cond.parse_kp(b"{}") is None
    assert cond.parse_kp(b'[{"estimated_kp": null}]') is None


def test_sun_elevation_seattle():
    # Seattle near local noon at the June solstice: about 66 degrees.
    noon = calendar.timegm(time.strptime("2026-06-21 20:10", "%Y-%m-%d %H:%M"))
    assert cond.sun_elevation(47.6, -122.3, noon) == pytest.approx(66, abs=2)
    midnight = noon + 12 * 3600
    assert cond.sun_elevation(47.6, -122.3, midnight) < -15
    assert cond.daylight("CN87", noon) == "day" and cond.daylight("CN87", midnight) == "night"


def test_summary_sentences():
    rows = [("N7AAA", f"W{i}AAA", "DM79", 14_074_000 + i, NOW - 60, "United States") for i in range(6)]
    rows += [("N7AAA", "JA1AAA", "PM95", 14_075_000, NOW - 60, "Japan")]
    out = cond.grade(cond.parse_pskreporter(_xml(rows)), "CN87", now=NOW)
    head, ctx = cond.summary(out, B["20m"], "CN87mm", 2.0, "night")
    assert head == "20 m is open: 7 stations heard near CN87 in the last 15 minutes, as far as Japan."
    assert ctx == "Quiet geomagnetic field (Kp 2) · Night"
    head, _ = cond.summary(out, B["40m"], "CN87", None, "day")
    assert head == "40 m is quiet near CN87. Best now: 20 m."
    head, ctx = cond.summary(None, B["40m"], "", 6.0, "day")
    assert head.startswith("Checking") and "storm" in ctx


def test_mode_follows_the_detection_kind():
    voice = make_plan(B["40m"], Mode.LSB, "General")
    assert voice.mode_for("cw") is Mode.CW and voice.mode_for("voice") is Mode.LSB
    cw = make_plan(B["20m"], Mode.CW, "General")
    assert cw.mode_for("cw") is Mode.CW and cw.mode_for("voice") is Mode.USB


def test_heard_replaces_a_clip_once_it_is_old():
    from kx3rig.smartscan.heard import CLIP_REFRESH_S

    h = HeardList()
    h.add(14_230_000, "voice", Mode.USB, 15, -6, now=100, clip=np.ones(5, np.float32))
    e = h.add(14_230_000, "voice", Mode.USB, 5, -20, now=200, clip=np.zeros(5, np.float32))
    assert e.clip[0] == 1.0 and e.clip_at == 100          # weaker and still fresh: kept
    later = 100 + CLIP_REFRESH_S
    e = h.add(14_230_000, "voice", Mode.USB, 5, -20, now=later, clip=np.zeros(5, np.float32))
    assert e.clip[0] == 0.0 and e.clip_at == later and e.snr_db == 15
