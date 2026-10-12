## Review — 2026-10-12 (commit: 58c7e53)

**Summary:** Light review of one unpushed commit on `main` (58c7e53, one ahead of `origin/main`): README.md, docs/custom-shack.md, and docs/looptune.md, 41 insertions and 20 deletions. `codereview-marker surface` is empty, so no code, configuration, or agent-instructing Markdown changed; tests, /security, external reviewers, the built-in review, and the fix loop were skipped. The three files were read in full and checked for broken links, secrets in prose, and factual accuracy. The new "Best practice, in short" section in docs/looptune.md matches the guide's code (`GOOD_SWR = 1.5` and the re-siting steps in kx3rig/ui/looptune.py, the `width / 2` retune threshold in kx3rig/looptune/state.py), the station's KXAT3 (docs/references.md:288), and the sources in docs/references.md. The `#the-procedure-and-why` anchor and both moved screenshots resolve. No secrets, callsigns, or locators were added; the commit removes the city from the README and custom-shack.md. No BLOCK or WARN.

**External reviewers:**
Skipped (light review).

**Built-in review:**
Skipped (light review).

### Findings

[NOTE] docs/looptune.md:22-23 — The summary gives the 20 m retune distance as 17 kHz. The table on line 68 says 17.5 kHz, and the code retunes beyond `width / 2` of the 35 kHz width (kx3rig/looptune/state.py:24-31, 82). The line says "about half", so the effect is small, but the two figures on one page disagree. Confidence: high on the mismatch.
  Evidence: "(5 kHz on 40 m, 17 kHz on 20 m)" against "| 20 m | 35 kHz | 8.75 kHz | 17.5 kHz |".
  Suggested fix: Write 17.5 kHz.

[NOTE] docs/looptune.md:12, 16-18 — The summary sets TUN PWR to 1.0 W and says to tune for "the brightest LED", but leaves out the caveat on lines 100-101 that the LED may be faint at 1 W on 40 m (raise TUN PWR to 2 or 3 W). A reader who stops at the summary, as the README now suggests (README.md:135-136), may not see the LED on 40 m. Confidence: medium that this matters; LED visibility at 1 W is still unverified at this station (docs/references.md:253-254).
  Evidence: Step 3 "Nudge the knob for the lowest SWR and the brightest LED" with no 40 m qualifier.
  Suggested fix: Add a clause to step 3, for example "(on 40 m the LED can be faint at 1 W; 2 or 3 W is fine)".

[NOTE] README.md:36; docs/custom-shack.md:9; docs/smartscan.md:132 — The docs disagree on how many sessions built Smartscan and Loop Tune. The README says "in one Claude Code session apiece". custom-shack.md says it "records how two of those features were made in one Claude Code session". These lines predate this commit, but the commit now points the README's readers to custom-shack.md for "How Smartscan and Loop Tune were built" (README.md:45-46), so they meet both claims. Confidence: medium that it is a contradiction; low on which count is right.
  Evidence: "in one Claude Code session apiece" against "how two of those features were made in one Claude Code session".
  Suggested fix: Settle on one count and use it in both files.

Carried from the prior entry, still present in the files this commit changed:
- [NOTE] docs/custom-shack.md:105 (was 106) — "The whole guide now runs, and is tested": `LoopTuneDialog` itself is still untested (no reference to it under tests/).
- [NOTE] README.md:140-141, 160; docs/screenshots/confirm.png — The confirmation now describes the loop and offers Tune Loop; confirm.png (last changed in cf707b3) shows the old dialog.

The prior entry's other NOTEs concern code already on `origin/main` that this commit does not touch. They were not re-checked here and remain open; the full list is in CODEREVIEW.md at e37e0ae.

### Fixes Applied

None.

### Accepted Risks

- The author's name in pyproject.toml, the About dialog, the AppStream metainfo, and the LICENSE
  copyright line is deliberate open-source attribution.
- The station's city and 4-character Maidenhead grid square (the Smartscan default grid, the
  README, the docs, the tests, and the scan screenshot) are published by the operator's decision
  (2026-10-12). Anything more precise, such as a 6-character subsquare, stays out of the repo.

---
*Prior review (2026-10-12, commit 26f1c86): full review of the `smartscan` branch after its history rewrite. Three WARNs (the Loop Tune guide on non-loop bands, the heard list cleared on restart, stale loop advice after a sweep) were fixed by /codefix and committed in e37e0ae; the fixes are present (`_heard_for` in kx3rig/smartscan/engine.py, `LoopTuner.refresh` and the "doesn't cover" refusal in kx3rig/looptune/tuner.py). 0 BLOCK, 51 NOTEs.*

<!-- REVIEW_META: {"date":"2026-10-12","commit":"58c7e53","reviewed_up_to":"58c7e53fb8394d5a0455cb9d9c5656af5402176b","base":"origin/main","tier":"light","block":0,"warn":0,"note":5} -->
