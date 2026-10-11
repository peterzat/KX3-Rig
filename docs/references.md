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

## Open items to verify on the radio

1. Read `RVM;` for the firmware version (`SW;` SWR needs 2.93+).
2. Confirm `K2;`, `K3;`, `AI;` as WSJT-X left them, and that KX3-Rig restores them on exit.
3. The AG (AF gain) range: the PR says 0-255; Hamlib says 0-60 in practice. KX3-Rig does not set
   AG.
4. Whether connecting pulses RTS (watch the KX3's TX indicator while KX3-Rig connects, into a
   dummy load).
5. FT8 transmit level: set Audio Level for 4-5 ALC bars at 5 W using Tune.
6. Voice: KX3 mic gain for about 5 ALC bars with the laptop or headset microphone; MIC BIAS.
7. Whether mic gain is stored separately for SSB and DATA (OM is silent).
