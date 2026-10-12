## Review — 2026-10-12 (commit: 0d1c5cf)

**Summary:** Light review of the one unpushed commit on `main` against `origin/main`: 0d1c5cf, a docs-only change (README.md and docs/custom-shack.md, 9 insertions, 4 deletions). It links the "Agent-First Repos" post from the README's fork paragraph and from custom-shack.md's closing section, and changes the example fork prompt's grid from the station's own CN87 to FN31. `codereview-marker surface` is empty, so no tests, /security, external reviewers, built-in review, or fix loop ran. Checked: both new URLs return 200 (fetched this session); the `#fork-and-customize` anchor exists as an `<h2 id>` on the page; custom-shack.md's definition matches the post's TL;DR ("a codebase built for a coding agent to develop, operate, and use, with humans supplying intent and judgment"); the README's "end state, rules, and verification travel with the fork" matches the post's Fork and Customize section; FN31 is a valid US Maidenhead square (41-42 N, 72-74 W), not the station's; no secrets or new location detail.

Resolved from the prior entry: the one-shot NOTE (README.md:59-61). The paragraph now cites the post's Fork and Customize section, which makes the same claim and reconciles it with the earlier post's one-shot ceiling: "From a blank prompt, that project sits well above the state-of-the-one-shot. From a fork, it sits comfortably inside it." The README's claim now matches its source. The grid half of the "FCC Grid" NOTE is also resolved (the prompt no longer hard-codes the station's square); the term half remains, below.

**External reviewers:**
Skipped (light review).

**Built-in review:**
Skipped (light review).

### Findings

[NOTE] README.md:50, 59-60 — The repo is now called two different things in consecutive paragraphs: "this agent-aware repo" (line 50, unchanged) and "an agent-first repo" (line 60, new, linked). The linked post uses "agent-aware" for data, not code ("Agent-aware data is complete, queryable, documented, and reachable"). It also says the author once considered "agent-aware codebase" as a name and chose "agent-first". A reader who follows the link meets the term for a different part of the pattern. Confidence: medium (the terms differ; whether line 50 should change is the author's call).
  Evidence: line 50 `While this agent-aware repo is great for customizing setups similar to mine`; line 60 `[agent-first repo](https://agent-hypervisor.ai/posts/agent-first-repos/#fork-and-customize)`.
  Suggested fix: Say "agent-first repo" on line 50 as well, or drop the adjective there.

[NOTE] README.md:54-55 (carried from the prior entry, term half only) — The prompt still says "FCC Grid FN31". Grid squares are Maidenhead locators (an amateur-radio convention, as docs/smartscan.md:86 treats them), not an FCC designation. The grid itself is no longer the station's own square. Confidence: high on the term.
  Evidence: `FCC Grid FN31: a <large computer controllable transceiver>, ...`
  Suggested fix: For example, "a US (FCC-licensed) station in grid square FN31", which keeps the band-plan hint that "FCC" may be meant to carry.

[NOTE] README.md:54-55 and the linked post — The README links the post's Fork and Customize section, which quotes the prompt with "FCC Grid CN87". The README now says FN31. The post introduces it as "a prompt along these lines", so the difference is not an error. The commit's goal of a neutral grid only holds within the repo, though: a reader who follows the link sees the station's square in the quoted prompt. CN87 is published by the operator's decision (Accepted Risks), so this is not a disclosure issue. The post is outside this repo. Confidence: low that it matters.
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
- [NOTE] README.md:206, docs/screenshots/confirm.png — confirm.png shows the old confirmation dialog.

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
*Prior review (2026-10-12, commit 1ebfe34): light review of the README fork prompt and the new "Make it yours" section. It ended at 0 BLOCK, 0 WARN, 2 new NOTEs (the one-shot claim against the cited post, and "FCC Grid CN87" as a term and a hard-coded grid), with 22 open NOTEs carried from d664373. This commit resolves the one-shot NOTE and the grid half of the other.*

<!-- REVIEW_META: {"date":"2026-10-12","commit":"0d1c5cf","reviewed_up_to":"0d1c5cff87adef73d09fc3ee1287d5e6bd4060d4","base":"origin/main","tier":"light","block":0,"warn":0,"note":25} -->
