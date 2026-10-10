"""FT8 contact sequencing, following WSJT-X's auto-sequence rules.

Pure logic: feed it each period's decodes and ask what to send next. It never
starts a contact by itself. A human either calls CQ or answers a decode, and
when a contact completes, transmit is switched off (WSJT-X User Guide 10.3:
"every QSO must be initiated by a human operator").

Our messages:
    Tx1  DX ME GRID       answer a CQ
    Tx2  DX ME -12        report (after they answered our CQ)
    Tx3  DX ME R-12       roger + report
    Tx4  DX ME RR73       roger, 73
    Tx5  DX ME 73         sign-off
    Tx6  CQ ME GRID       call CQ

The contact is logged when we first send RR73 or 73, as WSJT-X does.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .messages import Message, format_report, same_call

MAX_REPEATS = 5        # same message without progress, then give up
MAX_CQ = 8             # CQ calls without an answer, then stop


class Stage(enum.Enum):
    IDLE = "idle"
    CALLING_CQ = "cq"          # sending Tx6
    ANSWERING = "answering"    # sending Tx1
    REPORT = "report"          # sending Tx2
    ROGER_REPORT = "roger"     # sending Tx3
    ROGERS = "rogers"          # sending Tx4 (RR73)
    SIGNOFF = "signoff"        # sending Tx5 (73)
    DONE = "done"


@dataclass
class Decode:
    """One decoded message from a period."""

    slot: int                  # period index: int(utc_seconds // 15)
    snr: int
    dt: float
    freq: int                  # audio offset of tone 0, Hz
    text: str
    message: Message
    low_confidence: bool = False

    @property
    def even(self) -> bool:
        return self.slot % 2 == 0


@dataclass
class Contact:
    call: str
    grid: str = ""
    their_freq: int = 0
    report_sent: int | None = None     # what we told them
    report_rcvd: int | None = None     # what they told us
    time_on: datetime | None = None
    time_off: datetime | None = None


@dataclass
class Sequencer:
    my_call: str
    my_grid4: str
    stage: Stage = Stage.IDLE
    contact: Contact | None = None
    tx_even: bool = False          # which period parity we transmit in
    repeats: int = 0
    logged: bool = False
    history: list[tuple[datetime, str]] = field(default_factory=list)
    _rr73_sent: bool = False
    _resend_rr73: bool = False

    # --- operator actions -----------------------------------------------------------

    def call_cq(self, tx_even: bool) -> None:
        self._reset()
        self.stage = Stage.CALLING_CQ
        self.tx_even = tx_even

    def answer(self, d: Decode) -> bool:
        """Answer a CQ (or reply to any station that sent a callsign)."""
        sender = d.message.de
        if not sender or sender == "<...>" or same_call(sender, self.my_call):
            return False
        self._reset()
        self.contact = Contact(call=sender.strip("<>"), grid=d.message.grid, their_freq=d.freq,
                               report_sent=d.snr)
        self.tx_even = not d.even
        msg = d.message
        if msg.addressed_to(self.my_call):
            # They called us directly: pick up the exchange where they are.
            self._advance_from(msg, d)
        else:
            self.stage = Stage.ANSWERING
        return True

    def halt(self) -> None:
        self._reset()

    # --- what to send --------------------------------------------------------------------

    def next_message(self) -> str | None:
        me, grid = self.my_call, self.my_grid4
        c = self.contact
        if self.stage is Stage.CALLING_CQ:
            return f"CQ {me} {grid}"
        if c is None:
            return None
        dx = c.call
        if self.stage is Stage.ANSWERING:
            return f"{dx} {me} {grid}"
        if self.stage is Stage.REPORT:
            return f"{dx} {me} {format_report(c.report_sent or 0)}"
        if self.stage is Stage.ROGER_REPORT:
            return f"{dx} {me} R{format_report(c.report_sent or 0)}"
        if self.stage is Stage.ROGERS:
            # RR73 means "no reply needed": send it again only if they ask (repeat R-report).
            if self._rr73_sent and not self._resend_rr73:
                return None
            return f"{dx} {me} RR73"
        if self.stage is Stage.SIGNOFF:
            return f"{dx} {me} 73"
        return None

    @property
    def active(self) -> bool:
        return self.stage not in (Stage.IDLE, Stage.DONE)

    def sent(self, text: str, when: datetime | None = None) -> bool:
        """Record a transmission. Returns True when this send completes the contact
        (so the caller logs it): the first RR73 or 73 we send."""
        when = when or datetime.now(timezone.utc)
        self.history.append((when, text))
        self.repeats += 1
        c = self.contact
        if c is not None and c.time_on is None and self.stage in (Stage.REPORT, Stage.ROGER_REPORT):
            c.time_on = when
        if self.stage is Stage.ROGERS:
            self._rr73_sent = True
            self._resend_rr73 = False
        if c is not None and self.stage in (Stage.ROGERS, Stage.SIGNOFF) and not self.logged:
            self.logged = True
            c.time_off = when
            if c.time_on is None:
                c.time_on = when
            if self.stage is Stage.SIGNOFF:
                self.stage = Stage.DONE  # 73 sent: nothing more to say
            return True
        if self.stage is Stage.SIGNOFF:
            self.stage = Stage.DONE
        return False

    def should_give_up(self) -> bool:
        limit = MAX_CQ if self.stage is Stage.CALLING_CQ else MAX_REPEATS
        return self.active and self.repeats >= limit

    # --- receiving -----------------------------------------------------------------------

    def on_decodes(self, decodes: list[Decode]) -> None:
        """Process one period's decodes (from the period we were listening in)."""
        if not self.active:
            return
        to_me = [d for d in decodes if d.message.addressed_to(self.my_call)]
        if self.stage is Stage.CALLING_CQ:
            # Several answers: take the strongest, like picking the loudest caller.
            answers = [d for d in to_me if d.message.de and d.message.de != "<...>"]
            if not answers:
                return
            d = max(answers, key=lambda x: x.snr)
            self.contact = Contact(call=d.message.de.strip("<>"), grid=d.message.grid,
                                   their_freq=d.freq, report_sent=d.snr)
            self.repeats = 0
            self._advance_from(d.message, d)
            return
        c = self.contact
        mine = [d for d in to_me if c is not None and same_call(d.message.de, c.call)]
        if self.stage is Stage.ROGERS and self._rr73_sent:
            if any(d.message.roger_report is not None for d in mine):
                self._resend_rr73 = True      # they did not copy our RR73
            else:
                self.stage = Stage.DONE       # their 73, or silence: the contact is complete
            return
        if not mine:
            return
        d = mine[-1]
        if c.report_sent is None or self.stage in (Stage.ANSWERING, Stage.CALLING_CQ):
            c.report_sent = d.snr
        if d.message.grid and not c.grid:
            c.grid = d.message.grid
        c.their_freq = d.freq
        before = self.stage
        self._advance_from(d.message, d)
        if self.stage is not before:
            self.repeats = 0

    def _advance_from(self, msg: Message, d: Decode) -> None:
        c = self.contact
        if msg.grid and self.stage in (Stage.CALLING_CQ, Stage.IDLE):
            self.stage = Stage.REPORT
        elif msg.report is not None:
            c.report_rcvd = msg.report
            if self.stage in (Stage.CALLING_CQ, Stage.ANSWERING, Stage.IDLE, Stage.REPORT, Stage.ROGER_REPORT):
                self.stage = Stage.ROGER_REPORT
        elif msg.roger_report is not None:
            c.report_rcvd = msg.roger_report
            self.stage = Stage.ROGERS
        elif msg.rrr or msg.rr73:
            if self.stage in (Stage.ANSWERING, Stage.REPORT, Stage.ROGER_REPORT, Stage.IDLE, Stage.SIGNOFF):
                self.stage = Stage.SIGNOFF
        elif msg.seventy_three:
            if self.stage in (Stage.ANSWERING, Stage.REPORT, Stage.ROGER_REPORT):
                self.stage = Stage.SIGNOFF    # they signed off early: send our 73 and log
            elif self.stage in (Stage.ROGERS, Stage.SIGNOFF):
                self.stage = Stage.DONE
        elif msg.grid and self.stage is Stage.ANSWERING:
            pass  # they repeated their grid to someone; keep answering

    def _reset(self) -> None:
        self.stage = Stage.IDLE
        self.contact = None
        self.repeats = 0
        self.logged = False
        self.history = []
        self._rr73_sent = False
        self._resend_rr73 = False
