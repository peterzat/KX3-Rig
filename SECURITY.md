## Security Review: 2026-10-11 (scope: paths)

**Summary:** Path-scoped review at HEAD (ff6ea82) of the five code and test files changed in ff6ea82. That commit replaces the in-process GStreamer device scan with an asynchronous `pw-dump` subprocess, and voice and listen routing now use the cached result. One new NOTE: a dump nested deeply enough to make `json.loads` raise `RecursionError` stops audio discovery for the rest of the session (availability only). The routing invariants hold. Cached candidates still exclude Digirig nodes, a missing listen sink builds no speaker branch, and transmit stays refused until the first successful scan. The SPLIT and XIT key-down window was reproduced again on the emulator. Four NOTEs outside this scope are carried. No secret, callsign, locator, or adapter serial is in scope.

Post-fix re-check (same run) of the uncommitted /codefix change to kx3rig/controller.py, kx3rig/devices.py, tests/test_devices.py, and tests/test_station.py. The scan-latch NOTE is resolved. `finished` now catches `Exception`, so every outcome reaches `on_done` (devices.py:187-190), and `_check_audio` clears `_audio_scan_busy` when starting a scan raises (controller.py:390-394). The trigger was re-run offline with `cat` in place of `pw-dump`. Dumps nested 10,007 and 100,000 deep now report `None` within 0.03 s; the Station clears its flag and starts the next scan, and `audio.tx` stays False. The warning still logs only the exception text. While a dump keeps failing, discovery keeps the last good state, as a timeout already did, and resumes when a scan succeeds. The suite passes (227 tests: the earlier 225 plus 2 regression tests). Both new tests would fail at HEAD; this was read from the diff, not run. One new NOTE covers code the fix did not touch: the Digirig is recognized by node name alone. It cites line numbers as of the fix; controller.py lines after 390 are four higher than the HEAD numbers used elsewhere in this entry. The diff contains no secret, callsign, locator, or adapter serial (counts only).

### Findings

[NOTE] kx3rig/devices.py:30, 77-80, and 202-213; kx3rig/controller.py:209, 253, 338, 403-411, and 431 (line numbers as of the fix). The Digirig is recognized by node name alone, so another PipeWire client's node can stand in for it. `parse_pw_dump` keeps every Audio/Source and Audio/Sink node, whoever created it. `pick_digirig_audio` takes the first source and the first sink whose name matches `usb-C-Media|USB_PnP_Sound_Device`. This predates the fix, and no earlier entry records it. Confidence: high on the selection behavior (reproduced offline); low that a sandboxed client can create such a node (not tested).
  Attack vector: A sandboxed client with access to the PipeWire socket creates an Audio/Sink or Audio/Source node whose name contains `usb-C-Media`, for example before the radio is plugged in. `pw-dump` lists nodes in creation order, so the impostor comes first and is selected (controller.py:403-404). KX3-Rig then sends voice, FT8, and Tune audio to it (controller.py:253 and 338) while the link keys the radio by RTS. The waterfall and FT8 decoder read the impostor's audio (controller.py:431). An impostor sink alone also passes the `audio.tx` gate (controller.py:411 and 209). The added reach is limited, because a client that can play audio to the Digirig output can already mix sound into a transmission. The impostor adds two things: it replaces KX3-Rig's transmit audio instead of mixing with it, and it supplies the receive audio that the operator and the FT8 sequencer act on.
  Evidence: This run. Offline, a synthetic dump listed impostor nodes before the real Digirig nodes, and `pick_digirig_audio` returned the impostor as both source and sink. Read-only on the live session, `pw-dump` listed its 11 nodes in ascending `object.serial` order, not id order. /usr/share/wireplumber/main.lua.d/50-default-access-config.lua gives Flatpak clients "rx" ("all" for the Manager category). Whether "rx" permits creating a node was not verified, and no node was created on the live session.
  Remediation: Refuse transmit, with an error, when a scan finds more than one Digirig-named source or sink. This also catches a second C-Media adapter. Prefer properties a stream client cannot choose, such as a `device.id` that resolves to an ALSA Device with the CM108's USB IDs, after confirming that a client cannot set them.

[NOTE] kx3rig/controller.py:220-222; kx3rig/radio.py:253-260, 408-413, 505-509, and 558-582. Key-down can still be approved against SPLIT, XIT, or frequency state that is not the radio's current one. Re-checked in this run: still present. `can_transmit` still reads SPLIT and XIT from the main-loop copy (controller.py:220), and the `ptt` gate still compares only frequency and mode (radio.py:256-259). ff6ea82 moved this check down two lines without changing it. radio.py has no commits since the last scan, and its cited lines were re-read. Windows (2) and (3) were not re-probed. Confidence: high that each window exists; low that any occurs in normal operation.
  Attack vector: No adversary.
  - (1) The link has read a SPLIT or XIT change that the main loop has not yet applied. Key-down passes, because `ptt` compares neither flag.
  - (2) A rejected frequency SET. `_get("FA;")` returns the SET's `?;` as its answer (radio.py:412-413), and `_tuning` then clears (radio.py:564-566). Both copies hold the requested frequency until the next IF reply.
  - (3) Reconnect. `_handshake` publishes CONNECTED (radio.py:505) before it reads IF (radio.py:506-509). An active FT8 contact stops when the main loop sees the link down, but Tune, Talk, and a newly started contact are exposed for one IF round trip.
  Evidence: This run, demo emulator, General class, DATA mode. SPLIT was set on the emulator, and the link saw it after 0.20 s while the main-loop copy still showed it off. `can_transmit` and `play_data` were allowed, and the emulator's RTS rose. XIT behaved the same way (0.21 s). Windows (2) and (3) were reproduced in the 2026-10-10 scan: in 5 of 5 runs, the check approved 14.074 MHz and the rejected SET then keyed on 14.230 MHz.
  Remediation:
  - In `ptt(True)`, refuse when the link's live `split` or `xit_on` is set.
  - Keep `tuning_pending` true until an FA or IF reply read after the SET confirms the new frequency. Treat `?;` or a missing reply as unconfirmed, and match the GET's own reply rather than a `?;` left over from the SET.
  - Read IF before publishing CONNECTED, in the same state update. Ideally, read IF just before asserting RTS.

[NOTE] kx3rig/ft8/engine.py:128-133; kx3rig/radio.py:253-260, 419-431, and 543-547. The FT8 submode check can pass on a stale submode (carried from the 2026-10-10 scan, not re-checked). An unknown submode refuses (engine.py:129-130, tested at tests/test_station.py:349-355), but a stale known value passes. In a data mode the link reads DT only every fifth poll cycle (radio.py:543-547). It does not read DT when an IF reply shows a change into DATA (radio.py:419-431), and the `ptt` gate does not compare the submode. Confidence: high on the code behavior; low on the on-air effect, because the sourced references do not describe the sideband and signal source of the other submodes.
  Attack vector: No adversary. An operator changes the submode on the front panel and starts FT8 or Tune within about a second. The check passes on the old value.
  Evidence: From the 2026-10-11 scan at 85228ff, on the emulator. After the emulator's submode was set to AFSK A, `check_tx` and `play_data` were allowed at once, and RTS rose. The link saw AFSK A 0.60 s later.
  Remediation: Read DT whenever an IF reply changes the mode into DATA. Include the submode in the `ptt` gate for data transmissions, for example as an `expect_submode` argument compared with the link's live value.

[NOTE] kx3rig/bandplan.py:187 and 213. `tx_check` and `privilege_segments` still default `license_class` to "General" (carried from the 2026-10-10 scan, not re-checked). Confidence: high that no current caller omits it. The only app caller of `tx_check` is `Station.can_transmit`, which was re-read in this run's scope (controller.py:223). It passes `settings.license_class`, which defaults to Technician and is reset to Technician when unknown (config.py:35 and 67-68). `privilege_segments` has no app caller; only tests/test_bandplan.py:89 calls it, with "General".
  Attack vector: No adversary; the gap is latent. A future transmit path that called `tx_check(dial, mode)` would approve General segments for a Technician operator.
  Remediation: Make `license_class` a required parameter in both functions, or default it to "Technician".

[NOTE] install.sh:27-28, constraints.txt:1-8, pyproject.toml:2. Install-time code is still fetched unpinned (carried from the 2026-10-10 scan, not re-checked). numpy and pyserial resolve to the versions in constraints.txt. install.sh:27 upgrades pip with no version. The `setuptools>=64` build backend is installed into pip's isolated build environment, where `-c` does not apply. The pins carry no hashes. Confidence: high that pip and setuptools are unpinned; exploitation needs a compromised release.
  Attack vector: A compromised future release of pip or setuptools on PyPI runs with the user's privileges during `./install.sh`. It builds the venv of an app that keys a transmitter.
  Remediation: Pin pip (for example `pip install 'pip==26.2.1'`) or drop the upgrade. Add a tested `setuptools==` pin to constraints.txt and pass `--build-constraint constraints.txt`. Consider hashed pins with `--require-hashes`, and run `pip-audit` before releases.

[NOTE] HEAD tree, location withheld (outside this run's scope). One line still contains the 4-character prefix of the grid locator that the history scrub removed (carried from the 2026-10-10 scan, not re-checked). The scrub replaced that prefix in the tests, where it was paired with the scrubbed callsign. This line pairs it with a different callsign, so it does not identify the operator by itself. The file and line are not recorded here because this repository is public; they were given in the 2026-10-10 scan's session output. The line is not in this run's files. The five files' only locator-shaped tokens are DM79 and FN31 (cleared in the 2026-10-10 scan) and `if00` USB interface suffixes. Confidence: high that the value matches. Low that it matters, because a 4-character locator spans 1 degree of latitude by 2 degrees of longitude.
  Attack vector: A reader of the public repository learns the operator's region only if something ties this locator to the operator. Nothing in the tree does; a precise citation in a committed file would.
  Remediation: Replace the locator in that line with one unrelated to the station, as the scrub did in the tests, or record it under Accepted Risks. Include the 4-character prefix in future identity searches. Keep the location out of SECURITY.md, CODEREVIEW.md, and commit messages.

### Coverage

All eight dimensions were reviewed for the five in-scope files. Each was read in full at HEAD (ff6ea82), along with its diff against 85228ff, the last scan's commit. The scope is every code and test file changed in ff6ea82. The other file changed since that scan, d70f14d's connect_page.py jack-diagram sizing, is the /codefix change that the last scan's post-fix pass reviewed. It was re-read here with the rest of the file. AI-specific risks do not apply, because nothing in scope calls a model.

The Digirig was attached during this run, and no check opened its serial port or audio nodes. The tests use the emulator's port factory, and demo audio is synthetic and in-process. The new non-demo `Station` (tests/test_station.py:364) is never started; `RadioLink` starts its thread only in `start()`. Checks used the emulator or ran offline, with the XDG directories in a scratch directory:
- The suite passes: 225 tests (the earlier 215 plus 10 new), with the WSJT-X tools on PATH. It wrote only the GStreamer registry cache.
- `pw-dump` discovery (devices.py:155-214).
  - The command is a constant argv run through `Gio.Subprocess` with no shell. Its stderr is discarded, and a 5 s timeout cancels the read and force-kills the process.
  - The program is found on PATH, as `jt9`, `ft8code`, and `wpctl` already are.
  - `parse_pw_dump` uses `json.loads` (no evaluation) and type-checks each field. It keeps only Audio/Source and Audio/Sink nodes that have a string name.
  - Node names reach only GStreamer `target-object` properties. `node.description` is parsed but never read, and no node name is referenced in kx3rig/ui, app.py, or screenshots.py.
  - A scan failure logs only GLib or JSON error text, never dump content.
- Real `pw-dump` output on this machine (PipeWire 1.0.5) was summarized by structure only, with no names or values printed. WirePlumber 0.4.17's access rules were read; there are no user overrides.
- Routing with the cached scan (controller.py:246-250 and 411-420).
  - Both fallback lists still exclude Digirig-named nodes. A stale cache therefore cannot select the Digirig input as the microphone, or the Digirig output for listening.
  - `_listen_sink` runs only from `_start_rx`, right after the cache is refreshed. A `None` listen sink builds no speaker branch (audio.py:150-156).
  - The microphone stream opens before key-down (controller.py:251-262).
- Failure handling (controller.py:386-409).
  - A failed or timed-out scan keeps the previous state. Until a scan succeeds, `audio.tx` is False and `can_transmit` refuses (controller.py:209).
  - `audio.tx` and `_digirig_audio` are set in the same callback, so neither transmit path dereferences a missing sink.
  - A result that arrives after `shutdown` changes nothing (controller.py:396, tested at tests/test_station.py:386-388).
- Considered and not reported: a node name is passed as `target-object`, which PipeWire also accepts as an object serial. A node whose name is all digits could therefore resolve to another node. Creating such a node and changing the defaults needs a client that can already play audio into the Digirig output directly. This was not tested.
- Connect page (connect_page.py:182-184). The new help text is a constant set on a plain `Gtk.Label`. The last scan's dynamic-text analysis still holds. `busy_with` (lines 150 and 158), the shortened port name (192-195), and `audio.error` (175-176) are unchanged and come from local sources. No scan output reaches the page.
- Tests.
  - test_devices.py runs only `cat` on a tmp_path file, `true`, `sleep 30` (killed after 1 s), and a nonexistent program name. It never runs `pw-dump`.
  - Its `pw-dump` sample holds only generic device and node names.
  - The new station test replaces `scan_audio_nodes`, `_start_rx`, and `_stop_rx`. It never calls `shutdown`, so it writes no settings.
- Identity.
  - The scrubbed-identity search ran for the operator's callsign this time, as counts only. It found no match in the five files, in the full diffs of d70f14d and ff6ea82 (including README.md and docs/references.md), or in their commit messages.
  - The attached adapter's 32-character serial appears nowhere in the HEAD tree or those two commits. The test's `a4b1` suffix is a placeholder.
  - The only other personal string in scope is the app ID `com.zatloukal.KX3Rig` (connect_page.py:101), which the accepted attribution covers.

Not fully reviewed:
- The locator search was not run, because its value was not looked up in this session. The five files were checked for locator-shaped tokens instead (see the carried NOTE).
- README.md and docs/references.md changed in ff6ea82 and are outside this run's scope. They were checked only for the callsign and the adapter serial, by count.
- The nesting path through node params from a sandboxed client was not demonstrated. Neither nesting source was tested against the live PipeWire session.
- audio.py was read for context only. Whether another PipeWire or Pulse client can move KX3-Rig's own streams despite `node.dont-reconnect` was not examined.
- Key-down windows (2) and (3) are in radio.py, outside this scope and unchanged since 266a725; they were not re-probed.
- Dependency manifests and infrastructure files are outside this run's scope; their carried NOTE was not re-checked.

Git history checked for secrets: no credential-handling files are in scope. `git log -p --follow -3` of the five in-scope files was scanned for secret keywords, private-key headers, cloud and service token formats, long hex or base64 strings, and email addresses. Every hit was a false positive: `_data_tx_token`, and `+@pytest` diff lines that match the email pattern. The commit messages of d70f14d and ff6ea82 contain none. `main` is one commit ahead of `origin/main` (ff6ea82). No tags, notes, stash entries, or other refs exist.

### Accepted Risks

- The author's name in pyproject.toml, the About dialog, the AppStream metainfo, and the LICENSE
  copyright line is deliberate open-source attribution.

---
*Prior review (2026-10-11, commit 85228ff, with a post-fix re-check of the change later committed as d70f14d): A path-scoped review of the fifth-review fixes and the Connect page cable guide, with no BLOCK or WARN and five NOTEs. Three were re-checked: the SPLIT, XIT, and frequency key-down windows, the stale FT8 submode, and the `tx_check` default of General. Two were carried: unpinned install-time code and a 4-character locator prefix (location withheld). The cable guide draws only constants, its plug and jack claims matched docs/references.md, and the screenshot carried no metadata.*

<!-- SECURITY_META: {"date":"2026-10-11","commit":"ff6ea825951f62a736bf134034d831500a20522c","scope":"paths","scanned_files":["kx3rig/controller.py","kx3rig/devices.py","kx3rig/ui/connect_page.py","tests/test_devices.py","tests/test_station.py"],"block":0,"warn":0,"note":6} -->
