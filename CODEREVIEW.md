## Review — 2026-10-12 (commit: 35a3a25)

**Summary:** Light review of the one unpushed commit on `main` against `origin/main`: 35a3a25, a docs-only change to README.md (12 insertions, 10 deletions). It wraps seven screenshot `<img>` tags in `<p align="center">` (the pattern the wspr-map image already used) and breaks the example fork prompt into five shorter lines. `codereview-marker surface` is empty, so no tests, /security, external reviewers, built-in review, or fix loop ran. Checked: the prompt's words are unchanged, only its line breaks; all eight screenshot paths exist; the two images inside numbered steps (lines 169, 181) keep the 3-space indent, so they stay inside their list items, and a `<p>` HTML block ends at the following blank line as the `<img>` did; `git diff --check` is clean; no secrets or new location detail. pyproject.toml uses README.md as the package readme, but the change has no runtime effect.

**External reviewers:**
Skipped (light review).

**Built-in review:**
Skipped (light review).

### Findings

No new issues found.

The three NOTEs from the prior entry are still present (line numbers updated; README.md was not changed in these places beyond line breaks):

[NOTE] README.md:50, 62 — The repo is called "this agent-aware repo" (line 50) and "an agent-first repo" (line 62, linked) in consecutive paragraphs. The linked post uses "agent-aware" for data, not code, and chose "agent-first" over "agent-aware codebase" as the name. Confidence: medium.
  Evidence: line 50 `While this agent-aware repo is great for customizing setups similar to mine`; line 62 `[agent-first repo](https://agent-hypervisor.ai/posts/agent-first-repos/#fork-and-customize)`.
  Suggested fix: Say "agent-first repo" on line 50 as well, or drop the adjective there.

[NOTE] README.md:55 — The prompt still says "FCC Grid FN31". Grid squares are Maidenhead locators (an amateur-radio convention, as docs/smartscan.md:86 treats them), not an FCC designation. Confidence: high on the term.
  Evidence: `and matching the rig I run in FCC Grid FN31:`
  Suggested fix: For example, "a US (FCC-licensed) station in grid square FN31", which keeps the band-plan hint that "FCC" may be meant to carry.

[NOTE] README.md:55 and the linked post — The post's Fork and Customize section quotes the prompt with "FCC Grid CN87"; the README says FN31. The post calls it "a prompt along these lines", so this is not an error, and CN87 is published by the operator's decision (Accepted Risks). The post is outside this repo. Confidence: low that it matters.
  Evidence: post text `matching the rig I run in FCC Grid CN87`; README line 55 `FCC Grid FN31`.
  Suggested fix: None needed in the repo. Update the post's quoted prompt if the two should match.

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
*Prior review (2026-10-12, commit 0d1c5cf): light review of the README and custom-shack.md links to the Agent-First Repos post and the neutral FN31 grid in the fork prompt. It ended at 0 BLOCK, 0 WARN, 3 new NOTEs (agent-aware versus agent-first wording, "FCC Grid" as a term, and the post's quoted prompt still showing CN87), with 22 open NOTEs carried from d664373, and resolved the earlier one-shot NOTE.*

<!-- REVIEW_META: {"date":"2026-10-12","commit":"35a3a25","reviewed_up_to":"35a3a25c7ecaabec0e86469e0edeebd6f3bfcd53","base":"origin/main","tier":"light","block":0,"warn":0,"note":25} -->
