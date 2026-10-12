# References

Sourced facts behind KX3-Rig's radio behavior. Every entry cites where it came from; the linked
source wins on any conflict. Items marked **UNVERIFIED** were not settled by the documents and
need a live check on the radio (see the list at the end). Station facts verified on this machine
during the earlier bring-up live in the station's (private) KX3-Digirig-Ubuntu notes.

Source keys:

- **PR**: Elecraft *K3S/K3/KX3/KX2 Programmer's Reference*, rev G5 (2019-02-20), the newest on
  the Elecraft KX3 manuals page as of 2026-10. https://ftp.elecraft.com/KX2/Manuals%20Downloads/K3S%26K3%26KX3%26KX2%20Pgmrs%20Ref,%20G5.pdf
- **OM**: *KX3 Owner's Manual* rev C5, with errata C5-3/C5-4 and firmware release notes to MCU 3.02.
  https://ftp.elecraft.com/KX3/Manuals%20Downloads/E740163%20KX3%20Owner's%20man%20Rev%20C5.pdf
- **HL**: Hamlib 4.5.5 source (`rigs/kenwood/k3.c`, `elecraft.c`, `kenwood.c`), the version installed
  here (rig model 2045).
- **CFR**: 47 CFR Part 97 (eCFR, current to 2026-10-06), cross-checked against the ARRL band chart.
- **WSJT**: WSJT-X 3.0.x source and the installed 3.0.2 User Guide; the FT8/FT4 QEX paper
  (Franke, Somerville, Taylor).
- **FW**: KX3 firmware release notes, https://ftp.elecraft.com/KX3/firmware/ffwnotes.rtf (read
  2026-10-11).
- **2M**: *KX3-2M/4M Installation and Operation* rev D,
  https://ftp.elecraft.com/KX3/Manuals%20Downloads/E740247%20KX3-2M-4M%20Installation%20and%20Operation%20Rev%20D.pdf
- **BP**: ARRL band plan, https://www.arrl.org/band-plan (read 2026-10-11).
- **QRP**: QRP calling frequency lists at https://www.qsl.net/aa3sj/Pages/Freq.html and
  https://www.qsl.net/wb6dwd/QRPFrequencies.htm (they agree; neither names a publisher).
- **PSKR**: PSKReporter retrieval API, https://pskreporter.info/pskdev.html.
- **SWPC**: NOAA Space Weather Prediction Center JSON products, https://services.swpc.noaa.gov.
- **WSX**: WSJT-X source, `git.code.sf.net/p/wsjt/wsjtx` master b4f9a43 (2025-02-04, the
  `wsjtx-2.7` branch); file and line numbers below refer to it. FT4 and WSPR changes in 3.0.2,
  if any, are **UNVERIFIED**.
- **WS**: WSJT-X Improved ("WS - Digital Mode Suite") by DG2YCB: release notes, the "additional
  features" PDF (2025-10-11), and the user guide, https://wsjt-x-improved.sourceforge.io (read
  2026-10-12). Its home page asks that any adapted function credit it with a link.
- **FL**: fldigi at commit 61b97f4, https://github.com/w1hkj/fldigi (`src/psk/pskvaricode.cxx`,
  `src/psk/psk.cxx`, `src/cw_rtty/cw.cxx`, `src/cw_rtty/morse.cxx`, `src/rigcontrol/rigsupport.cxx`).
- **G3PLX**: the PSK31 specification as published by the ARRL, https://www.arrl.org/psk31-spec.
- **ITU**: ITU-R M.1677-1, International Morse code.

## CAT protocol (cat.py, radio.py)

- Link: 38400 baud, 8 data bits, 2 stop bits, no handshake (station-verified). The KX3 `RS232`
  menu sets the radio's rate; there is no auto-baud. A mismatched rate makes the radio execute
  garbage as commands (station incident), so KX3-Rig never scans rates.
- Syntax: commands and replies end in `;`. A GET is the bare command (`FA;`); a SET carries data
  and returns nothing, so every SET is followed by its GET (PR p.3). `?;` means busy or not
  allowed now (PR p.3). Typical reply under 10 ms, worst case ~100 ms, band changes up to 500 ms
  (PR p.3); wait 300 ms after `BN` (PR p.8).
- Overrunning the radio's input buffer gives `ERR FW2 004` and needs a power cycle (OM p.48):
  one command outstanding at a time, polls every 200 ms in receive.
- Formats used:

| Command | Format | Source |
|---------|--------|--------|
| `FA` | `FA` + 11-digit Hz | PR p.11 |
| `IF` | 38 bytes: freq 2-12, RIT sign 18, offset 19-22, RIT 23, XIT 24, TX 28, mode 29, VFO 30, split 32 | PR p.14; matches HL |
| `MD` | 1 LSB, 2 USB, 3 CW, 4 FM, 5 AM, 6 DATA, 7 CW-REV, 9 DATA-REV | PR p.16 |
| `DT` | 0 DATA A, 1 AFSK A, 2 FSK D, 3 PSK D; set after `MD` | PR p.11; HL `k3_set_mode` |
| `BW` | 10 Hz units | PR p.8 |
| `PC` | basic `PCnnn` watts; K22 adds a range digit | PR p.22 |
| `PO` | output, tenths of a watt (KX3 only) | PR p.22 |
| `SW` | SWR x10, firmware 2.93+ | PR p.24, p.33 |
| `SM` | 0-15 in basic mode: S9 = 6, +20 = 9, +40 = 12, +60 = 15 | PR p.23; values below S9 from HL's table |
| `TQ` | 0 receive, 1 transmit | PR p.27 |
| `BN` | 00-10 = 160 m … 6 m, recalls that band's memory | PR p.8 |
| `OM` | product ID at offsets 13-14, `02` = KX3 | PR p.21 |
| `ID` | `ID017;` | PR p.14 |

- Meta state: Hamlib 4.5.5 sends `K22;` on every open and never restores it (HL `elecraft.c`), so
  after WSJT-X the radio is likely in K22. KX3-Rig reads `K2;`/`AI;`, sets `K20;`/`AI0;`, and
  restores the saved values on exit. K21/K23 corrupt mode readback (PR p.16).
- The allow-list (`cat.ALLOWED`) and where each entry is documented: GETs `ID` `OM` `RVM` `RVD`
  `IF` `TQ` `SM` `PO` `SW` `PC` `MD` `DT` `BW` `FA` `FB` `K2` `K3` `AI` `PS` `BN` (PR pp.7-27; all
  GETs whose only documented effect is a reply, and the ones Hamlib sends on every KX3 open,
  HL `elecraft_open`); SETs `FAnnnnnnnnnnn` (p.11), `MDn` (p.16), `DTn` (p.11), `BWnnnn` (p.8),
  `PCnnn` (p.22), `BN00`-`BN10` (p.8), `K2n`/`AIn` to restore the operator's state (pp.4, 7, 14),
  and `RX` (p.23, "terminates transmit in all modes"). Push-to-talk is the Digirig RTS line only;
  `TX;` is not on the list.
- Never sent (allow-list in `cat.py`): `TX`-capable switch emulation (`SWT16`, `SWH16` TUNE,
  `SWT44` ATU TUNE, `SWT11` message play, `SWH29` VOX), `KY` keying text, `PS0` (CAT cannot turn
  the radio back on), `BR` baud change, `MN`/`MP`/`MQ` menu access (no range checking; unlocks
  TX GAIN, bias, carrier null), `!`/`@` DSP commands, `UP`/`DN` (they edit an open menu value)
  (PR pp.2-28).
- pyserial 3.5 asserts RTS and DTR when a port opens. With RTS wired to the Digirig PTT a plain
  `Serial(port)` keys the radio. KX3-Rig builds the port unopened, clears RTS/DTR, then opens.
  **UNVERIFIED**: whether the cp210x driver pulses RTS during open; test into a dummy load.

## Cabling (ui/connect_page.py)

- Digirig Elecraft KX cable set (https://digirig.net/product/elecraft-kx-cables/): an audio cable
  from the Digirig's audio socket, split into a **red** plug (TX audio and PTT) for the KX3
  **MIC** jack and a **green** plug (RX audio) for **PHONES**; and a **black** serial cable from
  the Digirig's serial socket to **ACC1** (RS-232 CAT). The set needs a Digirig Mobile rev 1.6+
  configured for RS-232.
- KX3 left-side top row, left to right: `9-15 VDC` power barrel, **ACC1**, KEY, PHONES, MIC
  (OM p.9). ACC1 is the first 3.5 mm jack beside the power barrel; KEY sits next to it and is
  easy to mistake for it. Bottom row: ACC2, RX I/Q.
- Both points were confirmed on this station's KX3 during the earlier bring-up.

## Receive and transmit audio (audio.py, controller.py)

- Plugging into PHONES disables the internal speaker and its amplifier (OM p.5), so the operator
  hears nothing unless the app plays the radio's audio.
- PHONES is a 0.1 W/channel headphone driver after the AF gain control; there is no fixed line
  output (OM p.54, p.22). The Radio audio meter guides the AF gain setting.
- Transmit monitor audio also comes out of PHONES (OM p.12, p.14), so KX3-Rig mutes playback while
  transmitting to avoid echo and acoustic feedback.
- There is no LINE IN on the KX3; computer audio goes into the MIC jack for both data and voice
  (OM p.18; KX3 menu list pp.35-43). MIC BIAS is meant for the MH3 mic; Digirig users run it OFF
  (OM p.38; Digirig forum).
- DATA A is upper sideband by default and disables compression and TX/RX EQ; set mic gain for no
  more than 4-5 ALC bars; 5 W or less is recommended in data modes (OM p.18).
- SSB voice: set CMP to 0, raise mic gain until ALC reaches about the 5th bar, then add
  compression to taste; set power with PWR, never with mic gain (OM p.15; firmware 1.50 notes).
  AM and FM use the same path. FM deviation defaults to 5.0 kHz (OM p.38).
- Digirig discovery runs `pw-dump` in a separate process. An in-process GStreamer
  `DeviceMonitor` (PipeWire 1.0.5 provider) deadlocks on its second start once a `pipewiresrc` in
  the same process is streaming from the Digirig; that froze the window on first contact with the
  radio (2026-10-11).
- The KX3 blocks transmit outside ham bands ("BND END", OM p.44) but knows nothing about license
  classes, so KX3-Rig enforces sub-band privileges itself.
- Power: 10 W PEP 160-15 m, 8 W 12-6 m (OM p.54); PWR adjusts in 0.1 W steps to 1 W and 0.2 W
  above (firmware 0.89). The PR's per-band maximums conflict with the OM and Hamlib, so KX3-Rig
  reads back what the radio accepted rather than assuming a maximum.

## US privileges (bandplan.py)

General class, from CFR 97.301 and 97.305 (eCFR 2026-10-06), in MHz. CW is allowed throughout the
phone segments too (97.305(a)).

| Band | CW and data | Phone |
|------|-------------|-------|
| 160 m | 1.800-2.000 | 1.800-2.000 |
| 80 m | 3.525-3.600 | 3.800-4.000 |
| 40 m | 7.025-7.125 | 7.175-7.300 |
| 30 m | 10.100-10.150 | none |
| 20 m | 14.025-14.150 | 14.225-14.350 |
| 17 m | 18.068-18.110 | 18.110-18.168 |
| 15 m | 21.025-21.200 | 21.275-21.450 |
| 12 m | 24.890-24.930 | 24.930-24.990 |
| 10 m | 28.000-28.300 | 28.300-29.700 |
| 6 m | 50.0-50.1 CW only; 50.1-54.0 all | |

- Emissions must stay inside the segment (97.307(b)), so a sideband transmission is checked over
  its whole occupied width (about 3 kHz), not just the dial frequency.
- FM's modulation-index limit below 29.0 MHz (97.307(f)) effectively puts FM at 29.0-29.7 MHz and
  6 m.
- 60 m changed on 2026-02-13: four channels plus a 5351.5-5366.5 kHz segment at 9.15 W ERP, with a
  2.8 kHz limit (97.303(h), ARRL). KX3-Rig is receive-only on 60 m for now.
- Sideband convention: LSB on 160/80/40 m, USB elsewhere, USB on 60 m; digital modes use USB
  (OM p.10; WSJT User Guide 4.2).
- FT8 dial frequencies (USB, WSJT-X `FrequencyList.cpp`): 1.840, 3.573, 7.074, 10.136, 14.074,
  18.100, 21.074, 24.915, 28.074, 50.313 MHz. All are inside General data segments.

## Smartscan (smartscan/)

- The KX3's built-in SCAN (VFO A to VFO B; OM p.17) is started by holding FREQ ENT, which over
  CAT is only `SWH10` switch emulation (PR p.25, Table 8). KX3-Rig refuses switch emulation, so
  Smartscan steps the dial itself with `FA` (allow-listed). No settle time is documented for
  `FA` within a band (PR p.3 gives typical replies under 10 ms); Smartscan waits for the
  readback, then skips 0.25 s of audio. **UNVERIFIED**: whether `FA` steps click or mute.
- SSB receive bandwidth is about 2.8 kHz (OM p.22); Smartscan hears 300-2800 Hz audio per step
  and narrows its steps if `BW;` reports a narrower filter. Per-mode BW limits are not
  documented (PR p.8 says only "may be quantized and/or range limited").
- With AGC on, AF level changes are compressed (OM p.22), so the band view's noise curve
  understates how far a magnetic loop's response falls. **UNVERIFIED** on the radio.
- Scan ranges (BP), clipped to the class's privileges: voice in the phone portion below the 10 m
  AM window (29.0 MHz), and 50.1-50.3 MHz SSB on 6 m. CW from the band edge to below the
  RTTY/data and FT8 sub-bands (for example 14.000-14.070, 7.000-7.074 MHz). 30 m has no
  voice, so voice falls back to CW there. 60 m is not swept (channelized).
- Calling frequencies (`bandplan.HOT_SPOTS`): AM calling 3.885, 7.290, 14.286; SSTV 3.845,
  7.171, 14.230, 28.680; 6 m SSB calling 50.125 (BP). QRP CW 1.810, 3.560, 7.040, 10.106, 14.060,
  18.096, 21.060, 24.906, 28.060, 50.060; QRP SSB 1.910, 3.985, 7.285, 14.285, 18.130, 21.385,
  24.950, 28.885 (QRP).
- PSKReporter (PSKR): `GET /query?receiverCallsign=<grid4>&modify=grid&flowStartSeconds=-900&rronly=1&noactive=1`.
  "Users are encouraged to retrieve reception data no more often than once every five
  minutes"; Smartscan polls at that limit, only while on, with no `appcontact` (operator's
  choice). A live CN87 query (2026-10-12 02:40 UTC) returned 1500 reports from 41 receivers in
  1.2 s and about 500 KB; 1500 looks like a server cap (it covered the newest 11 of 15 minutes).
- SWPC: `json/planetary_k_index_1m.json` (`estimated_kp`), polled every 15 minutes. HamQSL's
  band table was not used: it is a global calculation from the indices, and its terms ask for
  hourly updates only (https://www.hamqsl.com/solar.html).
- AlexLoop bandwidth: alexloop.com is a parked domain. Coverage 7-30 MHz (retailer listing);
  "very high Q, you will need to re-tune with even fairly small frequency changes" (AD5X review,
  http://www.radiomanual.info/schemi/ACC_antenna/AlexLoop_review.pdf). Approximate 2:1 SWR
  bandwidth measured indoors by VE3WDM (https://amateurradio.com/the-bandwidth-on-the-alexloop):
  40 m 10 kHz, 30 m 15 kHz, 20 m 35 kHz, 15 m 50 kHz, 10 m 60 kHz. The demo uses these for its
  simulated loop.
- 2 m: the `X` module flag means a KX3-2M or KX3-4M (PR p.21; added in PR rev E12). Transverter
  bands are `BN16`-`BN24` (PR p.8); the module defaults to XV1 (2M p.3). `FA` enters 2 m directly
  from other bands, 120-168 MHz (FW, MCU 2.15). 2 m uses the module's own antenna jack (2M p.4).
  Not used yet.

## Loop Tune (looptune/)

Elecraft documents (OM, PR, FW above, plus **ERR**: OM errata C5-3 and C5-4,
https://ftp.elecraft.com/KX3/Manuals%20Downloads/; **KXAT3**: KXAT3 Installation Instructions
rev A1). Tap is the labeled function, hold (about half a second) the one below it (OM p.3).

- XMIT tap = transmit; hold = **TUNE**, "Transmit CW carrier at PWR level (or MENU:TUN PWR
  level, if lower)" (OM p.7, p.14). SWR shows on VFO A during TUNE (OM p.14); tap XMIT to leave
  TUNE (OM p.33). No TUNE time limit is documented.
- **TUN PWR** (MN058): NOR follows the PWR knob, otherwise a fixed 0-10 W for TUNE only. "TUN
  PWR does not pertain to ATU TUNE, which uses 2 or 3 W (KXAT3)" (OM p.41; FW 0.77: 2 W below
  9 V supply).
- **ATU TUNE** is a tap (hold is ANT, KXAT100 only). It needs ATU MD = AUTO. Matching "takes an
  average of 4 seconds, initially. Settings are then recalled instantly on band change, as well
  as when you transmit after moving the VFO a significant distance" (OM p.14). The KXAT3 stores
  matches "at multiple points across each band" (KXAT3 p.1), in two data sets since MCU 2.76
  (ERR). It is an 8L/8C L-network, rated 15 W, under 0.5 dB loss in bypass 160-10 m (OM
  p.50, p.54).
- **ATU MD** (MN023): BYP or AUTO, set in the menu only (OM p.36). Tapping CLR in ATU MD clears
  the band's stored data (OM p.36; ERR).
- Menu use: hold MENU; OFS/VFO B scrolls entries; VFO A changes the value; hold MENU to exit
  (OM p.9).
- High SWR: "the KX3 reduces power if SWR is high" and may drop out of transmit (OM p.6, p.45).
- CAT: no command starts TUNE or ATU TUNE except switch emulation (`SWH16` TUNE, `SWT44` ATU
  TUNE; PR p.25, p.5), which KX3-Rig refuses. `SW` reads SWR "during transmit, TUNE, and during
  ATU tuning" (PR p.24). The PR's change list says firmware 2.93 (p.33); the public release
  notes list the SWR read command under MCU 2.95. Either way this radio's 2.38 lacks it. `PO`
  is "estimated from the KX3's or KX2's drive level" (PR p.22). `TQ1` is documented for PTT
  and pseudo-transmit; **UNVERIFIED** for front-panel TUNE (KX3-Rig sees transmit through the
  `IF` TX flag or `TQ`). `AK` (ATU relay bitmaps) cannot tell BYP from AUTO (PR p.7), so
  KX3-Rig does not read the ATU state.
- Nothing in Elecraft's documents mentions magnetic loops.

AlexLoop (PY1AHD). alexloop.com is parked; pages were read from the Wayback Machine:

- Coverage 6.95-29.7 MHz (kit page, web.archive.org/web/20100224225743/http://alexloop.com:80/instructions.html);
  HamPack "From 7 MHz to 30 MHz", "Maximum Power: 25 Watts SSB; 10 Watts AM / FM / CW / Digital
  Modes", and "The built in AlexTune will make the LED shine according the best tuning point"
  (web.archive.org/web/20241015174135/http://alexloop.com/alexloop-hampack-system-artigo44.html).
  Walkham retail listings: 7-30 MHz, 20 W SSB, 10 W AM/FM/CW (GigaParts).
- The manufacturer's tuning procedure (RC-2 page, web.archive.org/web/20250623054313/http://alexloop.com/artigo45.html):
  "Sudden increase of the band noise indicates that the operator is near the best tuning
  point." Then select a continuous carrier mode, key it, and "turn the tuning knob right and
  left until the LED shines the brightest. The transceiver will now show the lowest SWR."
- Use about 1 m above ground with the knob in reach; no radials
  (web.archive.org/web/20101025081152/http://alexloop.com/instructions2.html).
- One split-stator capacitor on a reduction drive covers the range in about 270 degrees (AD5X
  review, above). The LED is an RF field indicator, lit only in transmit, dimmer on lower
  bands (Passion Radio AlexTune page, https://www.passion-radio.com/tuners/alex-tune-2634.html).
- Bandwidth: VE3WDM's 2:1 figures (above) are the table in `looptune/state.py`. Sotabeams
  measured 12/16/24 kHz on 40/30/20 m outdoors (https://www.sotabeams.co.uk/blog/alex-loop-measurements/);
  operators report retuning after about 5 kHz on 40 m (K6DGW) and 20 kHz on 20 m (VE3WDM).
  17 m and 12 m are interpolated.
- ATU with the loop, against: K6DGW ("No ATU's, ever... Off resonance, it becomes an MDL",
  https://www.mail-archive.com/elecraft@mailman.qth.net/msg167409.html; "You MUST bypass the
  ATU", msg196652), W1GCF (msg254457), K2ULR ("the loop =is= the tuner", msg196656), AC3B (ATU
  MD BYP, TUN PWR 1 W, peak noise, then TUNE; https://qrper.com/2022/10/improving-my-mag-loop-tuning-skills/),
  G4ILO ("That's not how a magnetic loop is supposed to be used",
  https://www.amateurradio.com/alexloop-gets-an-airing/). Conditional: AC7AC and VE3WMB, to trim
  a residual mismatch at resonance, then recheck the loop (msg189422, msg189457). KX3-Rig
  follows the first group and offers the ATU only as a last resort.
- Tune power reported: 1 W (AC3B, K2ULR), 2 W, 5 W (EI2CN, msg170338), 10 W (AD5X). "Even at
  QRP levels you can get 1,000 volts across the cap" (AA1IK,
  https://www.amateurradio.com/5-foot-diameter-magnetic-loop-antenna/).
- Hand effect: VE3WDM saw 1.2 rise to 2.2 when he moved back to the radio and tuned from behind
  the loop to avoid it (https://www.amateurradio.com/learning-more-about-the-alexloop/); AD5X and
  G4ILO saw little. Nearby objects matter indoors (G4ILO 5:1 beside bookshelves; VE3WDM near a
  balcony door).
- Results when tuned: 1.3-1.4 on 40-12 m and 1.6 on 10 m without the ATU (AD5X); 1.2-1.5
  (EI2CN).
- **UNVERIFIED** at this station: TQ during TUNE, PO at 1 W, the noise peak through AGC, LED
  visibility at 1 W on 40 m, hand effect.

## FT8 engine (ft8/)

- `jt9` needs a 16-bit mono 12 kHz WAV and does not check the header: anything else decodes
  nothing, silently. The last six digits of the file name become the time stamp, so files are
  named `YYMMDD_HHMMSS.wav` (verified on WSJT-X 3.0.2).
- Command: `jt9 -8 -d 2 -q -L 200 -H 3000 -f RXHZ -c MYCALL -x DXCALL -Q n [-g DXGRID] -a DIR -t DIR
  file.wav` (`-x b` when there is no partner).
  `-c` defaults to `K1ABC` and `-x` to `W9XYZ` silently, so both are always passed. `-Q` selects
  a-priori decoding for the QSO stage. `-d 2` takes about 1.5 s on this laptop; the work directory
  keeps `jt9_wisdom.dat`, which saves about a second.
- Output line: `format(i6.6,i4,f5.1,i5,' ~ ',1x,a37,1x,a2)` from `lib/decoder.f90`: time, SNR,
  DT, frequency, a 37-character message (character 37 is `?` for a low-confidence a-priori
  decode), then an `a1`-`a8` tag.
- `ft8code "<msg>"` prints the message as the far end will see it, flags `*` when that differs
  from what was typed, prints `*** bad message ***` for unpackable text, and silently packs blank
  input as telemetry. KX3-Rig refuses all four cases.
- Transmit waveform (`lib/ft8/gen_ft8wave.f90`, QEX paper): 79 symbols of 0.16 s, 6.25 Hz tone
  spacing, Gaussian frequency pulse with BT = 2.0 over 3 symbols, continuous phase, 20 ms
  raised-cosine ramps, 12.64 s, starting 0.5 s after each 15 s boundary. The Python port matches
  `ft8sim` sample for sample and round-trips through `jt9` (test suite).
- Late starts: WSJT-X skips the elapsed part of the waveform; decodes survive several seconds of
  lateness. KX3-Rig starts up to 3 s late.
- Contact sequence and logging follow WSJT-X (`mainwindow.cpp`, User Guide 10.1-10.3): answer on
  the opposite period parity; log at the first RR73 or 73 sent; never chain contacts
  automatically. ADIF fields follow `logbook.cpp`.
- Clock: the User Guide asks for UTC within ±1 s. This machine runs systemd-timesyncd and was
  synchronized (offset about -70 ms) on 2026-10-10.

## FT4, WSPR, PSK31, CW (ft8/ft4.py, ft8/protocol.py, wspr/, keyboard/)

FT4:
- `jt9 -5` decodes FT4 (WSX lib/jt9.f90:59, 141-142). Lines use FT8's format with ` + ` in place
  of ` ~ ` (lib/decoder.f90:724-725). jt9 reads 72576 samples (6.048 s; jt9.f90:260); WSJT-X
  decodes at that point in each 7.5 s period (mainwindow.cpp:7596). TX audio starts 0.3 s in
  (Modulator/Modulator.cpp:76).
- `ft4code` is built but not installed (CMakeLists.txt:1258 against the install list at
  1663-1673), so KX3-Rig encodes FT4 itself: lib/ft4/genft4.f90 (rvec scrambling, the 103-tone
  frame with Costas arrays 0132 1023 2310 3201, Gray map 00 01 11 10 to tones 0-3),
  lib/ft8/encode174_91.f90 with lib/ft8/ldpc_174_91_c_generator.f90, lib/crc14.cpp, and
  lib/ft4/gen_ft4wave.f90 (GFSK BT = 1.0, h = 1, 576 samples per symbol at 12 kHz, 105 symbol
  times including two ramp symbols, 5.04 s). The LDPC and CRC port reproduces `ft8code`'s printed
  parity for a captured message (tests/test_ft4.py).
- Dials (models/FrequencyList.cpp): 3.575, 7.0475, 10.140, 14.080, 18.104, 21.140, 24.919, 28.180,
  50.318 MHz; none for 160 or 60 m. FT4 always sends RR73 (mainwindow.cpp:5884).
- ADIF: FT4 is SUBMODE FT4 of MODE MFSK; PSK31 is SUBMODE PSK31 of MODE PSK (ADIF 3.1 mode
  table, as WSJT-X writes them).

WSPR:
- `wsprd [-a dir] [-f MHz] [-C n] [-o n] file.wav` (lib/wsprd/wsprd.c:708-761). It skips a fixed
  44-byte header and reads 114 x 12000 16-bit samples without checking the rate (wsprd.c:122,
  146-147), and takes date and time from a `yymmdd_hhmm.wav` name (966-967). Output lines are
  `%4s %3.0f %4.1f %10.6f %2d  %-s` (time, SNR, DT, MHz, drift, message), ending
  `<DecodeFinished>` (1505-1524).
- `wsprcode` is not installed either. KX3-Rig ports the encoder from lib/wsprd/wsprsim_utils.c
  and lib/genwspr.f90: 28-bit call and 22-bit grid/power packing, K = 32 rate-1/2 convolutional
  code (polynomials 0xf2d05351 and 0xe4613c47, fano.c:13 `LL 1`), bit-reversal interleaving,
  and the 162-entry sync vector. Its symbols match the C encoder, compiled and run for seven
  messages (tests/test_wspr_protocol.py).
- Waveform: 162 symbols of 8192 samples at 12 kHz, tone spacing 12000/8192 Hz, centered on the
  audio frequency (mainwindow.cpp:9114), starting 1 s after an even minute (Modulator.cpp:72):
  110.6 s. WSJT-X decodes after 114.05 s (mainwindow.cpp:1654). Audio 1400-1600 Hz.
- Dials: 1.8366, 3.5686, 7.0386, 10.1387, 14.0956, 18.1046, 21.0946, 24.9246, 28.1246 MHz, and
  50.293 MHz for Region 2 (FrequencyList.cpp:68-283).
- Transmit share: WSJT-X fills a random 60-slot table per two hours; at 25% or less it uses
  K1JT's random gaps (WSPR/WsprTxScheduler.cpp:130-219). KX3-Rig's TxScheduler follows that
  idea and never sends two periods in a row below 50%.
- Upload: `POST http://wsprnet.org/post/`, form-encoded, `function=wspr` per spot with `rcall,
  rgrid, rqrg, date, time, sig, dt, drift, tqrg, tcall, tgrid, dbm, version, mode=2`
  (Network/wsprnet.cpp:23, 306-314), after a random 0-20 s delay (mainwindow.cpp:9698-9703).
  KX3-Rig sends the 4-character grid only.

PSK31 (G3PLX, FL):
- BPSK at 31.25 baud: a 0 is a phase reversal, a 1 is steady carrier; reversals are shaped with
  a raised cosine (G3PLX sec. 1; FL psk.cxx tx_shape). Idle is reversals, the tail is carrier.
- Varicode: FL `varicodetab1[]`. The ARRL HTML copy of the table has transcription errors (`p`
  shown as `I`'s code, `Z` as `Y`'s). Characters are separated by "00", and no code contains
  "00".
- Dials (FL rigsupport.cxx:313-328, signals about 1 kHz up): 1.807, 3.580, 7.070, 10.135,
  14.070, 18.100, 21.070, 24.920, 28.120 MHz. OM p.18 also suggests 14.070-14.073. KX3-Rig
  leaves out 18.100 and 24.920: 1 kHz up from them is inside the FT8 window on 17 m and the FT4
  window on 12 m (bandplan.py, ft8/ft4.py). No other cited 17 or 12 m PSK31 dial yet.

CW:
- Morse codes and spacing: ITU-R M.1677-1 sec. 1-2; codes as in FL morse.cxx. The decoder follows
  FL cw.cxx: complex mixing and low-pass, hysteresis between a tracked peak and noise floor, and
  speed tracking from adjacent dot-dash pairs with a length ratio of 2 to 4.
- 47 CFR 97.3(c)(1): "CW. International Morse code telegraphy emissions having designators with
  A, C, H, J or R as the first symbol; 1 as the second symbol; A or B as the third symbol; and
  emissions J2A and J2B." A keyed tone in a sideband transmitter (J2A) is therefore CW, allowed
  wherever the control operator may transmit (97.305(a)). PSK31 (J2B) is also RTTY
  (97.3(c)(7)), so KX3-Rig checks it as data.
- Why not the other keying methods: ACC1 is a 3-conductor jack (tip RX data, ring TX data, OM
  p.5), so there is no RTS or DTR to key with, and the KX3 has no PTT-KEY menu (it is K3 only,
  PR Table 5 entry 103). `KY` keys text through the KX3's keyer (PR p.15) and stays off the
  allow-list.

SWR and firmware:
- `SW;` returns SWR in tenths (PR p.24). PR's change log says KX3 firmware 2.93 (p.33); FW lists
  "ADDED SWR READ COMMAND" under MCU 2.95 (2018-12-04). KX3-Rig polls it from 2.93; on 2.93 or
  2.94 an unanswered poll is harmless. Firmware is updated with Elecraft's KX3 Utility through
  ACC1 (OM p.25, p.39).
- WS stops transmitting above SWR 2.5 and colors the display yellow above 1.5 and red above 2.0
  (WS user guide, "Rig Data"). KX3-Rig uses the same thresholds.

## Verified on this station's KX3 (2026-10-11, receive only)

- Replies at 38400 8N2 with RTS/DTR held low: `ID017;`, `OM A-F----BX-02;`, `RVM02.38;`, `K20;`,
  `AI0;`, and a well-formed 38-byte `IF`. The `OM` format is `OM APF---TBXI0n;` (PR p.21): this
  radio has the KXAT3 ATU (A), KXFL3 roofing filter (F), KXBC3 charger and clock (B), and a
  KX3-2M or KX3-4M module (X); no KXPA100 (P), KXAT100 (T), or KXIO2 (I); product 02 = KX3.
- Firmware MCU 2.38 is below the 2.93 that `SW;` needs, so KX3-Rig shows no SWR readout during
  transmit (it only polls `SW;` on 2.93+). A firmware update would enable it.
- KX3-Rig connected, followed the radio (7.245850 MHz, DATA), and ran receive audio and the
  waterfall from the Digirig for 30 s with no main-loop stalls.
- A plug that is not fully seated gives exactly the "radio isn't answering" symptom: the port
  opens and the radio sends nothing. The bring-up preflight (`check-digirig.py`) failed the same
  way until the plug was reseated.

## Open items to verify on the radio

1. Firmware version: verified above (2.38, so no SWR readout).
2. Confirm `K2;`, `K3;`, `AI;` as WSJT-X left them, and that KX3-Rig restores them on exit
   (before WSJT-X ran today the radio reported `K20;` and `AI0;`).
3. The AG (AF gain) range: the PR says 0-255; Hamlib says 0-60 in practice. KX3-Rig does not set
   AG.
4. Whether connecting pulses RTS (watch the KX3's TX indicator while KX3-Rig connects, into a
   dummy load).
5. FT8 transmit level: set Audio Level for 4-5 ALC bars at 5 W using Tune.
6. Voice: KX3 mic gain for about 5 ALC bars with the laptop or headset microphone; MIC BIAS.
7. Whether mic gain is stored separately for SSB and DATA (OM is silent).
8. Smartscan: step time over the real link, `FA` clicks, AGC and the noise curve, detector
   thresholds on real band noise and SSB, Tune accuracy on SSB, and CW pitch after Tune
   ([live-test.md](live-test.md) section 5).
9. Loop Tune: `IF`/`TQ` during front-panel TUNE, `PO` at TUN PWR 1.0 W, the receive-noise peak
   through AGC, the LED at 1 W on 40 m ([live-test.md](live-test.md) section 6).
10. FT4, WSPR, PSK31, CW: a `jt9 -5` round trip of KX3-Rig's FT4, `wsprd` on real audio, PSK31
    and CW decoding on a real band, transmit levels and spectra into a dummy load, and the SWR
    guard after a firmware update ([live-test.md](live-test.md) section 7).
