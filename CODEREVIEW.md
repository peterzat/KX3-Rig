## Review — 2026-10-10 (commit: 2c3aebc)

**Summary:** First-push full review of the whole tree (empty-tree base, 64 files): radio core, FT8 engine, GTK UI, packaging, and docs. One fix cycle was applied (uncommitted). Tests: 178 passed at baseline, 183 passed after fixes.

**External reviewers:**
None configured.

**Built-in review:**
`/code-review high`: 9 findings, 8 kept after Step 6 (1 dropped as a style item).

### Findings

[BLOCK] kx3rig/controller.py:218-220 — The microphone guard did the opposite of its intent. FIXED.
  Evidence: when the default source was the Digirig input, `mic = None` was passed to `VoiceTransmit`, so `pipewiresrc` had no target and autoconnected to the default source: the Digirig. Voice transmit would feed radio audio (KX3 PHONES, including TX monitor) back into the KX3 MIC on air.
  Fix: `devices.pick_mic()` never returns a Digirig node. `start_talking` refuses to key when no other microphone exists and never builds an untargeted mic stream.

[WARN] kx3rig/ft8/engine.py:299, 320-336 — A transmission still playing when the operator answered or called CQ was credited to the new contact. That could log a contact early and skip RR73 or 73. FIXED.
  Evidence: verified that after answering an R-report addressed to us, the old CQ's completion made `sent()` return True (contact logged) and suppressed RR73.
  Fix: the completion callback carries the sequencer that sent the message. `_tx_done` ignores completions from a replaced sequencer.

[WARN] kx3rig/controller.py:160-190 — License-class policy was checked only at key-down. Tune, band, and mode changes were accepted while keyed. FIXED.
  Fix: `Station.transmitting` added. `tune_to`, `select_band`, `select_mode`, and `go_ft8` refuse while transmitting.

[WARN] README.md:71-72 — The README promised a per-band confirmation before the first voice transmission, but voice never asked. FIXED.
  Fix: Hold to Talk goes through `MainWindow.confirm_transmit`. On an unconfirmed band the dialog only records the confirmation, and the next press keys.

[WARN] kx3rig/config.py:29-30 — The station callsign and 6-character grid were the defaults, so a fresh install would transmit under this station's callsign. (also /security) FIXED.
  Fix: both default to empty. Transmit is refused until a callsign is set. The station's own values persist in `~/.config/kx3-rig/settings.json`. The defaults test was deliberately updated.

[WARN] kx3rig/config.py:84 — A settings file with a non-string field (for example `"callsign": null`) crashed startup with AttributeError. FIXED.
  Fix: `load()` also catches AttributeError. Test case added.

[WARN] kx3rig/screenshots.py, kx3rig/app.py — `--screenshot` ran against the real radio without `--demo`, and the `qso` plan keyed it with no operator. (also /security) FIXED.
  Fix: `main()` rejects `--screenshot` without `--demo`, and `screenshots.run` refuses as a second guard.

[WARN] kx3rig/cat.py:89, kx3rig/radio.py:129-136 — `TX;` was allow-listed but nothing sent it, contradicting the README Safety section. CAT keying would also bypass the RTS-only watchdog. (also claude-code, also /security) FIXED.
  Fix: `TX` removed from `ALLOWED` (`RX` kept). Unused `_Pending.cat_ptt`/`extra` removed. `"TX;"` moved to the rejected-commands test.

[WARN] README.md:85-86 — The README stated that connecting never transmits, while docs/references.md marks the cp210x RTS-on-open behavior UNVERIFIED. (claude-code) FIXED.
  Fix: the bullet now states what the code does and that a driver RTS pulse during open is not yet ruled out.

[WARN] kx3rig/radio.py:455-470 — Any re-handshake overwrote the saved K2/AI values with the app's own K20/AI0, so nothing was restored on exit. (claude-code) FIXED.
  Fix: the first values read in the session are kept (`setdefault`). A re-handshake test was added (it fails on the old code).

[WARN] Repository history — The station callsign and 6-character grid are in all 5 unpushed commits, in the test files, and in the FT8 screenshots, and are headed for a public repo. (/security) OPEN: REQUIRES HUMAN DECISION.
  Evidence: see SECURITY.md. Changing HEAD alone does not remove them from history.
  Suggested fix: either accept the risk (callsigns are public by design, and the 4-character grid is sent in every FT8 CQ) and list it under Accepted Risks, or scrub and rewrite the unpushed commits before the first push.

[NOTE] kx3rig/controller.py:269-274 — `play_data.finished` clears `_data_tx` and unkeys even when a newer transmission has started (the demo-mode timer still fires after a halt). A transmit-audio pipeline error never sends EOS, so PTT stays keyed silently until the watchdog, and the engine then counts the message as sent.

[NOTE] kx3rig/config.py:32-33, kx3rig/cat.py:130-133 — `power_w` is stored but never applied, despite its comment. Sub-watt values round to `PC000;`. (also claude-code)

[NOTE] kx3rig/config.py:59-60 — `"max_power_w": NaN` in a hand-edited settings.json passes `clamp()`. It disables the power ceiling in `RadioLink.set_power` and crashes `radio_page._build_power` at startup. (/security, non-security)

[NOTE] kx3rig/config.py:32 — The license class still defaults to General. A Technician who sets only a callsign passes General privilege checks. (/security, medium confidence)

[NOTE] kx3rig/radio.py:480-556 — A tune or band change queued just before key-down is still applied by the link thread after PTT is keyed (a window of tens of milliseconds, operator-triggered only). (/security, non-security)

[NOTE] kx3rig/ui/radio_page.py:273-310 — Since the new transmit guard, the readout, band chips, and mode buttons stay sensitive while keyed. A refused change shows on screen until the next state update, with no reason given.

[NOTE] kx3rig/radio.py:509-510 — After a transmission only `power_out` is cleared. The previous `swr` shows briefly at the start of the next one.

[NOTE] tests/ — `Station` (controller) has no tests. `Ft8Engine` has one completion test, added by this fix.

[NOTE] install.sh:33 — `Exec=` is substituted unquoted, so a repo path with spaces, `|`, or `&` breaks the launcher.

[NOTE] kx3rig/ft8/sequencer.py:90-105 — Answering a decode addressed to us that carries only "73" (or no exchange word) reports success but leaves the sequencer idle.

[NOTE] docs/references.md:34-57 — The allow-list entries `FB`, `PS`, `RVD`, and `K3` have no cited source, which the project CLAUDE.md requires. (claude-code)

[NOTE] CLAUDE.md:38-43 — The `connect` value of `KX3RIG_SHOTS` does nothing. Connect shots need `--demo off` or `--demo unplugged`. Shots go to a shared `/tmp/shots` path. (claude-code, /security low confidence)

[NOTE] docs/references.md:118 — The documented jt9 command omits `-g GRID` and the `b` placeholder used when the callsign is empty. That case is now reachable on fresh installs. (claude-code)

[NOTE] docs/references.md:132-133 — "Starts up to 3 s late" counts from the period boundary. The most waveform skipped is about 2.5 s. (claude-code, low confidence)

[NOTE] requirements.txt, pyproject.toml — Dependencies have minimum versions only, with no lock file. (/security)

### Fixes Applied

- [BLOCK] kx3rig/controller.py, kx3rig/devices.py: the voice mic is never the Digirig input, and transmit is refused if no other mic exists. Tests in tests/test_devices.py.
- [WARN] kx3rig/ft8/engine.py: an FT8 completion is credited only to the sequencer that sent it. Test in tests/test_ft8_sequencer.py.
- [WARN] kx3rig/controller.py: no tune, band, or mode changes while transmitting.
- [WARN] kx3rig/ui/radio_page.py, kx3rig/ui/window.py: per-band confirmation before the first voice transmission.
- [WARN] kx3rig/config.py: empty default callsign and grid (test updated).
- [WARN] kx3rig/config.py: AttributeError in settings load falls back to defaults (test added).
- [WARN] kx3rig/app.py, kx3rig/screenshots.py: `--screenshot` requires `--demo`.
- [WARN] kx3rig/cat.py, kx3rig/radio.py: `TX` removed from the allow-list, dead pending fields removed (test updated).
- [WARN] README.md: the Safety bullet on RTS at open now matches the verified state.
- [WARN] kx3rig/radio.py: original K2/AI kept across re-handshakes (test added).

### Accepted Risks

None.

<!-- REVIEW_META: {"date":"2026-10-10","commit":"2c3aebc","reviewed_up_to":"2c3aebc6943c9a85b9fe97f41dde419c3e436b3d","base":"4b825dc642cb6eb9a060e54bf8d69288fbee4904","tier":"full","block":0,"warn":1,"note":15} -->
