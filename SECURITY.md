## Security Review: 2026-10-10 (scope: paths)

**Summary:** Path-scoped review at HEAD (3f84f8a) of the 11 files changed by the second review-fix commit: the transmit-policy code (radio.py, controller.py, bandplan.py), settings validation (config.py), the emulator, the first-transmit dialog, four test files, and the regenerated confirm.png. The changes add no attack surface, and each new check fails closed. Key-down is refused while a tune is queued or being applied. Transmit is refused while SPLIT or XIT is on. An unknown license class falls back to Technician, and null or wrong-typed settings fall back to defaults. The prior WARN is resolved. The `pre-scrub` branch no longer exists. `main` was rewritten again only to drop private-repository links: its first four commits are unchanged, the next three differ only in README.md and docs/references.md, and the last two have the same trees as before. No commit on `main` contains the scrubbed callsign or grid. The key-down-window NOTE was re-checked and is still present. This run adds two NOTEs: the license check ignores the radio's data submode, and `tx_check` still defaults to General when no class is passed. No secrets or personal data were found in scope.

### Findings

[NOTE] kx3rig/radio.py:245-252, 493-494, and 546-554; kx3rig/controller.py:104 and 201-215. Key-down can still be approved against a frequency, mode, SPLIT, or XIT state that is not the radio's current one. Re-checked in this run: the code is unchanged and the issue is still present. Confidence: high that each window exists (this run reproduced the first one again, and the prior scan reproduced all three); low that any occurs in normal operation.
  Attack vector: No adversary. There are three timing windows. (1) Stale main-loop copy. `can_transmit` reads `Station.radio`, which is updated through `GLib.idle_add` (controller.py:104), while `ptt(True)` checks only the link's own `tuning_pending`. If the link finishes applying a tune before the idle update runs, the check sees the old frequency and key-down is accepted. The FT8 tick (ft8/engine.py:280-299) and the 2 s audio scan (controller.py:374-390) run at default priority, ahead of idle updates. (2) Unconfirmed readback. `_tuning` clears when `_apply_changes` returns, even if the FA readback was `?;` or timed out (radio.py:566-570). The state then keeps the optimistic frequency until the next IF poll, and once keyed the link polls only TQ, PO, and SW (radio.py:505-519). A SPLIT or XIT change made on the radio likewise reaches the check only at the next IF poll. (3) Reconnect. `_handshake` publishes CONNECTED (radio.py:493) before it reads IF (radio.py:494), so the pre-outage frequency and flags are briefly approved. A link drop now ends any data transmission in flight (`_abort_data_tx`), but nothing halts an FT8 contact that is between transmissions (ui/window.py:175-179).
  Evidence: This run used demo mode with General class on 14.074 MHz DATA. It called `tune_to(14_230_000)` without iterating the main loop. After the emulator applied the tune and `tuning_pending` was False, `can_transmit(Mode.DATA, 1500, 1550)` and `play_data` were both allowed against 14.074 MHz. The radio was keyed on 14.230 MHz DATA, which `tx_check` refuses for General. The fix's test (tests/test_radio.py:245-260) checks `link.state`, not the `Station.radio` copy that the real check reads.
  Remediation: Pass the checked frequency and mode, and the requirement that SPLIT and XIT be off, to `ptt(True)`. In the link, refuse unless no change is pending and an FA or IF reply dispatched after the most recent SET confirms them. Treat a `?;` or missing readback as unconfirmed. Ideally, read IF just before asserting RTS. Publish CONNECTED in the same state update as the first IF reply.

[NOTE] kx3rig/controller.py:201-215 and kx3rig/bandplan.py:166-170. The license check ignores the radio's data submode. `occupied()` assumes the upper-sideband convention for DATA, which the references ground for DATA A only (docs/references.md:79), but the radio can also be in AFSK A, FSK D, or PSK D (docs/references.md:38). The link reads the submode (radio.py:428-431, polled at radio.py:532), but neither `can_transmit` nor `Ft8Engine.check_tx` (ft8/engine.py:120-125) checks it. The issue predates this change and is the same class as the SPLIT/XIT gap fixed in the prior cycle. Confidence: high that the submode is not checked; low on the on-air effect, because the sourced references do not cover the sideband or signal source of the other submodes.
  Attack vector: No adversary. The operator switches the KX3 to another data submode on the front panel (KX3-Rig itself always selects DATA A, controller.py:184 and 197). They then use FT8 or Tune with the dial within about 3 kHz above a lower segment edge. If that submode uses the lower sideband, or generates its own signal at the dial, the emission falls below the edge the check approved. Every standard FT8 dial is at least 10 kHz from a segment edge, so this needs a manually tuned dial.
  Evidence: Demo mode, General class. With the emulator reporting AFSK A (`Station.radio.data_submode` was `AFSK_A`) and the dial at 14.0245 MHz DATA, `can_transmit(Mode.DATA, 1500, 1550)` was allowed for the span 14.02600-14.02605 MHz. The lower-sideband span at the same dial, 14.02295-14.02300 MHz, is outside General privileges (14.025-14.150 MHz).
  Remediation: For data modes, refuse in `can_transmit` (or `Ft8Engine.check_tx`) unless `self.radio.data_submode is DataSubmode.DATA_A`, with a message such as "Set the KX3 to DATA A to transmit." This costs nothing in normal use, because the app selects DATA A itself.

[NOTE] kx3rig/bandplan.py:186 and 212. `tx_check` and `privilege_segments` still default `license_class` to "General". An unknown class now falls back to Technician (lines 200 and 214), but omitting the argument still selects General. Confidence: high that no current caller omits it.
  Attack vector: No adversary; the gap is latent. The only app caller, `Station.can_transmit` (controller.py:215), passes `settings.license_class`, and only tests call `privilege_segments`. A future transmit path that called `tx_check(dial, mode)` would approve General segments for a Technician operator.
  Remediation: Make `license_class` a required parameter in both functions, or default it to "Technician".

[NOTE] pyproject.toml:11, kx3rig/app.py:164 and 170, data/com.zatloukal.KX3Rig.metainfo.xml:9. The author's full name is published as attribution (carried from the 2026-10-10 scan, not re-checked). CODEREVIEW.md now lists this attribution under its Accepted Risks, but the Accepted Risks section of this file does not record it.
  Attack vector: No adversary. The first push publishes the name in the package metadata, the About dialog, and the AppStream developer entry. The surname and GitHub username also appear in the app ID, the repository URLs, and commit metadata.
  Remediation: If the CODEREVIEW.md entry reflects the operator's decision, record it under Accepted Risks below so later scans stop carrying it.

[NOTE] pyproject.toml:13, requirements.txt:4-8, install.sh:27-28. Dependencies use lower bounds only, with no lock file or hashes (carried from the 2026-10-10 scan, not re-checked).
  Attack vector: `install.sh` upgrades pip and installs the newest numpy release from PyPI on every install. A compromised future release would therefore put unreviewed code into an app that keys a transmitter.
  Remediation: Ship a constraints file with hashes (for example, `pip install --require-hashes -c constraints.txt -e .`) or pin known-good versions, and run `pip-audit` before releases.

[NOTE] CLAUDE.md:47. The visual-review command writes screenshots to the fixed, shared path `/tmp/shots`, and the agent then reads them back (carried from the 2026-10-10 scan, not re-checked). Confidence: low, because the attack needs a second local account.
  Attack vector: On a multi-user host, another account pre-creates `/tmp/shots`. `screenshots.run` accepts the existing directory (kx3rig/screenshots.py:41), and the other account can replace the PNGs before the agent reads them. That feeds attacker-chosen images, including embedded text instructions, to a coding agent with shell access.
  Remediation: In the documented command, use a private directory such as `"$(mktemp -d)"` or the session scratchpad.

### Coverage

All eight dimensions were reviewed for the 11 in-scope files, each read in full at HEAD. docs/screenshots/confirm.png was inspected visually: it shows the demo FT8 view with the new dialog text and no callsign, grid, or local path. It was also parsed: it has only IHDR, 19 IDAT, and IEND chunks, all CRCs are valid, there are no text or EXIF chunks, and nothing follows IEND.

Runtime checks used the demo emulator only, with no serial device attached:
- The 60 tests in the four in-scope test files pass.
- The key-down and data-submode probes described in the findings.
- Settings files with null, wrong-typed, list, and boolean values fall back or clamp without widening a privilege or the power ceiling.
- A numeric setting given as an integer too large for a float (over 308 digits) makes `config.load()` raise OverflowError at startup. This is a robustness gap, not a security one, and it fails closed. It was passed to /codereview.

Code traced outside scope, for context:
- `Ft8Engine.check_tx`, the transmit tick, and `_tx_done` (ft8/engine.py:120-125, 270-345). `on_done(False)` halts the sequence, so the new abort path cannot re-key.
- Each action behind the first-transmit dialog re-runs the transmit check at key-down (ui/radio_page.py:207-219, ui/ft8_page.py:303-326).
- `cat.parse_if`, `cat.parse_dt`, and the voice stream lifecycle in audio.py.

Not fully reviewed:
- KX3 behavior that the sourced references do not cover was not verified, because no hardware is attached and no local copy of the manuals exists:
  - the sideband and signal source of AFSK A, FSK D, and PSK D;
  - the IF VFO field at position 30, which is parsed as `vfo_b_rx` but not stored or checked;
  - any other radio-side setting that moves the transmit frequency, such as an FM repeater offset.
- Markup sinks in ui/window.py. `Adw.Toast` parses markup by default.
  - Local input: toasts receive serial replies (in the "garbled" message) and GStreamer errors. Neither crosses a privilege boundary.
  - Remote input: FT8 engine events also reach toasts. The prior full scan found their remote fields filtered, and ft8/engine.py has not changed since.
  - The dialog body is plain text.
- Dependency manifests, packaging, and the remaining source files were outside this run's scope. Their findings are carried without re-checking.

Git history checked for secrets: no credential-handling files are in scope. `git log -p --follow -3` of kx3rig/config.py, tests/test_config.py, and tests/test_station.py shows only placeholder identities (K1ABC, FN42hn, N0CALL, DM79). All nine commits on `main` were searched for the scrubbed callsign and 6-character grid, read from the reflog-only pre-scrub commits and never printed. There were no matches in file contents or commit messages. The unscrubbed commits survive only in the local reflog, which `git push` does not send. No tags, notes, stash entries, or refs other than `main` exist.

### Accepted Risks

- The author's name in pyproject.toml, the About dialog, the AppStream metainfo, and the LICENSE
  copyright line is deliberate open-source attribution.

---
*Prior review (2026-10-10, commit 26f3355): A full audit of the scrubbed `main` before the first push, with two post-fix passes. It resolved the earlier personal-data WARN and license-class NOTE. Its post-fix passes checked the key-down refusal during a tune and the data-transmission abort, and they found and then confirmed the fix for a WARN about transmitting under SPLIT or XIT. It left one WARN: the unscrubbed `pre-scrub` branch was one push away from the public remote. It also left four NOTEs: narrow key-down windows, the author's name as attribution, lower-bound-only dependencies, and the shared `/tmp/shots` path.*

<!-- SECURITY_META: {"date":"2026-10-10","commit":"3f84f8a1a2d2c2fd8a2743f7ea73e8a3f55f0d34","scope":"paths","scanned_files":["docs/screenshots/confirm.png","kx3rig/bandplan.py","kx3rig/config.py","kx3rig/controller.py","kx3rig/fakeradio.py","kx3rig/radio.py","kx3rig/ui/window.py","tests/test_bandplan.py","tests/test_config.py","tests/test_radio.py","tests/test_station.py"],"block":0,"warn":0,"note":6} -->
