# First live test

KX3-Rig has been tested against a simulated KX3 and on this laptop's audio devices, but not yet on
the radio. Work through this list the first time the KX3 is attached. Steps 1-2 never transmit.
Steps 3-4 transmit; do them yourself, as control operator, starting with a dummy load. Record
anything verified in [references.md](references.md) ("Open items to verify on the radio").

## Before you start

- Quit WSJT-X (it holds the serial port; KX3-Rig shows "Radio in Use" otherwise).
- Attach a dummy load for step 3. The KX3 `RS232` menu should already be 38400.
- Open KX3-Rig from Activities, or run `.venv/bin/kx3-rig --debug` in a terminal to see the log.

## 1. Connect and receive (no transmit)

- With the Digirig unplugged, the app shows **Connect Your Radio**.
- Plug in the Digirig: the **Digirig Cable** row turns green. With the KX3 off, the page
  reads **Turn On the KX3**.
- Turn the KX3 on: the app switches to the Radio view and shows "Connected to the KX3".
  **Watch the KX3's TX indicator during connection: it must not key** (open item 4).
- The frequency matches the KX3 display. Turn the KX3's VFO: the app follows. Scroll a
  digit in the app: the KX3 follows.
- Band and Mode buttons change the KX3's band and mode.
- The S-meter moves with band noise and signals.
- Raise the volume at the bottom left: you hear the radio on the laptop. The **Radio audio**
  meter sits in the green (adjust the KX3 AF gain if not).
- The connection button (top left) shows the KX3 firmware version (open item 1).

## 2. FT8 receive (no transmit)

- FT8 view, **Tune Radio to FT8**: the KX3 shows 14.074 in DATA mode (DA submode).
- Decodes appear within about 30 seconds, with DT values mostly within ±0.5 s.

## 3. Transmit into the dummy load

- FT8 view, **Tune**: the KX3 transmits a tone for up to 10 seconds. Watch the KX3's display
  for power, SWR, and ALC, and set **Audio Level** so it shows 4-5 ALC bars at 5 W (open item 5).
- Press **Tune** again, or Esc, mid-tone: the KX3 unkeys at once.
- Radio view, USB at 14.285 MHz: **Hold to Talk** keys the radio; speak and set the KX3 mic
  gain for about 5 ALC bars (open item 6). Release: it unkeys.
- General class only: Hold to Talk on 14.200 MHz (Extra-only phone) is disabled and says why.
  (An Extra licensee may transmit there, so skip this step if your class is Extra.)
- Quit the app while transmitting a Tune tone: the radio unkeys.

## 4. On the air (AlexLoop)

- Peak the loop for the loudest receive noise on 14.074.
- Double-click a strong CQ. The contact runs by itself; Stop ends it at any time.
- When it completes, the contact appears under **Logged Contacts** and in
  `~/.local/share/kx3-rig/kx3rig-log.adi`.

## After

- Start WSJT-X once to confirm the radio still works with it (KX3-Rig restores the
  `K2`/`AI` settings it found; open item 2).
