# CLAUDE.md — KX3-Rig

Operational guide for working on this repo with Claude Code. KX3-Rig is a GTK 4 / libadwaita 1.5
Python app that controls an Elecraft KX3 through a Digirig Mobile on this ThinkPad (Ubuntu
24.04). User-facing docs are in [README.md](README.md); sourced radio facts are in
[docs/references.md](docs/references.md). The station's hardware bring-up lives in the sibling
repo `~/src/KX3-Digirig-Ubuntu`.

## Working on this repo

**Ground hardware and menu claims; do not recall them.** KX3 and Digirig specifics (CAT
formats, button and menu behavior, cabling, audio levels) must come from a source read this
session (docs/references.md, the manuals it cites) or a live check on the radio. Two
from-memory claims were wrong in the earlier bring-up project. When something is verified live,
record it in docs/references.md.

**Credit what is borrowed.** Whenever a feature borrows from a new source (a program, a spec, a
manual, someone's published notes), add it to the README's opening "based on" sentence and its
"What KX3-Rig reuses" list, to Credits when it is a person's or project's work, and cite it in
docs/references.md.

**Sudo and system-wide changes are the operator's.** Propose the exact command; never run
`sudo` or change packages, groups, systemd units, or udev rules.

**Transmitting.** Never key the radio on air without the operator present and agreeing in the
moment. Automated tests that transmit require a dummy load the operator has confirmed.

**Durable facts:**
- App ID `com.zatloukal.KX3Rig`. Run from source with `.venv/bin/kx3-rig` (editable install via
  `./install.sh`, which also installs the desktop launcher to `~/.local/share`).
- The venv is created with `--system-site-packages` because PyGObject, GTK, libadwaita, and
  GStreamer come from apt. numpy and pyserial are in the venv.
- CAT: 38400 8N2, no handshake, CP2102N at `/dev/serial/by-id/*CP2102*`. Never scan baud rates.
  Every outgoing command must pass `cat.ALLOWED`; extend the allow-list only with a cited source.
- Audio: PipeWire nodes for the Digirig match `usb-C-Media` / `USB_PnP_Sound_Device`. Every
  stream sets `node.dont-reconnect` and an explicit target so audio is never silently rerouted
  (listening audio must never reach the Digirig output).
- FT8 and FT4 use WSJT-X's `jt9` (`-8`, `-5`) and `ft8code` (WSJT-X 3.0.2 installed); WSPR uses
  `wsprd`. WSJT-X does not install `ft4code` or `wsprcode`, so FT4 and WSPR encoding are ported
  (ft8/ft4.py, wspr/protocol.py). Always pass `-c MYCALL` to jt9.
- One self-keying activity at a time (FT8/FT4, the WSPR beacon, a keyboard message):
  `Station.register_keyer` and `auto_keying()`. New transmit paths register too.
- Demo mode (`--demo`, `--demo off`, `--demo unplugged`) runs the real link code against
  `fakeradio.FakeKX3` and synthesizes FT8 traffic that answers our transmissions. Demo contacts
  log to `kx3rig-demo-log.adi`, never the real log.

**Visual review.** `--demo --screenshot DIR` renders the window to PNGs: `KX3RIG_SHOTS` picks
plans from `radio,voice,ft8,qso,scan,loop,ft4,keyboard,wspr`; `--demo off` or `--demo unplugged` capture the connect page.
`--screenshot` refuses to run without `--demo` (the plans retune and transmit). When the
desktop is locked or the display is off, GTK draws no frames; run inside a private headless
compositor instead:

```bash
dbus-run-session -- gnome-shell --headless --no-x11 --sm-disable \
  --virtual-monitor 1280x960 --wayland-display kx3shot &
WAYLAND_DISPLAY=kx3shot .venv/bin/kx3-rig --demo --screenshot "$(mktemp -d)"
```

**Network.** Only Smartscan goes online (PSKReporter at most every 5 minutes, SWPC every 15),
only while it is on, and never in demo mode. The one exception is WSPR's Share Spots on WSPRnet,
off by default: when the operator turns it on, it sends the callsign, the 4-character grid, and
the spots heard. Send nothing beyond the 4-character grid without the operator's say-so.

**macOS (convenience only).** The ThinkPad is the target. On the MacBook, Homebrew's GTK stack
works with a venv made from `/opt/homebrew/bin/python3.14 -m venv --system-site-packages`;
run the app with `XDG_DATA_DIRS=/opt/homebrew/share`. `--screenshot` there may report "nothing
rendered yet" for the first capture.

**Tests:** `./run-tests.sh` must pass with no radio attached. The FT8 round-trip tests need the
WSJT-X tools and are skipped without them. Add or update tests in the same increment as any
behavior change; pure logic lives outside `ui/` so it can be tested.

**Conventions (global CLAUDE.md):** small committable increments; commits attributed to the
configured user only; the pre-push hook requires `/codereview`. Writing style: professional,
concise, no em-dashes, no emoji. Interface copy follows the GNOME HIG (header capitalization for
titles and buttons, sentence case for descriptions).

## Layout

- `kx3rig/cat.py` protocol and allow-list; `radio.py` serial worker (connection states,
  verified SETs, RTS PTT, watchdog); `fakeradio.py` emulator.
- `audio.py` GStreamer/PipeWire streams; `spectrum.py` waterfall FFT; `devices.py` Digirig
  discovery; `controller.py` the `Station` object the UI talks to (transmit policy lives here).
- `bandplan.py` US privileges and FT8 dials; `config.py` settings (`~/.config/kx3-rig`).
- `ft8/` messages, sequencer, encode (ft8code + GFSK), decode (jt9 + UTC-aligned recorder),
  engine (period timing, transmit scheduling, logging), adif, grid.
- `smartscan/` detect (voice/CW/carrier in a dwell), plan (sweep steps, RF mapping, calling
  frequencies), heard (merged hearings and clips), conditions (PSKReporter, SWPC, sun), engine
  (the sweep on the main loop). Design and story in docs/smartscan.md.
- `looptune/` state (where the AlexLoop is tuned, per-band widths), meter (receive-noise peak),
  tuner (the GObject the UI uses; reads the operator's TUNE carrier, never keys). Procedure
  and sources in docs/looptune.md.
- `ft8/protocol.py` FT8 and FT4 timing and waveforms; `ft8/ft4.py` the FT4 encoder;
  `ft8/filters.py` which decodes to show. Design in docs/digital-modes.md.
- `keyboard/` PSK31 (varicode, psk31) and CW (cw) modems in numpy, and the engine (send one
  composed message in DATA A; CW is a keyed tone, checked as CW).
- `wspr/` protocol (encode, wsprd output, scheduler) and engine (decode, beacon, opt-in upload).
- `ui/` window, connect page, radio page, FT8 page (FT8 and FT4), keyboard page, WSPR page,
  smartscan, looptune (the guide), frequency readout, waterfall, meters, preferences, style.css.
