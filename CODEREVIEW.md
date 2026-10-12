## Review — 2026-10-12 (commit: 26f1c86)

**Summary:** Full review of the unpushed `smartscan` branch after its history rewrite (0b9297d to 26f1c86, seven commits ahead of `origin/main`). The branch has no upstream, so the push gate's base is the empty tree and the diff is the whole tree (96 files). The 46 files that differ from `origin/main` were read in full. The 50 identical to `origin/main` are already public and covered by earlier reviews; they were checked only where the new code calls them. Not a refresh review: the prior entry's commit (00fda49) is not an ancestor of HEAD after the rewrite. Baseline tests: 335 passed, 7 skipped (the skips are WSJT-X round trips, with no `jt9` on this Mac), run with Homebrew's PyGObject on PYTHONPATH because this checkout's `.venv` was made without `--system-site-packages`. The prior BLOCK (the station's location) is resolved by the operator's Accepted Risks entry and the rewrite, which took the 6-character subsquare out of the tree and the branch history. Three new WARNs, all fixed by one /codefix cycle in the working tree (not committed). Tests went to 338 passed, 7 skipped (3 new). /security re-checked the six changed files: 0 BLOCK, 0 WARN, 12 NOTE.

**External reviewers:**
None configured.

**Built-in review:**
`/code-review high`: 10 findings, 10 kept after Step 6.

### Findings

Line numbers are as found at 26f1c86, before the fixes.

[WARN, fixed] kx3rig/ui/radio_page.py:75-79, 327-332; kx3rig/looptune/tuner.py:81-89; kx3rig/ui/window.py:186-200 — The Loop Tune guide opens on bands the AlexLoop does not cover (160, 80, 60, 6 m). docs/looptune.md:54-55 says the tag reads "No Loop Band" there "and the guide is off". Only the Loop row's button is made insensitive (radio_page.py:355). The Loop tag stays visible and clickable on those bands (radio_page.py:343) and calls `open_loop_tune()`. Changing band during a sweep always shows "Tune the loop for <band>, then Smartscan carries on there." with a Tune Loop button (radio_page.py:327-332), whatever the target band. `open_refusal` checks only transmitting and the FT8 engine. The guide then tells the operator to set the knob near the band's mark and to hold XMIT for TUNE, on a band the antenna cannot resonate on. Nothing transmits by itself. (also claude-code)
  Evidence: `loop_tag.connect("clicked", lambda b: self.open_loop_tune())` with `set_visible(connected and n.band is not None)`; `_on_band_toggled` calls `_prompt_loop(..., then_scan=True)` unconditionally; `open_refusal` has no band check.
  Suggested fix: Refuse in `LoopTuner.open_refusal` when `looptune.state.covers(band_for(dial))` is false ("The AlexLoop doesn't cover 80 m."), so every path is covered and testable without a display. In `_on_band_toggled`, prompt only when the target band is covered; otherwise just stop the sweep. Add a test for the refusal.

[WARN, fixed] kx3rig/smartscan/engine.py:148-152 — Restarting Smartscan can clear the heard list on the same band and sweep. `start()` decides whether to clear from `heard.entries[0].kind`, but a voice sweep also records CW hearings (and a CW sweep voice ones), because `_finish_step` stores each contact with its detection's kind (engine.py:355-361). When the first entry is the other kind, stopping and starting the same sweep wipes the list, its clips, the noise curve, and the carriers. That breaks "Stations heard stay listed for 15 minutes" (ui/smartscan.py:393) and docs/smartscan.md:26. Entries are also re-sorted by recency once there are more than 12 (heard.py:84-87), so `entries[0]` can be any kind. (also claude-code)
  Evidence: `if self.heard.entries and self.heard.entries[0].kind != plan.kind or not self._same_band(plan): self.heard.clear()`.
  Suggested fix: Remember the band and kind of the plan the list was built from (for example `self._heard_for = (plan.band.name, plan.kind)`, set in `start()`), and clear only when that changes. Test: a CW entry first in a voice sweep, stop, start the same sweep, assert the list is kept.

[WARN, fixed] kx3rig/looptune/tuner.py:151-155; kx3rig/smartscan/engine.py:175-194; kx3rig/ui/window.py:276-281 — The loop advice can stay stale after Smartscan stops without restoring. `_on_radio` skips `_refresh_need` while `station.scanning`, and nothing recomputes it when the sweep ends. When the operator turns the VFO during a sweep, the frequency change arrives while scanning is still true, then Smartscan stops ("you tuned the radio", restore=False) and sends nothing. Until some other radio field changes, the Loop tag and `confirm_transmit` use the advice from before the sweep. On a band already confirmed, `confirm_transmit` then keys at once (window.py:279-281) without the retune warning or the Tune Loop response, in exactly the case the operator just tuned to a station heard on the sweep. The same applies to the "mode changed" stop. (claude-code)
  Evidence: Reproduced on the emulator with a steady S-meter (as on a quiet band): loop marked tuned at 14.300, Smartscan started, VFO moved to 14.200, Smartscan stopped with "you tuned the radio". 3 s later `tuner.need.level` was still "tuned" while `tuner._compute().level` was "retune". With the emulator's wandering S-meter the next SM poll refreshes it, which is why the existing tests pass.
  Suggested fix: Recompute the advice when scanning ends: for example a public `LoopTuner.refresh()` called when Smartscan stops (from the Radio view's Smartscan "changed" handler, or by passing the tuner to Smartscan), and have `confirm_transmit` use `need_for(st.frequency)` rather than the cached value. Test it on the emulator with the S-meter held steady.

New NOTEs:

[NOTE] kx3rig/ui/waterfall.py:162-170; kx3rig/smartscan/engine.py:307-313, 353 — A quick-listen outline stays on the waterfall when the confirm listen rejects it, or measures its low edge more than 300 Hz away. `mark()` removes an earlier mark only when a new span at the same `t_start` starts within 300 Hz, and a confirm that finds nothing passes no spans. A false "Voice" box, or a duplicate, scrolls down the waterfall. Suggested: when a dwell is re-reported, drop every mark with the same `t_start` before adding the new spans. (claude-code)
[NOTE] kx3rig/smartscan/engine.py:258-314 — `_tick` has no exception guard. An unexpected exception in `detect`, `_finish_step`, or the plan math makes PyGObject remove the timer while `active` and `station.scanning` stay true: the toggle shows a sweep that is not running, and every transmit is refused until Stop or Esc. It fails closed. Suggested: catch, log, and `stop()` with a reason. (also claude-code)
[NOTE] kx3rig/ui/radio_page.py:66; kx3rig/smartscan/engine.py:290-314 — The frequency readout tunes during a sweep without stopping Smartscan first, unlike the band and mode buttons (radio_page.py:327-329, 385-386). While the operator's FA is still queued, `settled` is false, so the tick skips the takeover check and can finish the step; `_tune_step` then replaces the queued frequency (radio.py:203-207), the operator's tune is lost, and the sweep carries on. Benign, and the window is short. Low confidence on how often it happens over the real link.
[NOTE] kx3rig/audio.py:238-337 — `ClipPlayer` repeats `DataTransmit`'s one-shot appsrc lifecycle, and the copies already differ: `DataTransmit.stop()` runs `on_done`, `ClipPlayer.stop()` does not. (claude-code)
[NOTE] kx3rig/smartscan/engine.py:299-300; kx3rig/looptune/tuner.py:91-94 — Every 50 ms tick concatenates up to 5 s of audio only to compare its length with the target; summing chunk lengths would do. `mark_tuned` emits "need-changed" twice. (claude-code)
[NOTE] kx3rig/smartscan/plan.py:58-61; kx3rig/smartscan/heard.py:5-6 — `Plan.tune_mode` is now used only by tests (the engine uses `mode_for`). heard.py's docstring says each entry keeps the clip from its strongest hearing; `add()` now also replaces a clip older than CLIP_REFRESH_S.
[NOTE] kx3rig/ui/radio_page.py:329-337 (post-fix); docs/smartscan.md:99 — Introduced by the fix. Changing to a band the loop does not cover during a sweep now stops Smartscan with no toast or reason, and docs/smartscan.md:99 still says a band change "offers Loop Tune". Suggested: stop with a reason (for example "Smartscan stopped for the band change.") and qualify the doc line to loop bands.
[NOTE] refs/heads/backup/smartscan-pre-scrub (local) — The local backup branch still holds the pre-rewrite commits, one of which carries the 6-character subsquare. A plain `git push` of `smartscan` does not send it; `git push --all`, `--mirror`, or pushing it by name would, irreversibly. Suggested: delete it once the rewritten branch is confirmed. (/security)

Carried from the prior entry, still present (updated where re-checked):
- [NOTE] kx3rig/smartscan/engine.py:59, 108, 221-231, 301 — Audio buffer trimmed by wall-clock timestamps only; a backward clock step grows it and replays stale audio into later steps. Re-reproduced: 310.5 s (14.9 MB) held after a 600 s step. (/security, also found inline)
- [NOTE] kx3rig/smartscan/engine.py:245-256; kx3rig/radio.py:516-519 — A sweep step can send `FA` during a transmission keyed at the radio, before the next poll shows it. (/security)
- [NOTE] kx3rig/smartscan/conditions.py:118, 164-167; kx3rig/ft8/grid.py:14-17 — One PSKReporter report with a non-ASCII digit in its sender locator discards the whole fetch. (/security)
- [NOTE] kx3rig/audio.py:305-306; kx3rig/controller.py:504-511 — A sink named "auto" takes the unpinned `autoaudiosink` path; in demo mode a clip does not mute the demo's own listening audio. (/security)
- [NOTE] kx3rig/app.py:109; kx3rig/smartscan/engine.py:395-397; kx3rig/ui/smartscan.py:432-433; kx3rig/screenshots.py:66-79 — Demo mode loads the real settings, so `--demo --screenshot` can put the configured grid (and, in the FT8 view, the callsign) in committed PNGs. Since the station's square is now published, this matters when the configured grid differs from it. (/security)
- [NOTE] kx3rig/app.py:146-147 — Quitting during a sweep stops Smartscan without restoring, leaving the KX3 on a sweep step in the scan mode. (also claude-code)
- [NOTE] kx3rig/ui/looptune.py:132-135, 290-301 — Opening the guide during a sweep builds the peak page from the sweep step's frequency before the restore lands. (also claude-code)
- [NOTE] kx3rig/smartscan/engine.py:340-344; kx3rig/looptune/tuner.py:110-111 — `_find` re-implements `HeardList.add`'s match with a different tie rule; `restart_meter` is used only by a test. (also claude-code)
- [NOTE] kx3rig/smartscan/plan.py:123-132 — One sweep step can put the dial a little outside the band edge (receive only; the band tag reads "Out of band" for that step).
- [NOTE] kx3rig/looptune/tuner.py:156 — When KX3-Rig unkeys, `ptt` drops before `transmitting`, so its own carrier can briefly count as the operator's TUNE. Corner case now that the guide refuses while anything can key.
- [NOTE] docs/live-test.md:4-5 — Says steps 1, 2, and 5 never transmit and 3-4 do; section 6 also transmits (the operator's TUNE).
- [NOTE] kx3rig/smartscan/conditions.py:43 — The User-Agent sends the app name, version, and repository URL, which the network rule and the Privacy section do not mention.
- [NOTE] docs/custom-shack.md:106 — "The whole guide now runs, and is tested": `LoopTuneDialog` itself is untested.
- [NOTE] README.md:140, 161; docs/screenshots/confirm.png — The confirmation now describes the loop and offers Tune Loop; confirm.png shows the old dialog.
- [NOTE] SECURITY.md — One personal-data NOTE (a 4-character locator prefix, location withheld) may now be covered by the operator's location decision; /security did not check. Keep precise locations out of committed review files. (/security)
- [NOTE] kx3rig/devices.py:30, 77-80, 202-213; kx3rig/controller.py:410-437 — Digirig recognized by node name alone. (/security)
- [NOTE] kx3rig/controller.py:231-233; kx3rig/radio.py:203-207, 253-260, 408-413, 507-511 — Key-down windows (SPLIT and XIT not in `ptt`, a `?;` reply to a frequency SET, CONNECTED before IF). (/security)
- [NOTE] kx3rig/radio.py:546-550; kx3rig/ft8/engine.py:128-133 — A stale known submode passes for about one DT poll. (/security)
- [NOTE] kx3rig/bandplan.py:187, 213, 284 — `tx_check`, `privilege_segments`, and `scan_ranges` default `license_class` to "General"; every caller passes the setting. (/security)
- [NOTE] install.sh:27-28, constraints.txt:5-8 — pip and the setuptools build backend are unpinned; no hashes. (/security)
- [NOTE] kx3rig/controller.py:229-231, 428-437; kx3rig/audio.py:38-45 — `default_node_name` runs `wpctl inspect` synchronously on the main loop (3 s timeout), now also from `play_clip`. (also claude-code)
- [NOTE] kx3rig/controller.py:257, 435 — The microphone and listen-sink fallbacks read the cached `_audio_nodes` (up to 2 s old). (also claude-code)
- [NOTE] kx3rig/controller.py:134-145, kx3rig/devices.py:172-193 — `shutdown` cannot cancel a `pw-dump` scan in flight. (claude-code)
- [NOTE] kx3rig/devices.py:167 — The 2 s `pw-dump` poll; measured cost negligible. (claude-code)
- [NOTE] install.sh:12-15 — No check for `pw-dump` or `wpctl`. Low. (claude-code)
- [NOTE] docs/references.md:302 — "before WSJT-X ran today" is still undated.
- [NOTE] docs/screenshots/connect.png — Still predates the d70f14d layout change.
- [NOTE] kx3rig/ui/connect_page.py:55-67, 183-184, 227-230, kx3rig/ui/style.css:87-89 — The plug-to-jack mapping is written four times; nothing checks that `JACK_ROW` and `PLUGS` agree. (also claude-code)
- [NOTE] kx3rig/ui/connect_page.py:231, 233-302 — The `notify::dark` handler is never disconnected. (claude-code)
- [NOTE] kx3rig/ui/connect_page.py:204 — The diagram row may take keyboard focus (low confidence). (claude-code)
- [NOTE] kx3rig/ui/connect_page.py:59 — KEY is labeled "leave empty" (low confidence).
- [NOTE] kx3rig/config.py:79-81 — The whole-watt clamp raises a hand-edited ceiling below 1 W to 1 W.
- [NOTE] kx3rig/radio.py:277-286 — `_update` calls `on_state` after releasing `_state_lock`, so snapshots can queue out of order (fails closed).
- [NOTE] kx3rig/controller.py:271-279 — Voice reports a frequency or mode mismatch as a push-to-talk failure.
- [NOTE] kx3rig/ft8/engine.py:309-315 — Each refused retry rebuilds the transmit buffer on the main thread.
- [NOTE] kx3rig/ui/radio_page.py — The power scale shows the clamped limit when the radio is above it; its range is fixed at startup.
- [NOTE] kx3rig/ft8/engine.py:132 — Comment cites OM p.18 for other submodes; docs/references.md does not record it.
- [NOTE] kx3rig/controller.py:373-380 — `_abort_data_tx` cannot tell which transmission an idle-queued event belongs to (low confidence).
- [NOTE] kx3rig/radio.py:232-234, 561-569, kx3rig/config.py:69-74, kx3rig/controller.py:83, 364-380 — Code quality items (redundant `_Pending` reset, duplicated tuning-field list, separate finite check, `_abort_data_tx` duplication).
- [NOTE] docs/references.md:6, 22-24 — references.md cites private notes.
- [NOTE] install.sh:31 — `Exec=` substituted unquoted; a path containing `|` breaks sed.
- [NOTE] kx3rig/ft8/sequencer.py:90-105 — Answering a "73"-only decode reports success but leaves the sequencer idle.
- [NOTE] docs/references.md:155-156 — "Starts up to 3 s late" counts from the period boundary (low confidence).

Resolved since the prior entry: the location BLOCK (operator's Accepted Risks entry; the 6-character subsquare was replaced and rewritten out of the branch history, confirmed by /security), and the nine WARNs fixed in that run, now committed in 26f1c86 and re-checked here.

### Fixes Applied

All by /codefix, one cycle, uncommitted in the working tree. Three new tests. /security re-checked all six changed files (no new findings).

- [WARN] kx3rig/looptune/tuner.py, kx3rig/ui/radio_page.py — `open_refusal` refuses with "The AlexLoop doesn't cover <band>." when the dial's band is not a loop band, covering the Loop tag, the Loop button, and the toast. A band change during a sweep prompts for Loop Tune only on loop bands. (also claude-code)
- [WARN] kx3rig/smartscan/engine.py — The heard list remembers the (band, kind) it was built for in `_heard_for` and is cleared only when that changes; `_same_band` was removed. (also claude-code)
- [WARN] kx3rig/looptune/tuner.py, kx3rig/ui/radio_page.py, kx3rig/ui/window.py — New `LoopTuner.refresh()`, called on Smartscan's "changed" signal, recomputes the advice once no sweep runs. `confirm_transmit` uses `need_for(st.frequency)` instead of the cached advice. The test holds the emulator's S-meter steady. (claude-code)

### Accepted Risks

- The author's name in pyproject.toml, the About dialog, the AppStream metainfo, and the LICENSE
  copyright line is deliberate open-source attribution.
- The station's city and 4-character Maidenhead grid square (the Smartscan default grid, the
  README, the docs, the tests, and the scan screenshot) are published by the operator's decision
  (2026-10-12). Anything more precise, such as a 6-character subsquare, stays out of the repo.

---
*Prior review (2026-10-11, commit 00fda49, before the history rewrite): full review of the Smartscan and Loop Tune branch. Nine WARNs fixed by /codefix (since committed as 26f1c86); one BLOCK left for the operator, the publication of the station's location, since resolved by the Accepted Risks entry and the rewrite. 44 NOTEs.*

<!-- REVIEW_META: {"date":"2026-10-12","commit":"26f1c86","reviewed_up_to":"26f1c86bdf1ab7cb74ed91b68a0c1623d617df41","base":"origin/smartscan","tier":"full","block":0,"warn":3,"note":51} -->
