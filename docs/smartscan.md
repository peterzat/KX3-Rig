# Smartscan

Smartscan sweeps the band the radio is on, finds stations, keeps a short recording of each one,
and shows which bands are open from your location. It never transmits.

![Smartscan sweeping 20 meters in demo mode](screenshots/scan-dark.png)

## Using it

Press **Smartscan** on the Radio view. If the loop isn't tuned for the band,
[Loop Tune](looptune.md) opens first and starts the sweep when you finish. Within a second or
two:

- **The band buttons get a dot.** Green means open, amber means some activity, gray means quiet.
  Hover over a band button for the reason, for example "20 m: Open. 125 stations heard by 25 near
  CN87 in the last 15 minutes, as far as Angola." The sentence above the waterfall says the same
  thing for your band, and points elsewhere when another band is better.
- **The radio sweeps the band.** In LSB or USB it hunts voice in your license class's phone
  segment. In CW it hunts CW below the digital sub-bands. From DATA, AM, or FM it switches to the
  band's voice sideband. The status line shows how long a sweep takes.
- **The waterfall outlines what it finds** ("Voice", "CW") as it scrolls past.
- **The band view under the waterfall shows the whole sweep.** It shows where the receiver is
  listening, the calling frequencies (small ticks), every station heard (brighter when recent),
  and a faint curve of how well the antenna hears each part of the band.
- **The heard list keeps each station for 15 minutes.** Press the play button to hear the few
  seconds that made Smartscan stop there. Press **Tune** or click the row to stop and listen.

**Stop** (or Esc) puts the radio back where it was. Tuning the radio yourself, changing band or
mode, or transmitting stops the sweep and leaves the radio where you put it. Transmit is locked
while it sweeps, because the dial moves every second.

## How it works

**The sweep.** The KX3's PHONES output carries a 300-2800 Hz audio window beside the dial. Each
step moves the dial 2.4 kHz, so consecutive windows overlap slightly and together cover the
segment. A step tunes the radio (a verified SET), skips 0.25 s while the synthesizer, AGC, and
audio pipeline settle, then listens for 0.6 s. If nothing could be a station, it moves on. If
something could be, it listens to 1.5 s to confirm, or to 5 s when the heard list needs a
clip of that station. A quiet step takes about 0.9 s. The 20 m General phone segment
(14.225-14.350 MHz) is 53 steps, so one sweep takes about a minute, longer when there is a
lot to record. CW is swept in USB with the voice filter, so one step covers dozens of CW channels,
and the radio switches to CW only when you tune to a station.

**Where people gather.** Calling frequencies (QRP calling on every band, the AM calling
frequencies, 50.125 SSB calling) get a dial position of their own. The sweep revisits one after
every six steps, so a CQ there is caught within seconds instead of once a sweep. Stations heard
on one are labeled ("QRP calling"). SSTV frequencies are labeled and sorted last: pictures, not
a conversation.

**Finding stations** (`smartscan/detect.py`). Each dwell becomes a short-time spectrum (11.7 Hz
bins, 23 frames per second) and is compared with the noise floor, estimated per bin from the
quiet moments and smoothed across the passband.

- **CW** is a narrow region that switches on and off.
- **A carrier** is narrow and steady. It is shown, but never offered as a contact.
- **Voice** is found per 200 Hz chunk: summing a chunk's bins makes noise steady to about a
  decibel, so a voice that lifts several adjacent chunks a few decibels and rises and falls with
  syllables stands out even when no single bin does. The first version looked for voice bin by
  bin and fired on plain noise; the tests on synthetic audio caught that before it reached the
  radio.

**Where to tune.** For CW, on the signal. For SSB, the suppressed carrier sits about 300 Hz
outside the voice's edge nearest the dial, snapped to a whole kHz when close to one (most SSB
stations sit on round frequencies).

**Is the band open?** (`smartscan/conditions.py`). Every 5 minutes while Smartscan is on,
KX3-Rig asks [PSKReporter](https://pskreporter.info) for every reception report made by
stations in your grid square during the last 15 minutes. It sends only your 4-character grid
from Preferences (CN87, Seattle, until one is set), never your callsign or email. A band where
nearby receivers heard 5 or more stations, or a couple from 3000 km or more, is open. One where
they heard fewer is "some activity". One where they heard none, while other bands have reports,
is quiet. It is a direct measurement of what antennas near you are hearing right now, mostly on
FT8. NOAA's planetary K index (every 15 minutes) and the sun's elevation over your grid (day,
night, greyline) add context without overriding the measurement. Demo mode makes up an outlook
and never goes online.

## Design decisions

- **Whole segment, not just near where the loop is tuned.** A sweep takes about a minute on 20 m.
  The band view's noise curve shows where the AlexLoop hears poorly, so a quiet edge is not
  mistaken for a dead band.
- **Follow the mode.** Voice in a voice mode, CW in CW. No setting.
- **HF first, 2 m later.** See below.
- **No contact email to PSKReporter.** Queries stay anonymous and are rate-limited to their
  stated limit (no more than one every five minutes).
- **Location is the Preferences grid square**, defaulting to Seattle's CN87. Grid squares are
  what propagation data is keyed on, so a separate city or call-district setting would add a
  knob and nothing more.

## Other antennas

The AlexLoop is the primary antenna and nothing is tuned for anything else. A dipole or long
wire works with Smartscan unchanged. The band view's noise curve just comes out flat (no
loop resonance), which is informative in itself. Two behaviors assume the loop:

- Changing band stops the sweep and offers [Loop Tune](looptune.md), which starts the sweep
  again when the loop is tuned. Starting Smartscan on a band the loop is not tuned for opens
  Loop Tune first.
- The band view's tooltip explains a noise drop as "the antenna hears less here".

If a wire antenna becomes a regular, the smallest useful change is an **Antenna** preference
(Loop or Wire). With Wire, Smartscan would follow a band change instead of stopping and would
drop the loop wording. It is not built, to keep the app simple until it is needed.

## 2 m (not yet)

This KX3 reports a 2 m or 4 m module: `X` in its `OM` reply (Programmer's Reference p.21). The
FA command can tune it directly (120-168 MHz, firmware 2.15 notes). 2 m activity is FM: simplex
channels and repeater outputs. Detecting it means watching for receiver quieting, not
syllables, and sweeping a channel list, not a segment. It needs an allow-list review for
transverter band numbers (BN16-24), a 2 m entry in the band plan, and the module's own antenna
jack. It is a clean follow-up once HF Smartscan has been checked on the air.

## To verify on the radio

Everything above runs against the KX3 emulator and the demo band, a simulated magnetic loop
with voice and CW stations at real frequencies. The live checks are in
[live-test.md](live-test.md) section 5:

- step timing over the real link
- whether FA changes click or mute
- how AGC shapes the noise curve
- detector thresholds on real band noise and real SSB
- how close Tune lands on an SSB station
- where a CW station sounds after Tune

## How it was built

Smartscan was built in one Claude Code session (Opus 5.5) from a few paragraphs of intent, with
no radio attached. The process is the point as much as the feature.

1. **Read before designing.** The agent read the controller, CAT allow-list, waterfall, audio
   streams, and band plan, so the feature reuses the verified-SET radio link, the transmit
   policy, and the demo emulator instead of building beside them.
2. **Research in parallel, from sources.** Three background agents ran at once:
   - **Propagation data.** One fetched the candidate services live. PSKReporter's CN87 query
     returned 1500 reports from 41 local receivers in about a second (40 m and 20 m busiest, 15
     m reaching only Australia and New Zealand). HamQSL turned out to be a global calculation
     with hourly-only terms, and DX cluster spots were too sparse from the Pacific Northwest.
   - **Elecraft documents.** One read the Programmer's Reference, Owner's Manual, firmware
     notes, and the KX3-2M manual. It found the 2 m module flag in this radio's own `OM`
     reply, that FA reaches 2 m directly, and that the KX3's built-in SCAN is reachable only
     through switch emulation, which KX3-Rig refuses to send. It also found AlexLoop bandwidth
     measurements, since alexloop.com is now a parked domain.
   - **WSJT-X Improved.** One reviewed the fork for ideas. Nothing applied to Smartscan, so it
     went to the backlog.
3. **Ask only what is the operator's to decide.** Four questions (sweep range, what to hunt, 2 m,
   contact email), each with a recommendation. The operator overrode one (whole segment) and the
   design followed.
4. **Prototype the risky part first, against tests.** The detector was built against synthetic
   voice, CW, carriers, and noise over many random seeds before any UI existed.
5. **Change course mid-flight.** "Smartscan should know where people typically are" arrived
   halfway through. Calling frequencies were sourced (ARRL band plan, two QRP lists that
   agree), and became revisits and labels rather than a new setting.
6. **Make the demo honest.** The demo band simulates the loop's narrow response, using the
   measured AlexLoop bandwidths. That realism made a test flaky (a station 200 kHz from the
   loop's tuning really is 20 dB down), and the test was fixed to peak the simulated loop, as
   an operator would.
7. **Look at it.** Screenshots of the running demo caught a rendering bug the tests could not:
   a PyGObject struct freed too early, so the station marks never drew.

The ingredients that made this work are in the repo: sourced radio facts in
[references.md](references.md), safety rules and conventions in [CLAUDE.md](../CLAUDE.md), an
emulator good enough to run the whole app, and the
[zat.env](https://github.com/peterzat/zat.env) development setup (spec, code review, and
security review skills).
