## Review — 2026-10-12 (commit: 9ec21fc)

**Summary:** Light review of the two unpushed commits on `main` (58c7e53 and 9ec21fc, against `origin/main`): README.md, docs/custom-shack.md, and docs/looptune.md, 43 insertions and 21 deletions. `codereview-marker surface` is empty, so no code, configuration, or agent-instructing Markdown changed; tests, /security, external reviewers, the built-in review, and the fix loop were skipped. The three files were read in full and checked for broken links, secrets in prose, and factual accuracy. 9ec21fc resolves all three of the prior entry's new NOTEs: the summary now gives 17.5 kHz for 20 m (matching the table and `width / 2` in kx3rig/looptune/state.py), step 3 carries the faint-LED caveat, and the README's "both in a single Claude Code session" now agrees with docs/custom-shack.md:9 and docs/smartscan.md:132 (the commit times, 18:44 to 22:42 on 2026-10-11, fit one session). The `#the-procedure-and-why` anchor, the `docs/looptune.md` link, and the moved screenshots resolve. No secrets, callsigns, or locators were added. No BLOCK or WARN.

**External reviewers:**
Skipped (light review).

**Built-in review:**
Skipped (light review).

### Findings

[NOTE] docs/looptune.md:18-19 (also :101-102) — The faint-LED advice says to raise TUN PWR to "2 or 3 W". The guide warns when TUNE runs strictly above 3.0 W (`TUNE_POWER_WARN_W = 3.0` and `self.max_power > TUNE_POWER_WARN_W`, kx3rig/looptune/tuner.py:31, 158) and then tells the operator to set TUN PWR to 1.0 W (kx3rig/ui/looptune.py:371-373). `PO` reports tenths of a watt (docs/references.md:50), so a 3 W setting that reads 3.1 W would draw a warning that contradicts the doc, shown as "running at 3 W". Confidence: medium on the mismatch, low that it occurs; what `PO` reads during TUNE is unverified at this station (docs/references.md:253). The advice at lines 101-102 predates this push; the summary now repeats it where the README points readers.
  Evidence: "raise TUN PWR to 2 or 3 W" against `max_power > TUNE_POWER_WARN_W` with a 3.0 threshold.
  Suggested fix: Advise "about 2 W", or raise the warning threshold a little above 3 W (for example 3.5 W) so a 3 W setting does not trip it.

[NOTE] docs/looptune.md:17-18 — "working from behind the loop. Let go, check again, and tap XMIT to stop." "Let go" can read as releasing XMIT, which does not end TUNE (it latches; tap XMIT to leave, OM p.33 per docs/references.md:189-191). The same sentence says to tap XMIT, so the outcome is safe; the guide's own wording at line 45 ("Take your hand away") is clearer. Confidence: low that a reader is misled.
  Evidence: "Let go, check again" against "Take your hand away, check again" at line 45.
  Suggested fix: Write "Take your hand off the loop, check again, and tap XMIT to stop."

Carried from the prior entry, still present:
- [NOTE] docs/custom-shack.md:105 — "The whole guide now runs, and is tested": `LoopTuneDialog` itself is still untested (no reference to it under tests/; it appears only in kx3rig/ui/window.py and kx3rig/ui/looptune.py).
- [NOTE] README.md:140-141, 160; docs/screenshots/confirm.png — The confirmation now describes the loop and offers Tune Loop; confirm.png (last changed in cf707b3) shows the old dialog.

The NOTEs from the 26f1c86 full review concern code already on `origin/main` that these commits do not touch. They were not re-checked here and remain open; the full list is in CODEREVIEW.md at e37e0ae.

### Fixes Applied

None in this run. 9ec21fc, committed by the author before this review, fixed the prior entry's three NOTEs (17.5 kHz, the faint-LED caveat, the session count).

### Accepted Risks

- The author's name in pyproject.toml, the About dialog, the AppStream metainfo, and the LICENSE
  copyright line is deliberate open-source attribution.
- The station's city and 4-character Maidenhead grid square (the Smartscan default grid, the
  README, the docs, the tests, and the scan screenshot) are published by the operator's decision
  (2026-10-12). Anything more precise, such as a 6-character subsquare, stays out of the repo.

---
*Prior review (2026-10-12, commit 58c7e53): light review of the README tightening and the AlexLoop best-practice summary. 0 BLOCK, 0 WARN, 5 NOTEs; three (the 17 kHz figure, the missing faint-LED caveat, the session-count mismatch) are fixed in 9ec21fc, and two (the untested `LoopTuneDialog` claim, the stale confirm.png) remain.*

<!-- REVIEW_META: {"date":"2026-10-12","commit":"9ec21fc","reviewed_up_to":"9ec21fce7a6a1a122e5fa16ca9aed4f97d6ae15d","base":"origin/main","tier":"light","block":0,"warn":0,"note":4} -->
