## Review — 2026-10-12 (commit: fcabcf4)

**Summary:** Light review of the one unpushed commit on `main` against `origin/main`: fcabcf4, a docs-only change to README.md and docs/custom-shack.md (18 insertions, 11 deletions). The README's "Why this exists" now calls the repo an agent-first codebase (linked to the post's `#agent-first-codebase` section) and lists five things that make it one; custom-shack.md adds the screenshot mode and design docs to its pattern list and moves its post link to the same anchor. `codereview-marker surface` is empty, so no tests, /security, external reviewers, built-in review, or fix loop ran. Checked against the repo: docs/references.md marks unsettled items **UNVERIFIED** (7 occurrences); `cat.ALLOWED` is enforced in the one serial write path (kx3rig/radio.py:382-384); `--screenshot` exists, requires `--demo` (kx3rig/app.py:237-242), and CLAUDE.md documents running it in a headless compositor; CLAUDE.md's Layout section points to docs/smartscan.md, docs/looptune.md, and docs/digital-modes.md; `git diff --check` is clean; no secrets or new location detail. Not checked: whether the post has an `#agent-first-codebase` anchor, because fetching the post was denied in this session.

**External reviewers:**
Skipped (light review).

**Built-in review:**
Skipped (light review).

### Findings

[NOTE] README.md:34 — "a design doc for each major feature in docs/" overstates the coverage. docs/ has design docs for Smartscan (smartscan.md), Loop Tune (looptune.md), and the digital modes (digital-modes.md: FT8/FT4, PSK31/CW, WSPR), but none for the core Radio page (tuning, waterfall, listening and talking, connection states), which docs/references.md covers only as sourced CAT and audio facts. Confidence: medium that a reader would count the Radio page as a major feature.
  Evidence: `- a design doc for each major feature in [docs/](docs/), which CLAUDE.md maps`; `ls docs/` lists custom-shack.md, digital-modes.md, live-test.md, looptune.md, references.md, smartscan.md.
  Suggested fix: Name the covered features ("design docs for Smartscan, Loop Tune, and the digital modes"), or say "for each mode and tool".

Carried from the prior entry:

[NOTE] README.md:61 — The prompt still says "FCC Grid FN31". Grid squares are Maidenhead locators (an amateur-radio convention, as docs/smartscan.md:86 treats them), not an FCC designation. Confidence: high on the term.
  Evidence: `and matching the rig I run in FCC Grid FN31:`
  Suggested fix: For example, "a US (FCC-licensed) station in grid square FN31", which keeps the band-plan hint that "FCC" may be meant to carry.

[NOTE] README.md:61 and the linked post — The post's Fork and Customize section quoted the prompt with "FCC Grid CN87"; the README says FN31. Not re-checked this run (the post could not be fetched). The post is outside this repo. Confidence: low that it matters.
  Evidence: README line 61 `FCC Grid FN31`.
  Suggested fix: None needed in the repo. Update the post's quoted prompt if the two should match.

Resolved since the prior entry: README.md now says "this agent-first repo" (line 56) where it said "agent-aware", so the wording matches the linked post's name throughout.

Open NOTEs carried from earlier entries (code already on `origin/main`, outside this diff, not re-checked; see the d664373 entry in git history for full detail):
- [NOTE] kx3rig/ft8/engine.py:257-261 — The faded-station wait can expire while the decode of its last period is still running, so a reply heard in that period is dropped. (claude-code)
- [NOTE] kx3rig/ft8/sequencer.py:221-234 — The "call" resume keeps the old stage and an old signal report. (claude-code)
- [NOTE] kx3rig/keyboard/engine.py:200-202, 239-241; kx3rig/keyboard/psk31.py:242-251 — `_drain` copies `_browser.channels` without the lock while the audio thread sorts it. (claude-code)
- [NOTE] kx3rig/wspr/engine.py:243-248 — The beacon's audio lead is computed before waveform synthesis, so audio starts late by that time. (claude-code)
- [NOTE] kx3rig/keyboard/engine.py:407-418; kx3rig/controller.py:245-250; kx3rig/smartscan/engine.py:129-132; kx3rig/looptune/tuner.py:93-96 — Duplication: `tune_radio` repeats `go_dial`, `go_ft8` has no callers, and `auto_keying()` is called twice with a redundant `ft8.busy` check. (claude-code)
- [NOTE] kx3rig/keyboard/engine.py:292-296, 312 — PSK31 `duration_s` is one character short. (also claude-code)
- [NOTE] kx3rig/ui/radio_page.py; kx3rig/ft8/engine.py:147-162 — The Radio page can still retune under an active FT8 contact, and `check_tx` does not require the protocol's dial. The WSPR view's guard has no test.
- [NOTE] kx3rig/screenshots.py:188, 194 — The keyboard screenshot plan's `tune_radio` call refuses if the "qso" plan's contact is still active. (/security)
- [NOTE] kx3rig/ui/ft8_page.py — A band or protocol change clears the decode list but not the waterfall labels.
- [NOTE] kx3rig/ft8/engine.py:467; kx3rig/ft8/adif.py:91-108; kx3rig/ft8/filters.py:67 — Worked-set lookups use `base_call()` against full logged calls, and Keyboard-view contacts reach `engine.worked` only after a restart. (also claude-code)
- [NOTE] kx3rig/ft8/adif.py:34-36 — `_field` writes a character count for a UTF-8 file.
- [NOTE] kx3rig/ui/ft8_page.py:191, 223; kx3rig/ft8/engine.py:155, 161 — Several labels are not FT4-aware. (also claude-code)
- [NOTE] kx3rig/ft8/ft4.py:187-203; kx3rig/wspr/engine.py:55, 76-79 — Duplicated parsing and band lookup; `PTT_LEAD_S` is unused.
- [NOTE] kx3rig/ui/keyboard_page.py:350-354; kx3rig/keyboard/varicode.py — Received PSK31 text can contain control characters, and GTK truncates at NUL.
- [NOTE] kx3rig/ui/wspr_page.py:258-259 — Changing "Transmit" during a beacon reseeds the scheduler.
- [NOTE] kx3rig/keyboard/engine.py:183-189 — `set_offset` is accepted while a message is going out.
- [NOTE] kx3rig/controller.py:181-195 — What `SW` reads between software-CW elements is unverified.
- [NOTE] tests/test_wspr_engine.py:115-135; tests/test_keyboard_engine.py:39-44 — Test isolation: the upload test relies on a `threading.Thread` patch, and the `kb` fixture uses the real log path. (/security)
- [NOTE] docs/looptune.md:18-19, 101-102 — The "2 or 3 W" TUN PWR advice can trip the guide's 3.0 W warning.
- [NOTE] docs/looptune.md:17-18 — "Let go" can read as releasing XMIT.
- [NOTE] docs/custom-shack.md:105 — Says the guide "is tested", but `LoopTuneDialog` has no test.
- [NOTE] README.md:208, docs/screenshots/confirm.png — confirm.png shows the old confirmation dialog.

The /security NOTEs are detailed in SECURITY.md (0 BLOCK, 0 WARN, 14 NOTE as of d664373). No code changed since that scan.

### Fixes Applied

None.

### Accepted Risks

- The author's name in pyproject.toml, the About dialog, the AppStream metainfo, and the LICENSE
  copyright line is deliberate open-source attribution.
- The station's city and 4-character Maidenhead grid square (the Smartscan default grid, the
  README, the docs, the tests, and the scan screenshot) are published by the operator's decision
  (2026-10-12). Anything more precise, such as a 6-character subsquare, stays out of the repo.

---
*Prior review (2026-10-12, commit 35a3a25): light review of centered README screenshots and a re-wrapped fork prompt. It ended at 0 BLOCK, 0 WARN, no new findings, with the 3 README NOTEs from 0d1c5cf (agent-aware versus agent-first wording, "FCC Grid" as a term, the post's prompt showing CN87) and 22 open NOTEs from d664373 carried forward.*

<!-- REVIEW_META: {"date":"2026-10-12","commit":"fcabcf4","reviewed_up_to":"fcabcf43d3863770933ab71a076090532cfd38b1","base":"origin/main","tier":"light","block":0,"warn":0,"note":25} -->
