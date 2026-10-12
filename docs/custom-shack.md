# A Custom Ham Shack

KX3-Rig is a professional-looking GNOME app with an audience of one: an Elecraft KX3, a Digirig,
an AlexLoop, a General license, and a ThinkPad. The decoder is WSJT-X's, the CAT knowledge is Elecraft's and Hamlib's, and the tuning advice is
two decades of operators writing to mailing lists. What is new is that one operator can have
all of it shaped around exactly their station and their opinions, without writing the code by
hand.

This page records how two of those features were made in one Claude Code session, and why the
repo is set up to make that routine.

## The bitter lesson, applied to a radio

[The Bitter Lesson of Agentic Coding](https://agent-hypervisor.ai/posts/bitter-lesson-of-agentic-coding/)
argues that the durable skill is no longer hand-writing implementations. It is "carefully
defining what you want and letting the model figure out how to build it." Its methodology in
one line: "Define what done looks like. Let the model figure out how to get there. Build the
simplest harness that verifies the work."

This repo is that harness, for one radio:

- **What done looks like** is a few paragraphs of intent from the operator, plus the rules in
  [CLAUDE.md](../CLAUDE.md). Those rules are the parts that are not negotiable:
  - never key the radio without the operator
  - every CAT command passes an allow-list
  - radio facts come from a source read in the session
  - listening audio never reaches the Digirig
- **The verification** is an emulator that runs the whole app against the real link code:
  - `fakeradio.py` speaks the CAT protocol
  - `demo.py` synthesizes a band of voice and CW stations heard through a simulated magnetic
    loop
  - a test suite runs with no radio attached
  - screenshot plans render every view for review
  - a pre-push gate runs code review
- **The model figures out the rest**: the research, the design tradeoffs, the code, and the
  tests.

Repurposing it is the same move. A different radio, antenna, license, or set of UI opinions
means a different few paragraphs of intent. The harness stays.

## Smartscan

The ask: a toggle on the Radio view that sweeps the likely parts of the band within the radio's,
the loop's, and the license's limits. It should highlight what it finds, show which bands are
open right now, list recently heard stations with quick tune and a replayable clip of each,
and need no configuration. The full story is in [smartscan.md](smartscan.md#how-it-was-built). In
short:

- **Parallel research from live sources.** Background agents fetched the candidate
  propagation services and read the Elecraft documents. One found, in this radio's own `OM`
  reply, that it has a 2 m module.
- **Four questions** went to the operator, the only decisions that were theirs to make. The
  rest followed from the rules and the sources.
- **The detector came first,** built against synthetic audio before any UI. Its first version
  fired on plain noise; the tests caught it.
- **A mid-build request** ("know where people typically are") became calling-frequency
  revisits and labels, from the ARRL band plan and two QRP lists, not a new setting.

## Loop Tune

The ask was this:

- "My default really is the AlexLoop. Add a simple guided way to properly use it."
- Research the conflicting advice: some say to key the mic at a particular time, and some
  operators get good results with the KX3's internal tuner.
- Record what's best.
- Nudge me, subtly but visibly, when a band change or other action means the loop needs
  attention.
- Make it easy to reach from Smartscan.

What happened:

1. **Two research agents ran at once.**
   - **Elecraft documents.** One read the Owner's Manual, errata, Programmer's Reference,
     KXAT3 instructions, and firmware notes for everything about TUNE, the ATU, and the CAT
     interface.
   - **Operator experience.** The other read the manufacturer's pages from the Wayback Machine
     (alexloop.com is a parked domain), AD5X's review, and about twenty operators' reports on
     the Elecraft list, QRPer, and AmateurRadio.com.
2. **The sources disagreed, and the disagreement was settled on evidence.**
   - Everyone, the manufacturer included, peaks receive noise first.
   - The manufacturer's procedure then keys a steady carrier and tunes for the brightest LED
     and lowest SWR. That is the "key the mic at a particular time" step.
   - On the ATU, the better-supported side is to keep it in bypass. A loop is its own matching
     network, and an ATU can make a mistuned loop look perfect to the radio while it heats.
   - The guide uses the ATU only as a last resort. Every source is cited in
     [references.md](references.md#loop-tune-looptune), and the reasoning is in
     [looptune.md](looptune.md).
3. **A premise was corrected.** The request assumed holding ATU TUNE; the manual says it is a
   tap (the hold function is ANT).
4. **The safety rules shaped the design.**
   - The rule that the radio is never keyed without the operator led to the plainest answer:
     the guide asks the operator to hold XMIT on the KX3. The app watches power and SWR and
     never transmits. No switch emulation was added to the allow-list.
   - The rule against menu writes meant the guide asks for the two settings (TUN PWR 1 W,
     ATU MD BYP) instead of setting them.
5. **The grounding rule caught a mistake.** The first draft of the menu instructions said VFO A
   picks the entry and VFO B changes it. The Owner's Manual, checked before committing, says
   the opposite. This is the class of error that CLAUDE.md's "ground hardware claims; do not
   recall them" exists for.
6. **The emulator grew to match.**
   - The KX3 emulator gained front-panel TUNE at TUN PWR.
   - The simulated loop gained an SWR curve fitted to the measured 2:1 bandwidths.
   - Demo mode gained a pretend tuning knob.
   - The whole guide now runs, and is tested, without a radio, including the receive-noise
     meter finding a real peak in synthetic band noise.
7. **The reminders are subtle by design.**
   - The Loop tag under the frequency goes from a quiet "Loop Tuned" to amber when the dial
     leaves the loop's usable width.
   - A band change offers the guide in a notification.
   - Smartscan on an untuned band opens the guide and starts the sweep when it is done.
   - The transmit confirmation says how far off the loop is.
   - Nothing is ever locked: a wire antenna works as before.
8. **Screenshots of the running demo** were reviewed page by page before the work was
   committed.

## Five more modes

The next ask was short:
- Take the best ideas from WSJT-X Improved.
- Add more digital modes.
- Do PSK31 and CW on the computer rather than with the KX3's built-in decoders, "for more
  control".
- Make every design and UI decision along the way.

What happened:

1. **Research ran in parallel.** One agent read WSJT-X Improved's release notes, features PDF,
   and user guide. Another read the WSJT-X source for FT4 and WSPR. A third read the KX3
   manuals, Part 97, the PSK31 spec, and fldigi.
2. **Two findings changed the plan.** WSJT-X builds FT4 and WSPR encoders but does not install
   them, so KX3-Rig had to encode both itself. And the KX3's ACC1 jack has no RTS or DTR, so
   computer-keyed CW could not use the serial line.
3. **The regulation settled the CW design.** 47 CFR 97.3(c)(1) counts a keyed tone in a sideband
   transmitter (J2A) as CW. So CW is a shaped tone in DATA mode, checked against CW privileges,
   and the allow-list's refusal of text keying stands.
4. **Separate pieces went to separate agents.** The PSK31 modem, CW modem, FT4 encoder, and WSPR
   encoder were each built by a forked agent, with its own tests, while the main session built
   the engines and views.
5. **Each port was checked against the original.** The FT4 encoder's LDPC code reproduces
   `ft8code`'s parity bits. The WSPR encoder matches WSJT-X's own C encoder, compiled and run
   for seven messages. The PSK31 and CW decoders read their own synthetic signals in noise.
6. **Safety rules kept up.** A station-wide rule now lets only one self-keying activity run at a
   time, the WSPR beacon stops by itself, and sharing spots online is off until the operator
   turns it on.

The design and sources are in [digital-modes.md](digital-modes.md).

## Everyone can have this

None of this is special to one operator except the choices. The pattern is:

- an emulator honest enough to develop against
- radio facts with sources
- safety rules the agent cannot argue with
- a short description of what you want

With those, the station you actually have gets software that fits it: your antenna's quirks,
your band plan, your license, your idea of a good interface. Fork the repo, change the intent,
and keep the harness. The development setup used here (spec, code review, and security review
skills, plus conventions) is [zat.env](https://github.com/peterzat/zat.env), driven from the
Claude Code CLI.
