import pytest

from kx3rig import bandplan
from kx3rig.bandplan import BY_NAME, band_for, nearest_band, tx_check
from kx3rig.cat import Mode


def test_band_lookup():
    assert band_for(14_074_000).name == "20m"
    assert band_for(7_200_000).name == "40m"
    assert band_for(15_000_000) is None
    assert nearest_band(14_400_000).name == "20m"


def test_band_numbers_match_kx3_bn_table():
    assert [b.number for b in bandplan.BANDS] == list(range(11))


def test_voice_sideband_convention():
    assert BY_NAME["40m"].voice_mode is Mode.LSB
    assert BY_NAME["20m"].voice_mode is Mode.USB
    assert BY_NAME["60m"].voice_mode is Mode.USB


def test_ft8_dials_are_inside_general_data_privileges():
    for band in bandplan.BANDS:
        if band.name == "60m":
            continue
        check = tx_check(band.ft8, Mode.DATA, "General", audio_low=1500, audio_high=1550)
        assert check.allowed, (band.name, check.reason)


@pytest.mark.parametrize("dial,mode", [
    (14_285_000, Mode.USB),     # 20 m QRP SSB
    (7_285_000, Mode.LSB),      # 40 m
    (3_985_000, Mode.LSB),
    (28_385_000, Mode.USB),
    (14_060_000, Mode.CW),
    (29_600_000, Mode.FM),
    (50_125_000, Mode.USB),
])
def test_general_allowed(dial, mode):
    assert tx_check(dial, mode, "General").allowed


@pytest.mark.parametrize("dial,mode,fragment", [
    (14_200_000, Mode.USB, "14.225"),          # Extra-only phone
    (7_150_000, Mode.LSB, "7.175"),            # Extra/Advanced phone
    (14_010_000, Mode.CW, "14.025"),           # Extra-only CW
    (10_120_000, Mode.USB, "no voice"),        # 30 m has no phone
    (28_500_000, Mode.FM, "29.0"),             # FM below 29 MHz
    (15_000_000, Mode.USB, "outside the amateur bands"),
    (5_357_000, Mode.DATA, "60 m"),
])
def test_general_blocked(dial, mode, fragment):
    check = tx_check(dial, mode, "General")
    assert not check.allowed
    assert fragment in check.reason


def test_sideband_must_stay_inside_segment():
    # LSB at 7.176 puts voice at 7.173-7.176, below the 7.175 edge.
    assert not tx_check(7_176_000, Mode.LSB, "General").allowed
    assert tx_check(7_178_000, Mode.LSB, "General").allowed
    # USB at the top of 20 m spills past 14.350.
    assert not tx_check(14_349_000, Mode.USB, "General").allowed
    assert tx_check(14_347_000, Mode.USB, "General").allowed


def test_extra_gets_more():
    assert tx_check(14_200_000, Mode.USB, "Extra").allowed
    assert tx_check(14_010_000, Mode.CW, "Extra").allowed


def test_technician_limits():
    assert not tx_check(14_074_000, Mode.DATA, "Technician", 1500, 1550).allowed
    assert tx_check(28_074_000, Mode.DATA, "Technician", 1500, 1550).allowed
    assert tx_check(28_400_000, Mode.USB, "Technician").allowed
    assert not tx_check(7_050_000, Mode.DATA, "Technician", 1500, 1550).allowed


def test_occupied_spans():
    assert bandplan.occupied(14_074_000, Mode.DATA, 1500, 1550) == (14_075_500, 14_075_550)
    assert bandplan.occupied(7_074_000, Mode.DATA_REV, 1500, 1550) == (7_072_450, 7_072_500)
    assert bandplan.occupied(7_200_000, Mode.LSB) == (7_197_000, 7_200_000)


def test_privilege_segments_for_band():
    segs = bandplan.privilege_segments(BY_NAME["20m"], "General")
    assert [(s.low, s.high) for s in segs] == [(14_025_000, 14_150_000), (14_225_000, 14_350_000)]


def test_unknown_license_class_is_most_restrictive():
    assert not tx_check(14_074_000, Mode.DATA, "Wizard", 1500, 1550).allowed
    assert tx_check(28_074_000, Mode.DATA, "Wizard", 1500, 1550).allowed


def test_software_cw_is_checked_as_cw():
    from kx3rig.bandplan import CW, tx_check
    from kx3rig.cat import Mode

    # A 700 Hz keyed tone in DATA on 14.2593: CW (J2A) is fine in the phone segment ...
    assert tx_check(14_259_300, Mode.DATA, "General", 650, 750, kind=CW).allowed
    # ... where a data signal is not.
    assert not tx_check(14_259_300, Mode.DATA, "General", 650, 750).allowed
