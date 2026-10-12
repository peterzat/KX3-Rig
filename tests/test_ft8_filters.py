from kx3rig.ft8.filters import DecodeFilter, doubtful, plausible_call
from kx3rig.ft8.messages import parse
from kx3rig.ft8.sequencer import Decode


def dec(text, snr=-10, low=False):
    return Decode(slot=1, snr=snr, dt=0.1, freq=1200, text=text, message=parse(text), low_confidence=low)


def test_plausible_calls():
    for call in ("K1ABC", "W7XYZ", "N0CALL", "JA1ABC", "VE7QRP", "2E0ABC", "PJ4/K1ABC", "K1ABC/P", "3DA0RU"):
        assert plausible_call(call), call
    for call in ("<...>", "1234", "ABCDEF", "K1ABC/P/R", ""):
        assert not plausible_call(call), call


def test_doubtful_decodes():
    assert doubtful(dec("CQ K1ABC FN42", low=True))
    assert not doubtful(dec("CQ K1ABC FN42", snr=-22))
    assert doubtful(dec("CQ 9Q1ZZZZZ JJ00", snr=-22))
    assert doubtful(dec("K1ABC <...> RR73", snr=-21))
    assert not doubtful(dec("K1ABC <...> RR73", snr=-12))   # strong: keep it


def test_filter_never_hides_messages_to_us():
    f = DecodeFilter(cq_only=True, hide_worked=True)
    worked = {("W1AW", "20m")}
    assert f.shows(dec("N0CALL W1AW -05"), "N0CALL", worked, "20m")
    assert not f.shows(dec("CQ W1AW FN31"), "N0CALL", worked, "20m")
    assert f.shows(dec("CQ W1AW FN31"), "N0CALL", worked, "40m")
    assert not f.shows(dec("K9XYZ W1AW -05"), "N0CALL", set(), "20m")
    f.hidden_calls.add("K7ZZZ")
    assert not f.shows(dec("CQ K7ZZZ DN07"), "N0CALL", set(), "20m")
