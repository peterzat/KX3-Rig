import pytest

from kx3rig.ft8.messages import base_call, format_report, parse, same_call


def test_cq_plain():
    m = parse("CQ K9ABC FN42")
    assert m.is_cq and m.de == "K9ABC" and m.grid == "FN42" and not m.cq_modifier


@pytest.mark.parametrize("text,mod,call", [
    ("CQ DX K9ABC FN42", "DX", "K9ABC"),
    ("CQ POTA W7XYZ CN85", "POTA", "W7XYZ"),
    ("CQ POTA W7XYZ", "POTA", "W7XYZ"),
    ("CQ 123 K9ABC FN42", "123", "K9ABC"),
])
def test_cq_with_modifier(text, mod, call):
    m = parse(text)
    assert m.is_cq and m.cq_modifier == mod and m.de == call


def test_cq_nonstandard_call_without_grid():
    m = parse("CQ PJ4/K9ABC")
    assert m.is_cq and m.de == "PJ4/K9ABC" and m.grid == ""


@pytest.mark.parametrize("text,field,value", [
    ("K1ABC W1AW FN31", "grid", "FN31"),
    ("K1ABC W1AW -12", "report", -12),
    ("K1ABC W1AW +05", "report", 5),
    ("K1ABC W1AW R-08", "roger_report", -8),
    ("K1ABC W1AW RR73", "rr73", True),
    ("K1ABC W1AW RRR", "rrr", True),
    ("K1ABC W1AW 73", "seventy_three", True),
])
def test_exchange_messages(text, field, value):
    m = parse(text)
    assert m.to == "K1ABC" and m.de == "W1AW"
    assert getattr(m, field) == value
    assert m.addressed_to("K1ABC")
    assert not m.addressed_to("W1AW")


def test_rr73_is_not_a_grid():
    assert parse("K1ABC W1AW RR73").grid == ""


def test_hashed_and_portable_calls():
    m = parse("<W1AW> PJ4/K1ABC RR73")
    assert m.to == "<W1AW>" and m.rr73
    assert parse("K1ABC <...> -10").de == "<...>"
    assert base_call("PJ4/K9ABC") == "K9ABC"
    assert base_call("K9ABC/P") == "K9ABC"
    assert base_call("<K1ABC>") == "K1ABC"
    assert same_call("K1ABC/P", "k1abc")
    assert not same_call("<...>", "<...>")


@pytest.mark.parametrize("text", ["TNX BOB 73 GL", "HELLO", "", "K1ABC W1AW EXTRA"])
def test_free_text(text):
    assert parse(text).free_text


def test_format_report():
    assert format_report(-12) == "-12"
    assert format_report(5) == "+05"
    assert format_report(0) == "+00"
    assert format_report(-99) == "-50"
    assert format_report(60) == "+49"
