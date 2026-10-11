## Review — 2026-10-10 (commit: 26f3355)

**Summary:** First-push full review of the whole tree on the rewritten `main` (empty-tree base, 65 files, 8 commits). Two fix cycles were applied (uncommitted): key-down is refused while a tune is in flight, a link-initiated PTT drop now ends the FT8 engine's transmission, and transmit is refused while SPLIT or XIT is on. Tests: 191 passed at baseline, 194 passed after fixes.

**External reviewers:**
None configured.

**Built-in review:**
`/code-review high`: 8 findings, 6 kept after Step 6 (merged into 4 NOTEs; 1 dropped as unconfirmed, 1 as style).

### Findings

[WARN] kx3rig/radio.py:234-238 — Discarding a pending tune at key-down transmitted on a frequency the license check never saw. FIXED.
  Evidence: `set_frequency` updates `RadioState.frequency` optimistically and `Station.can_transmit` checks that value, but `ptt(True)` dropped the pending `FA`, so the radio keyed on its previous frequency while the display showed the checked one. Reproduced with FakeKX3 (checked 14.230 MHz, transmitted on 14.200 MHz USB, outside General phone). Introduced by 75eb844.
  Fix: `ptt(True)` refuses while a band, frequency, or mode change is queued or being applied, and keeps the change. The discard test was replaced by `test_never_keys_on_a_frequency_other_than_the_one_checked`.

[WARN] kx3rig/controller.py:150-155, 327-333 — When the link dropped PTT on its own (time-limit watchdog, or no TQ reply while keyed), the FT8 engine was never told, so it stayed "transmitting" and refused Tune until the operator pressed Stop. A lost serial port also let the data clip play out and counted it as sent. FIXED.
  Evidence: `stop_data_tx()` cleared the completion token, so `on_done` never ran. Reproduced in demo mode (Tune stuck after a "watchdog" event). Introduced by 75eb844.
  Fix: on a "watchdog" or "lost" event the data transmission in flight ends and its `on_done(False)` runs once (`_abort_data_tx`). Operator halts stay silent. Test `test_watchdog_ends_data_transmission_and_reports_it_once` added.

[WARN] kx3rig/controller.py:201-215 — The license check ignored SPLIT and XIT, so an approved key-down could transmit on VFO B or at the XIT offset, outside the operator's privileges. (/security post-fix re-check; pre-existing) FIXED.
  Evidence: `RadioState.split` and `xit_on` were stored from every IF poll and never read; only VFO A reached `bandplan.tx_check`.
  Fix: `can_transmit` refuses with "Turn off SPLIT and XIT on the KX3 to transmit." The emulator reports both flags at the documented IF offsets. Test `test_split_or_xit_blocks_transmit` added. Not confirmed on the radio itself.

[WARN] Local branch `pre-scrub` (7fe3a5f) — It still holds the unscrubbed history: the station callsign in four test files, the 6-character grid, and the original FT8 screenshots. (/security) OPEN: REQUIRES HUMAN DECISION.
  Evidence: `main` is clean (no commit on `main` contains either value, in file contents or commit messages). `git push -u origin main` would not send `pre-scrub`, but `git push --all`, `--mirror`, or `git push origin pre-scrub` would publish it to the public repository.
  Suggested fix: push with `git push -u origin main`. If a backup is wanted, `git bundle create ~/kx3-rig-pre-scrub.bundle pre-scrub`, then `git branch -D pre-scrub`.

[NOTE] kx3rig/radio.py:245-252, 493-494, 546-554, kx3rig/controller.py:104, 201-215 — Narrow key-down windows remain: the license check reads the main-loop copy `Station.radio` (idle priority), so a default-priority FT8 tick can check a stale frequency just after a tune was applied; a `?;` or missing frequency readback clears the in-progress flag while the state still shows the optimistic frequency; a SPLIT or XIT change made on the radio is seen only at the next IF poll; and after a reconnect `_handshake` reports CONNECTED before reading IF, so the pre-outage frequency and flags are briefly approved. All reproduced against the emulator; low likelihood in normal use. A sturdier design has the link confirm frequency, mode, SPLIT, and XIT against the checked values just before asserting RTS, and announces CONNECTED with the first IF reply. (/security)

[NOTE] kx3rig/controller.py:247-249, 306-307 — When key-down is refused because a tune is still in flight, the operator sees "The radio did not accept push-to-talk." and an active FT8 contact is halted as "blocked". A "Waiting for the radio" reason would be clearer.

[NOTE] Commits 77cd569 and 75eb844 each bundle many unrelated fixes (about ten and seven). They follow this workflow's review-batch convention and their messages list every item, so this is not a BLOCK. Split them only if per-fix bisecting matters; nothing is pushed yet.

[NOTE] Repository history — Links to the private KX3-Digirig-Ubuntu GitHub repository remain in 166f505, 77cd569, and 75eb844 (README.md:11, docs/references.md:7). 26f3355 removes them from HEAD only. If the goal was only to avoid dead links, nothing is needed. If the repository's GitHub location should stay unpublished, fold 26f3355 into the earlier commits before the first push. The repository name stays at HEAD in CLAUDE.md:7 and docs/references.md:6 either way. (claude-code)

[NOTE] docs/references.md:6, 22-24 — Facts marked station-verified now cite private notes that readers cannot open, while line 4 says the linked source wins on any conflict. Copy the verified facts in, or mark them as verified on this station with a date. (claude-code)

[NOTE] kx3rig/ui/window.py:253-255, README.md:72 — The generalized first-transmit reminder now addresses only magnetic-loop users, so operators with other antennas get no tune or SWR reminder, though the docstring says "antenna tuned". README.md:72 states the reminder unconditionally. A neutral line ("Check that your antenna is tuned for this frequency; for a magnetic loop, ...") covers both. The AlexLoop is still named as the reason for the 10 W default in README.md:95, ui/preferences.py:68, and config.py:37. (claude-code)

[NOTE] docs/screenshots/confirm.png — It shows the old dialog text ("Retune the AlexLoop ..."). Neither README.md nor the metainfo references it, and screenshots.py:93 writes `confirm-light.png`, so it will not be regenerated. Regenerate or remove it. (claude-code)

[NOTE] kx3rig/controller.py:99-100 — `"serial_port": null` in a hand-edited settings.json passes `config.load()` (`clamp()` never touches it) and crashes `Station.__init__` at `settings.serial_port.strip()` (verified). Separately, any one bad field makes `load()` return all defaults, and `Station.shutdown()` then saves those defaults over the operator's file.

[NOTE] kx3rig/bandplan.py:186, 200, 212-214 — `tx_check` and `privilege_segments` still default to, and fall back to, General for an unknown class. `Settings.clamp()` makes this unreachable today, but it should match the new most-restrictive default (Technician).

[NOTE] kx3rig/radio.py:536-537 — After a transmission only `power_out` is cleared; the previous `swr` shows briefly at the start of the next one. (carried from prior review)

[NOTE] install.sh:31 — `Exec=` is substituted unquoted, and a repo path containing `|` breaks the sed expression. (carried from prior review)

[NOTE] kx3rig/ft8/sequencer.py:90-105 — Answering a decode addressed to us that carries only "73" reports success but leaves the sequencer idle. (carried from prior review)

[NOTE] docs/references.md:139-140 — "Starts up to 3 s late" counts from the period boundary; the most waveform skipped is about 2.5 s. (carried from prior review, low confidence)

[NOTE] /security NOTEs (see SECURITY.md): the author's full name as attribution in pyproject.toml, the About dialog, and the metainfo (deliberate; add to Accepted Risks if so); dependencies with lower bounds only and no lock file; the shared `/tmp/shots` path in CLAUDE.md:47.

### Fixes Applied

- [WARN] kx3rig/radio.py: `ptt(True)` refuses while a band, frequency, or mode change is queued or being applied; the change is kept. New `tuning_pending` property. tests/test_radio.py: the discard test was replaced with `test_never_keys_on_a_frequency_other_than_the_one_checked`.
- [WARN] kx3rig/controller.py: on a "watchdog" or "lost" link event, the data transmission in flight ends and its `on_done(False)` runs once (`_abort_data_tx`); operator halts stay silent. Test `test_watchdog_ends_data_transmission_and_reports_it_once` added.
- [WARN] kx3rig/controller.py, kx3rig/fakeradio.py: `can_transmit` refuses while SPLIT or XIT is on; the emulator reports both flags in its IF reply. Test `test_split_or_xit_blocks_transmit` added.

### Accepted Risks

- The author's name in pyproject.toml, the About dialog, the AppStream metainfo, and the LICENSE
  copyright line is deliberate open-source attribution.

---
*Prior review (2026-10-10): first-push review of the pre-scrub history (commit 2c3aebc); 1 BLOCK and 9 WARNs fixed, the personal-data-in-history WARN left for the operator's decision (now resolved on `main` by the history rewrite), and 15 NOTEs, most of which 75eb844 addressed.*

<!-- REVIEW_META: {"date":"2026-10-10","commit":"26f3355","reviewed_up_to":"26f33558b5ab0f05cc85dc1555e775d29e7a08ec","base":"4b825dc642cb6eb9a060e54bf8d69288fbee4904","tier":"full","block":0,"warn":1,"note":16} -->
