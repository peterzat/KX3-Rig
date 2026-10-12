from kx3rig.ft8.messages import parse
from kx3rig.ft8.sequencer import Decode, Sequencer, Stage

ME, GRID = "K1ABC", "FN42"


def dec(text, slot=100, snr=-10, freq=1200):
    return Decode(slot=slot, snr=snr, dt=0.1, freq=freq, text=text, message=parse(text))


def run_tx(seq):
    """Send whatever the sequencer wants; return (message, completed)."""
    msg = seq.next_message()
    done = seq.sent(msg) if msg else False
    return msg, done


def test_answer_a_cq_full_contact():
    s = Sequencer(ME, GRID)
    assert s.answer(dec("CQ W1AW FN31", slot=100, snr=-7))
    assert s.tx_even is False  # CQ heard in an even period: we answer in the odd one
    assert run_tx(s) == ("W1AW K1ABC FN42", False)
    s.on_decodes([dec("K1ABC W1AW -12", snr=-9), dec("CQ K9XYZ EN52")])
    assert s.stage is Stage.ROGER_REPORT
    assert run_tx(s) == ("W1AW K1ABC R-09", False)
    s.on_decodes([dec("K1ABC W1AW RR73")])
    msg, done = run_tx(s)
    assert (msg, done) == ("W1AW K1ABC 73", True)
    assert s.stage is Stage.DONE and not s.active
    c = s.contact
    assert (c.call, c.grid, c.report_sent, c.report_rcvd) == ("W1AW", "FN31", -9, -12)
    assert c.time_on is not None and c.time_off is not None


def test_parity_is_opposite_of_the_cq():
    s = Sequencer(ME, GRID)
    s.answer(dec("CQ W1AW FN31", slot=101))
    assert s.tx_even is True
    s.answer(dec("CQ W1AW FN31", slot=100))
    assert s.tx_even is False


def test_call_cq_full_contact_with_rr73():
    s = Sequencer(ME, GRID)
    s.call_cq(tx_even=True)
    assert run_tx(s) == ("CQ K1ABC FN42", False)
    s.on_decodes([])
    assert run_tx(s) == ("CQ K1ABC FN42", False)
    s.on_decodes([dec("K1ABC K9ABC FN42", snr=-15), dec("K1ABC N0XYZ EM48", snr=-3)])
    assert s.contact.call == "N0XYZ"  # the stronger caller
    assert run_tx(s) == ("N0XYZ K1ABC -03", False)
    s.on_decodes([dec("K1ABC N0XYZ R-11")])
    msg, done = run_tx(s)
    assert (msg, done) == ("N0XYZ K1ABC RR73", True)   # logged at first RR73
    assert s.contact.report_rcvd == -11
    s.on_decodes([dec("K1ABC N0XYZ 73")])
    assert s.stage is Stage.DONE


def test_rr73_resent_only_when_they_repeat_roger():
    s = Sequencer(ME, GRID)
    s.call_cq(tx_even=True)
    run_tx(s)
    s.on_decodes([dec("K1ABC N0XYZ EM48")])
    run_tx(s)
    s.on_decodes([dec("K1ABC N0XYZ R-11")])
    assert run_tx(s)[1] is True
    s.on_decodes([dec("K1ABC N0XYZ R-11")])  # they missed our RR73
    assert s.next_message() == "N0XYZ K1ABC RR73"
    assert s.sent("N0XYZ K1ABC RR73") is False   # already logged
    s.on_decodes([])
    assert s.stage is Stage.DONE


def test_silence_after_rr73_completes():
    s = Sequencer(ME, GRID)
    s.call_cq(tx_even=True)
    run_tx(s)
    s.on_decodes([dec("K1ABC N0XYZ R-11")])  # they skipped straight to roger
    assert s.stage is Stage.ROGERS
    assert run_tx(s)[1] is True
    s.on_decodes([])
    assert s.stage is Stage.DONE


def test_caller_skips_grid_and_sends_report():
    s = Sequencer(ME, GRID)
    s.call_cq(tx_even=False)
    run_tx(s)
    s.on_decodes([dec("K1ABC W1AW -05", snr=-14)])
    assert run_tx(s) == ("W1AW K1ABC R-14", False)


def test_ignores_other_stations_and_gives_up():
    s = Sequencer(ME, GRID)
    s.answer(dec("CQ W1AW FN31"))
    for _ in range(5):
        run_tx(s)
        s.on_decodes([dec("K9XYZ W1AW -12"), dec("K1ABC N0ABC -01")])
    assert s.stage is Stage.ANSWERING
    assert s.should_give_up()


def test_cq_gives_up_after_limit():
    s = Sequencer(ME, GRID)
    s.call_cq(tx_even=True)
    for _ in range(8):
        run_tx(s)
        s.on_decodes([])
    assert s.should_give_up()


def test_answering_a_direct_call():
    s = Sequencer(ME, GRID)
    assert s.answer(dec("K1ABC W1AW FN31", snr=-4))
    assert s.next_message() == "W1AW K1ABC -04"


def test_cannot_answer_self_or_unknown():
    s = Sequencer(ME, GRID)
    assert not s.answer(dec("CQ K1ABC FN42"))
    assert not s.answer(dec("CQ <...>"))
    assert not s.active


def test_early_73_from_them():
    s = Sequencer(ME, GRID)
    s.answer(dec("CQ W1AW FN31"))
    run_tx(s)
    s.on_decodes([dec("K1ABC W1AW -12")])
    run_tx(s)
    s.on_decodes([dec("K1ABC W1AW 73")])
    assert run_tx(s) == ("W1AW K1ABC 73", True)


def test_halt():
    s = Sequencer(ME, GRID)
    s.call_cq(tx_even=True)
    s.halt()
    assert s.next_message() is None and not s.active


def test_engine_ignores_completion_from_a_replaced_sequencer(tmp_path, monkeypatch):
    """A transmission still playing when the operator answers someone else must
    not be credited to the new contact (it would log early and skip RR73)."""
    from types import SimpleNamespace

    from kx3rig import config
    from kx3rig.ft8.engine import Ft8Engine

    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    station = SimpleNamespace(settings=config.Settings(callsign=ME, grid=GRID), stop_data_tx=lambda: None)
    engine = Ft8Engine(station)
    old = engine.sequencer
    old.call_cq(tx_even=True)
    engine.transmitting_text = "CQ K1ABC FN42"
    new = Sequencer(ME, GRID)
    assert new.answer(dec("K1ABC N0XYZ R-11"))
    assert new.stage is Stage.ROGERS
    engine.sequencer = new
    logged = []
    engine.connect("logged", lambda _e, entry: logged.append(entry))
    engine._tx_done(old, "CQ K1ABC FN42")
    assert engine.transmitting_text == ""
    assert not logged
    assert new.stage is Stage.ROGERS
    assert new.next_message() == "N0XYZ K1ABC RR73"


def _fade(s):
    """Send until the sequencer runs out of repeats with no reply."""
    while not s.should_give_up():
        run_tx(s)
        s.on_decodes([])


def test_a_faded_contact_waits_then_resumes_when_they_answer():
    s = Sequencer(ME, GRID)
    s.answer(dec("CQ W1AW FN31", slot=100))
    run_tx(s)
    s.on_decodes([dec("K1ABC W1AW -12")])
    assert s.stage is Stage.ROGER_REPORT
    _fade(s)
    assert s.can_wait()
    s.start_waiting(slot=120)
    assert s.waiting and s.active and s.next_message() is None
    assert s.on_waiting_decodes([dec("CQ K9XYZ EN52", slot=121)]) == ""
    # They come back in the other parity, still asking for our roger.
    assert s.on_waiting_decodes([dec("K1ABC W1AW -12", slot=123)]) == "reply"
    assert not s.waiting and s.tx_even is True
    assert s.next_message() == "W1AW K1ABC R-10"


def test_a_faded_station_calling_cq_gets_a_few_more_calls():
    s = Sequencer(ME, GRID)
    s.answer(dec("CQ W1AW FN31", slot=100))
    _fade(s)
    s.start_waiting(slot=110)
    assert s.on_waiting_decodes([dec("CQ W1AW FN31", slot=112)]) == "call"
    assert s.stage is Stage.ANSWERING and s.next_message() == "W1AW K1ABC FN42"
    sends = 0
    while not s.should_give_up():
        run_tx(s)
        s.on_decodes([])
        sends += 1
    assert sends == 3


def test_waiting_expires_and_is_limited():
    s = Sequencer(ME, GRID)
    s.answer(dec("CQ W1AW FN31", slot=100))
    _fade(s)
    s.start_waiting(slot=110, periods=4)
    assert not s.wait_expired(114) and s.wait_expired(115)
    s.wait_until = None
    s.start_waiting(slot=120)
    s.wait_until = None
    assert not s.can_wait()          # two waits per contact
    s.halt()
    assert not s.waiting and s.waits == 0


def test_cq_and_signoff_never_wait():
    s = Sequencer(ME, GRID)
    s.call_cq(tx_even=True)
    assert not s.can_wait()
