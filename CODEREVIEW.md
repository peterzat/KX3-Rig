## Review — 2026-10-11 (commit: 85228ff)

**Summary:** Refresh review of 85228ff ("Add a cable guide to the Connect Your Radio page"), the one commit ahead of `origin/main` (5 files: README.md, docs/references.md, docs/screenshots/connect.png, kx3rig/ui/connect_page.py, kx3rig/ui/style.css). The cabling facts match docs/references.md and the station's bring-up notes (KX3-Digirig-Ubuntu references.md and README, "confirmed on the unit"). The one WARN, about the jack drawing ignoring text size, was fixed in one /codefix cycle and verified by a headless render. The fix is uncommitted in kx3rig/ui/connect_page.py. /security found nothing new, before or after the fix. Tests: 215 passed (baseline 215).

**External reviewers:**
None configured.

**Built-in review:**
`/code-review high`: 8 findings, 8 kept after Step 6 (merged into 1 WARN and 3 NOTEs).

### Findings

No open BLOCK or WARN. The one WARN is listed under Fixes Applied.

[NOTE] docs/screenshots/connect.png — The screenshot predates the WARN fix. The diagram row is now sized from its labels, so at the default window size it is about 8 px taller than shown. Regenerate it (`--demo off --screenshot`) when committing the fix if an exact match matters.

[NOTE] kx3rig/ui/connect_page.py:55-67, 183-184, 227-230, kx3rig/ui/style.css:87-89 — The plug-to-jack mapping is written four times in connect_page.py (`JACK_ROW`, `PLUGS`, the accessible label, and the NO_REPLY help text), and the plug colors twice (`PLUG_RGB` and the `.plug-dot` CSS). Nothing checks that `JACK_ROW` and `PLUGS` agree, and CLAUDE.md asks for tests in the same increment as a behavior change. Building the accessible label from `JACK_ROW` and adding a small test that both tables map each color to the same jack would catch drift. (also claude-code)

[NOTE] kx3rig/ui/connect_page.py:231, 233-302 — Code quality. The `notify::dark` handler on the `Adw.StyleManager` singleton is never disconnected and is likely redundant, because a light or dark switch changes the widget's CSS color and GTK redraws on that. There is one panel per window, so nothing accumulates. Each snapshot, and now each measure, also rebuilds its paths, strokes, attribute lists, and Pango layout; this runs only on resize or theme change, so the cost is negligible. (claude-code)

[NOTE] kx3rig/ui/connect_page.py:204 — The diagram row takes keyboard focus, so Tab stops on a row that does nothing. The checklist and plug rows on the same page behave the same way (standard boxed-list rows), and the accessible label sits on the panel, not the row. Low confidence that this matters. (claude-code)

[NOTE] kx3rig/ui/connect_page.py:59 — KEY is labeled "leave empty". The app offers CW (kx3rig/ui/radio_page.py:19), and a CW operator may have a paddle in KEY. "No Digirig plug" would say what is meant. Low confidence.

Carried, still present (code unchanged since the prior review; /security re-confirmed the first three on the emulator in this run):
- [NOTE] kx3rig/radio.py:248-259, 407-412, 504-508, kx3rig/controller.py:218-220 — Key-down windows: SPLIT and XIT are not compared in `ptt` (re-run in this scan: still keys), a `?;` reply to a frequency SET leaves the optimistic frequency, and `_handshake` publishes CONNECTED before IF, DT, and PC are read. Low likelihood in normal use. (/security)
- [NOTE] kx3rig/radio.py:543-547, kx3rig/ft8/engine.py:128-133 — A stale known submode or power passes for about one DT/PC poll (re-run in this scan: keyed at once on DATA A after a change to AFSK A, seen 0.60 s later). (/security)
- [NOTE] kx3rig/bandplan.py:187, 213 — `tx_check` and `privilege_segments` default `license_class` to "General". No caller omits it. (/security)
- [NOTE] install.sh:27-28, constraints.txt:5-8 — pip and the setuptools build backend are unpinned; no hashes. (/security)
- [NOTE] SECURITY.md records one personal-data NOTE without its location. Do not copy its location into committed files. (/security)
- [NOTE] kx3rig/config.py:77-79 — The whole-watt clamp raises a hand-edited ceiling below 1 W to 1 W.
- [NOTE] kx3rig/radio.py:277-286 — `_update` calls `on_state` after releasing `_state_lock`, so snapshots can queue out of order (fails closed).
- [NOTE] kx3rig/controller.py:260-265 — Voice reports a frequency or mode mismatch as a push-to-talk failure.
- [NOTE] kx3rig/ft8/engine.py:309-315 — Each refused retry rebuilds the transmit buffer on the main thread.
- [NOTE] kx3rig/ui/radio_page.py:121-122, 317-320 — Power scale shows the clamped limit when the radio is above it; range fixed at startup.
- [NOTE] kx3rig/ft8/engine.py:132 — Comment cites OM p.18 for other submodes; docs/references.md does not record it.
- [NOTE] kx3rig/ft8/grid.py:14 — `isdigit()` then `int()`, the pattern fixed in cat.py.
- [NOTE] kx3rig/controller.py:298-314, 356-363 — `_abort_data_tx` cannot tell which transmission an idle-queued event belongs to (low confidence).
- [NOTE] kx3rig/radio.py:232-234, 558-566, kx3rig/config.py:69-74, kx3rig/controller.py:83, 356-363 — Code quality items (redundant `_Pending` reset, duplicated tuning-field list, separate finite check, `_abort_data_tx` duplication).
- [NOTE] README.md:73, docs/references.md:6, 22-24 — README's first-transmit dialog description is out of date; references.md cites private notes.
- [NOTE] kx3rig/radio.py:548-549 — The previous `swr` shows briefly at the start of the next transmission.
- [NOTE] install.sh:31 — `Exec=` substituted unquoted; a path containing `|` breaks sed.
- [NOTE] kx3rig/ft8/sequencer.py:90-105 — Answering a "73"-only decode reports success but leaves the sequencer idle.
- [NOTE] docs/references.md:151-152 — "Starts up to 3 s late" counts from the period boundary (low confidence).

### Fixes Applied

- [WARN] kx3rig/ui/connect_page.py:221-252, 313-334 — `JackPanel` drew its labels at fixed pixel positions with a fixed 96 px height and no width limit. A headless render at the 380 px minimum window width showed that at text scale 1.25 (GNOME Large Text), "leave empty" overlapped "black plug" by 9.9 px and "green plug" by 11.9 px. The second label line also ran past the allocation to the row separator. At text scale 1.0 the gaps were only 2 to 5 px. The panel now measures itself height-for-width (`do_get_request_mode`, `do_measure`), and each label wraps (`WORD_CHAR`) and centers within its slot. The same `_labels` code measures and draws. Re-rendered at 380 px: no overlap at 1.0 or 1.25 (KEY's note wraps to "leave / empty"), and the row is 120 px and 129 px tall. At the default size and 1.25 the row is 110 px with no wrapping. (also claude-code)

### Accepted Risks

- The author's name in pyproject.toml, the About dialog, the AppStream metainfo, and the LICENSE
  copyright line is deliberate open-source attribution.

---
*Prior review (2026-10-10, commit 266a725): refresh review of the transmit-path hardening commit. It found 3 WARNs (the FT8 refusal counter carried across contacts, the retry repeating key-down after an audio failure, and untested unknown-value refusals), all fixed by /codefix and pushed as ba3bd59, and 20 NOTEs.*

<!-- REVIEW_META: {"date":"2026-10-11","commit":"85228ff","reviewed_up_to":"85228ffeedc697832058c069b38640779cf0eabe","base":"origin/main","tier":"refresh","block":0,"warn":0,"note":24} -->
