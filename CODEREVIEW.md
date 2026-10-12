## Review — 2026-10-12 (commit: 1ebfe34)

**Summary:** Light review of the one unpushed commit on `main` against `origin/main`: 1ebfe34, a README-only change (36 insertions, 20 deletions) that ends the "Why this exists" section with an example Claude Code prompt for forking KX3-Rig to a different rig and moves the customizing, Smartscan and Loop Tune, and harness paragraphs into a new "Make it yours" section. `codereview-marker surface` is empty, so no tests, /security, or fix loop ran. Checked: every relative link and image target exists; the repo URL matches `origin`; the new `#what-i-think-is-durable` anchor resolves to the post's "What I Think Is Durable" heading (fetched this session); `xhigh` is a valid Claude Code effort level (`claude --help`); the only location detail is the 4-character grid CN87, which Accepted Risks covers; no secrets. The prior entry's commit-structure WARN no longer applies: those commits are on `origin/main`, outside the push set.

**External reviewers:**
Skipped (light review).

**Built-in review:**
Skipped (light review).

### Findings

[NOTE] README.md:59-61 — The paragraph says you would "expect to one-shot a working solution" because the repo acts as a "near oracle-level spec", and it links the cited post's "What I Think Is Durable" section. That post also has a section titled "The One-Shot Ceiling", which argues that complex projects cannot reliably be built in one pass ("the obstacle is architectural, not linguistic"). It defines an oracle as "a ground-truth reference, like Carlini's diff against the GCC torture suite", which is a verification tool, and it treats the spec as a separate idea. For a different transceiver, FakeKX3 is not ground truth; the new radio is. That radio cannot be checked inside the session, and CLAUDE.md requires hardware claims to come from sources or live checks. The "test it on your own equipment" caveat comes only in the next section, after a prompt for a 100 W setup. Confidence: medium (author's opinion about his own post; the tension with the cited text is factual).
  Evidence: "And you'd expect to one-shot a working solution. Why? Because the agentic pattern acts as a live and near [oracle-level](...#what-i-think-is-durable) spec".
  Suggested fix: Soften to a first working draft, or say what the one shot is expected to cover. Put the verification step (manuals, the emulator, then a dummy load with the operator present) in the same paragraph.

[NOTE] README.md:54-55 — The example prompt says "the rig I run in FCC Grid CN87". Grid squares are Maidenhead locators (an amateur-radio convention, as docs/smartscan.md:86 treats them), not an FCC designation. CN87 is the author's square, while the transceiver, amplifier, and antenna are `<placeholders>`, so a reader who copies the prompt asks for a fork located in Seattle. Confidence: high on the term; medium that the hard-coded grid is unintended.
  Evidence: `FCC Grid CN87: a <large computer controllable transceiver>, ...`
  Suggested fix: For example, "a US (FCC-licensed) station in grid square <your 4-character grid>", which keeps the band-plan hint that "FCC" may be meant to carry.

Open NOTEs carried from the prior entry (code already on `origin/main`, outside this diff, not re-checked; see that entry in git history for full detail):
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
- [NOTE] README.md:204, docs/screenshots/confirm.png — confirm.png shows the old confirmation dialog.

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
*Prior review (2026-10-12, commit d664373): full review of seven feature commits (SWR guard, FT8 wait, FT4, filters, Keyboard and WSPR views). It ended at 0 BLOCK, 1 WARN, 22 NOTE after /codefix made Tune Radio in the Keyboard and WSPR views refuse during an FT8 contact (committed as 68b0d90). The remaining WARN, commit structure, became moot when those commits were pushed.*

<!-- REVIEW_META: {"date":"2026-10-12","commit":"1ebfe34","reviewed_up_to":"1ebfe34975d3434fcfb44fa603c8aa08021cb9a9","base":"origin/main","tier":"light","block":0,"warn":0,"note":24} -->
