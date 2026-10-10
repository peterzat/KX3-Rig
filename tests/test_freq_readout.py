import pytest

from kx3rig.ui.freq_readout import format_groups, parse_entry, snap_step


def test_format_blanks_leading_zero():
    assert "".join(format_groups(7_074_000)) == " 7074000"
    assert "".join(format_groups(14_074_000)) == "14074000"
    assert "".join(format_groups(50_313_000)) == "50313000"


@pytest.mark.parametrize("text,hz", [
    ("14.074", 14_074_000),
    ("14074", 14_074_000),
    ("14074.5", 14_074_500),
    ("7.185.000", 7_185_000),
    ("7185 kHz", 7_185_000),
    ("28.4MHz", 28_400_000),
    ("14,074", 14_074_000),
    ("3985", 3_985_000),
])
def test_parse_entry(text, hz):
    assert parse_entry(text) == hz


@pytest.mark.parametrize("text", ["", "abc", "99999", "0.05", "1.2.3.4x"])
def test_parse_entry_rejects(text):
    assert parse_entry(text) is None


def test_snap_step():
    assert snap_step(14_074_000, 1, 1_000) == 14_075_000
    assert snap_step(14_074_300, 1, 1_000) == 14_075_000
    assert snap_step(14_074_300, -1, 1_000) == 14_074_000
    assert snap_step(14_074_000, -1, 1_000) == 14_073_000
    assert snap_step(14_074_000, 10, 100) == 14_075_000
