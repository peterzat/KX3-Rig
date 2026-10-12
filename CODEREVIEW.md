## Review — 2026-10-11 (commit: 00fda49)

**Summary:** Full review of the unpushed `smartscan` branch (7a365bb to 00fda49, six commits ahead of `origin/main`): Smartscan, Loop Tune, their UI, tests, docs, and screenshots. The branch has no upstream, so the push gate's base is the empty tree. 52 of the 96 files in that whole-tree diff are byte-identical to `origin/main`, already public and covered by earlier reviews; they were checked only for interactions with the new code. The 44 files that differ from `origin/main` got full review. One cycle of /codefix fixed all nine WARNs in the working tree; the fixes are not committed. Tests went from 321 passed, 7 skipped to 335 passed, 7 skipped (14 new; the skips are WSJT-X round trips, with no `jt9` on this Mac). The run used Homebrew's PyGObject on PYTHONPATH because this checkout's `.venv` was made without `--system-site-packages`. One BLOCK remains, an operator decision about publishing the station's location, so no push marker was written.

**External reviewers:**
None configured.

**Built-in review:**
`/code-review high`: 10 findings, 10 kept after Step 6.

### Findings

Line numbers are as found at 00fda49, before the fixes, except where noted.

[BLOCK] kx3rig/smartscan/conditions.py:5-7, 36; tests/test_smartscan_logic.py:175-248 (notably 216, 231-237, 244); tests/test_smartscan_engine.py:31 (post-fix); tests/test_looptune_tuner.py:29; docs/screenshots/scan-dark.png; README.md:19; docs/custom-shack.md:4; docs/smartscan.md:17, 70, 89, 139; docs/references.md:167 — The branch states the operator's city and that city's 4-character grid square. The tests also use a 6-character subsquare (tests/test_smartscan_logic.py:216, 244), which is more precise. SECURITY.md records that the operator's locator was scrubbed from history, and `origin/main` does not name the city. Once pushed, this cannot be taken back. **Operator decision; not for /codefix.** (/security, raised from WARN: irreversible on push)
  Evidence: /security's `git log -S` shows the values were added in 7a365bb, 908eaf0, 281bee0, and 00fda49. The values are deliberately not repeated here.
  Suggested fix: Choose one. (a) Keep it private: default the grid to empty, show "Set your grid square in Preferences" with no query until one is set (or use a neutral example square), use neutral locators in the tests (FN31pr is already used at tests/test_smartscan_logic.py:219), remove the city from code, tests, README, and docs, regenerate scan-dark.png, and rewrite the four commits so history does not carry the values. (b) Publish it: record the city-level location under Accepted Risks. Replace the 6-character test subsquare either way.

[WARN, fixed] kx3rig/controller.py:244-279, 302-358, 488-528; kx3rig/ui/smartscan.py:216-232, 336-352 — A Smartscan clip keeps playing during a voice transmission, and a new one can be started while keyed. `start_talking` and `play_data` never stop a clip, `play_clip` does not check `transmitting`, and the replay button stays sensitive. With the laptop mic and speakers, another station's recorded audio goes out on the air. This defeats the mute-while-transmitting rule at controller.py:470-473. (claude-code, also /security)
  Evidence: /security reproduced both orders on the emulator: with a clip playing, `start_talking()` was allowed and the clip kept playing; while talking, `play_clip()` returned "".
  Suggested fix: Stop any clip before keying in `start_talking` and `play_data`, and in `_on_radio_state` when the radio reports transmit. Refuse `play_clip` while `transmitting`. Make the replay buttons insensitive while keyed. Add a test.

[WARN, fixed] kx3rig/ui/window.py:186-199; kx3rig/ui/looptune.py:157-158, 178-179 — Loop Tune opens while an FT8 contact or CQ is in progress, and the FT8 engine keeps keying the radio on its slots. Meanwhile the guide says "Nothing is transmitted on this step" and has the operator's hand at the loop's knob. `open_loop_tune` checks only `station.transmitting` at that instant. `LoopTuneDialog` stops Smartscan but not the engine. `Smartscan.start` refuses the same case with "Finish the FT8 contact first." (smartscan/engine.py:126-127).
  Evidence: Nothing on the open path reads `engine.busy` or calls `engine.halt()`. The engine transmits from its own GLib timer (ft8/engine.py:218-230, 280-339) whatever view is shown.
  Suggested fix: In `open_loop_tune`, refuse with the same toast when `self.engine.busy` (or halt the engine and say so). Put the check somewhere a test can reach without a display, and test it.

[WARN, fixed] kx3rig/smartscan/engine.py:274-296, 106 — The listen phase has no timeout, and the engine never checks `station.audio.rx`. When receive audio stops mid-sweep (the rx error path at controller.py:455-460, or the Digirig's audio unplugged), the sweep sits on one step indefinitely. The status line still says "Sweeping" and every transmit is refused. A second, lower-confidence cause: `_samples` holds 2000 chunks, not a fixed duration, so very small PipeWire buffers could hold less than CLIP_S plus settle and stall the same way. (also claude-code)
  Evidence: On the emulator, after the demo audio was stopped, Smartscan was still active 8 s later with the same step index, phase "listen", and `can_transmit` refusing ("Smartscan is sweeping the band").
  Suggested fix: Stop with a reason (for example "Smartscan stopped: radio audio stopped.") when `station.audio.rx` is false, or when no new audio arrives within a couple of seconds of what the step needs. Bound `_samples` by duration. Add the emulator case as a test.

[WARN, fixed] kx3rig/controller.py:518-527; kx3rig/audio.py:287-337 — The clip player's error paths never stop the pipeline. `on_error` runs `done()`, which clears `_clip` but leaves the errored pipeline and its bus signal watch in place. If `player.start()` raises, the except branch drops the player without stopping it. Each failed replay leaks a pipeline. Compare `_on_rx_error` (controller.py:455-460) and `failed` in `play_data` (controller.py:327-332), which both stop theirs. (also claude-code)
  Suggested fix: Stop the player on the error path and in the except branch.

[WARN, fixed] kx3rig/controller.py:424-433, 488-528 — `play_clip` is a new path that sends audio to an output, and its "never the Digirig" invariant (CLAUDE.md, Audio) rests on `_listen_sink`. No test covers either: there is no test of `play_clip`, `_listen_sink`, or `default_node_name` routing.
  Suggested fix: Add tests that monkeypatch `audio.default_node_name` and `audio.ClipPlayer` and assert three things. A Digirig default with another sink present picks the other sink. A Digirig-only setup returns the refusal and builds no ClipPlayer. Live audio is muted during a clip and restored when it ends. Cover the transmit interaction from the first WARN too.

[WARN, fixed] kx3rig/smartscan/engine.py:133; kx3rig/smartscan/plan.py:115-117 — The plan sizes its audio window from `st.bandwidth`, which is read in the mode the radio is in before Smartscan switches to the scan mode. The link reads `BW;` after every mode change (radio.py:589-591), and the emulator keeps a bandwidth per mode (fakeradio.py:139: CW 400 Hz, USB 2800 Hz). So every start from CW mode sweeps about 3.4 times slower than designed, against docs/smartscan.md ("one step covers dozens of CW channels"). The reverse case, a wide filter in the starting mode and a narrow one in USB or LSB, would leave gaps. Whether the real KX3 keeps a bandwidth per mode was not verified here. (also claude-code)
  Evidence: On the emulator, starting from CW on 20 m planned 65 steps (audio_high 1100 Hz) while the radio then listened at 2800 Hz in USB. The same plan with the USB bandwidth is 19 steps.
  Suggested fix: When the starting mode differs from the scan mode, plan without the bandwidth, then rebuild once a `BW` reading in the scan mode arrives. Alternatively, pass the bandwidth only when the radio is already in the scan mode. Test: start from CW on the emulator and assert the step count.

[WARN, fixed] kx3rig/smartscan/engine.py:327; kx3rig/smartscan/plan.py:58-61 — Every hearing is stored with `plan.tune_mode`, whatever the detection's kind. A CW signal found during a voice sweep gets the sweep's sideband, with `tune_hz` on the signal, so Tune puts it at zero beat (inaudible). A voice detection during a CW sweep gets CW mode and its narrow filter. (claude-code)
  Evidence: For a 40 m voice plan (tune_mode LSB), a CW detection peaking at 1020 Hz audio from a 7.200 MHz dial gives tune_hz 7.198980 MHz, stored with mode LSB.
  Suggested fix: Choose the mode per detection: `Mode.CW` for "cw", the scan sideband for "voice". Test a CW detection in a voice plan.

[WARN, fixed] kx3rig/looptune/tuner.py:155-161; kx3rig/radio.py:548-549 — `best_swr` can be seeded from the previous transmission's SWR. After a transmission the link clears only `power_out` (radio.py:549). While keyed it reads TQ, then PO, then SW (radio.py:518-529). The first two state updates of a new key-down therefore carry the old `swr`. The guide then reports that stale value as the lowest SWR, and its Next button finishes on it (ui/looptune.py:378-381), marking the loop tuned. This happens only on firmware 2.93 and later, where SW is polled; this radio runs 2.38, where `swr` stays None. It makes the carried NOTE (the previous SWR shows briefly at the start of the next transmission) consequential. (claude-code)
  Suggested fix: Clear `swr` together with `power_out` when the link sees a transmission end. Alternatively, have LoopTuner ignore `swr` until it changes from the value present at key-down. Test with the emulator's `swr_source` and a firmware value of 2.93 or later.

[WARN, fixed] kx3rig/smartscan/engine.py:298-305; kx3rig/smartscan/heard.py:66-76 — `CLIP_REFRESH_S` never takes effect. `_needs_clip` compares the time with `entry.last_seen`, which `add()` updates on every hearing, so a station heard on every sweep (about once a minute) never reaches 300 s. Also, `add()` keeps a new clip only when the hearing is stronger. A station's replay stays its first clip for up to 15 minutes, against the stated intent at engine.py:55 ("record a new clip of a known station after this long"). (claude-code)
  Suggested fix: Record when the clip was taken (for example a `clip_at` field on `Heard`), test its age in `_needs_clip`, and let `add()` replace a clip older than `CLIP_REFRESH_S`. Test in test_smartscan_logic.py.

New NOTEs:

[NOTE] kx3rig/smartscan/plan.py:119-127 — On most bands, one sweep step puts the dial 300 to 2600 Hz outside the band edge. In USB the first CW step sits below the band edge (for example 13.9997 MHz for an Extra on 20 m). In LSB the last voice step sits above it (7.3002 and 7.3026 MHz on 40 m for a General). Receive only, so nothing is unsafe. During that step, though, the band tag reads "Out of band" and the band buttons clear. Clicking the current band's button at that moment stops the sweep and offers a loop retune for the same band (ui/radio_page.py:325-332). Whether `FA` just outside a band makes the KX3 switch its band memory, and its mode, is not verified. Suggested: clamp dials to the band, or add the check to live-test.md section 5.
[NOTE] kx3rig/ui/looptune.py:132-135, 290-301 — Opening the guide during a sweep stops Smartscan with restore, then builds the peak page at once from `station.radio`, which still holds the sweep step until the restore's idle callback runs. The page names the sweep frequency, and gives no CW hint when the origin was CW. The noise meter follows the real radio. (claude-code)
[NOTE] kx3rig/app.py:146-147 — Quitting during a sweep stops Smartscan without restoring, which leaves the KX3 on the sweep's dial and scan mode (for example USB instead of the operator's DATA or CW). (also claude-code)
[NOTE] kx3rig/looptune/tuner.py:146 — When KX3-Rig unkeys, `ptt` drops at once, but `transmitting` stays true until the next TQ reply. In that window `_on_radio` counts KX3-Rig's own carrier as the operator's TUNE, and its power goes into `max_power` (which drives the "TUNE is running at 5 W" warning). It shows only if the SWR page is open during a KX3-Rig transmission. Since the Loop Tune fix, the guide refuses to open while anything can key the radio, so this is now a corner case. Low confidence on the timing.
[NOTE] kx3rig/smartscan/engine.py:307-311; kx3rig/looptune/tuner.py:100-101 — `_find` re-implements the match in `HeardList.add` with a different tie rule (first match versus nearest), so `_needs_clip` can judge a different entry from the one the hearing updates. `restart_meter` is called only by a test. If the UI used it, `NoiseMeter.reset` on the main thread could race `feed` on the audio thread (IndexError at meter.py:70, caught and logged by `Station._on_samples`). (claude-code)
[NOTE] kx3rig/audio.py:305-306; kx3rig/controller.py:499-505 — The clip player treats the sink name "auto" as `autoaudiosink`, with no target and no `node.dont-reconnect`, so a Linux default sink named "auto" would take the unpinned path. In macOS demo mode it plays to the system default output; a Digirig is a USB audio device and can be that default. In demo mode `_rx` is None, so a clip does not mute the demo's own listening audio. Suggested: pass the platform default as a separate flag. (/security, also found inline)
[NOTE] kx3rig/app.py:109; kx3rig/smartscan/engine.py:362-364; kx3rig/ui/smartscan.py:422-425; kx3rig/screenshots.py:66-79 — Demo mode loads the real settings, and the Radio view now shows the grid, so `--demo --screenshot` can put the operator's grid in committed PNGs. Suggested: a fixed demo identity. (/security)
[NOTE] kx3rig/smartscan/engine.py:234-256; kx3rig/radio.py:514-517 — A sweep step can send `FA` during a transmission keyed at the radio, before the next poll shows it. /security saw it in 1 of 12 emulator trials, 0.14 s after key-down. Suggested: read TQ before applying queued tuning SETs in the link. (/security)
[NOTE] kx3rig/smartscan/conditions.py:118, 164-167; kx3rig/ft8/grid.py:14-17 — One PSKReporter report with a non-ASCII digit in its sender locator makes `int()` raise in `to_latlon`. The whole fetch is discarded and the panel says "Couldn't reach PSKReporter". This makes the carried grid.py `isdigit()` NOTE reachable from network data. Suggested: validate locators against an ASCII pattern and skip bad reports. (/security)
[NOTE] docs/live-test.md:4-5 — The intro says steps 1, 2, and 5 never transmit and steps 3-4 do, "starting with a dummy load". Section 6 also transmits: the operator holds TUNE into the loop.
[NOTE] kx3rig/smartscan/conditions.py:43 — The User-Agent sends the app name, version, and repository URL. CLAUDE.md's network rule ("Send nothing beyond the 4-character grid") and the README's Privacy section do not mention it. It identifies the app, not the operator. Low.
[NOTE] docs/custom-shack.md:106 — "The whole guide now runs, and is tested, without a radio": the tuner, meter, and state are tested, but `LoopTuneDialog` itself is not.
[NOTE] README.md:140, 161; docs/screenshots/confirm.png — The transmit confirmation now describes the loop's state and offers Tune Loop. confirm.png still shows the old dialog. This replaces the carried README.md:75 NOTE.
[NOTE] kx3rig/smartscan/engine.py:59, 108, 221-226, 301 (post-fix) — Introduced by the fix. The audio buffer is now trimmed by wall-clock timestamps (`time.time()`, audio.py:168) instead of the old 2000-chunk cap. If the clock steps backward, nothing is trimmed until it catches up. The buffer grows by about 48 KB/s, and each listen includes audio from before the step, so stations heard earlier reappear at later steps. /security reproduced it: after a 600 s backward step and 300 s more audio, the buffer held 310.5 s (14.9 MB). The new stall check uses the same clock, so a forward step of more than about 3 s during a listen stops the sweep with "radio audio stopped". That failure is safe. Low likelihood. Suggested: keep a hard size cap as a backstop, clear the buffer when a chunk is older than the newest one, and use `time.monotonic()` for the stall deadline. (/security post-fix, also found inline)
Carried from the prior entry, still present (updated where this diff touches them):
- [NOTE] kx3rig/devices.py:30, 77-80, 202-213; kx3rig/controller.py:406-422 — Digirig recognized by node name alone. Re-checked by /security; the clip path uses the same name test. (/security)
- [NOTE] kx3rig/controller.py:229-231, 424-433; kx3rig/audio.py:38-45 — `default_node_name` runs `wpctl inspect` synchronously on the main loop (3 s timeout). `play_clip` adds a caller through `_listen_sink`. (also claude-code)
- [NOTE] kx3rig/controller.py:257, 431 — The microphone and listen-sink fallbacks read the cached `_audio_nodes` (up to 2 s old). `play_clip` uses the same fallback. (also claude-code)
- [NOTE] kx3rig/controller.py:134-145, kx3rig/devices.py:172-193 — `shutdown` cannot cancel a `pw-dump` scan in flight. (claude-code)
- [NOTE] kx3rig/devices.py:167 — The 2 s `pw-dump` poll; measured cost negligible. (claude-code)
- [NOTE] install.sh:12-15 — No check for `pw-dump` or `wpctl`. Low. (claude-code)
- [NOTE] docs/references.md:302 — "before WSJT-X ran today" is still undated.
- [NOTE] docs/screenshots/connect.png — Still predates the d70f14d layout change.
- [NOTE] kx3rig/ui/connect_page.py:55-67, 183-184, 227-230, kx3rig/ui/style.css:87-89 — The plug-to-jack mapping is written four times; nothing checks that `JACK_ROW` and `PLUGS` agree. (also claude-code)
- [NOTE] kx3rig/ui/connect_page.py:231, 233-302 — The `notify::dark` handler is never disconnected. (claude-code)
- [NOTE] kx3rig/ui/connect_page.py:204 — The diagram row may take keyboard focus (low confidence). (claude-code)
- [NOTE] kx3rig/ui/connect_page.py:59 — KEY is labeled "leave empty" (low confidence).
- [NOTE] kx3rig/radio.py:248-259, 407-412, 504-508, kx3rig/controller.py:229-231 — Key-down windows (SPLIT and XIT not in `ptt`, a `?;` reply to a frequency SET, CONNECTED before IF). Re-checked by /security. (/security)
- [NOTE] kx3rig/radio.py:543-547, kx3rig/ft8/engine.py:128-133 — A stale known submode or power passes for about one DT/PC poll. (/security)
- [NOTE] kx3rig/bandplan.py:187, 213, 284 — `tx_check`, `privilege_segments`, and now `scan_ranges` default `license_class` to "General"; every caller passes the setting. (/security)
- [NOTE] install.sh:27-28, constraints.txt:5-8 — pip and the setuptools build backend are unpinned; no hashes. (/security)
- [NOTE] SECURITY.md carries one personal-data NOTE without its location; the BLOCK above bears on it. Keep locations out of committed review files. (/security)
- [NOTE] kx3rig/config.py:79-81 — The whole-watt clamp raises a hand-edited ceiling below 1 W to 1 W.
- [NOTE] kx3rig/radio.py:277-286 — `_update` calls `on_state` after releasing `_state_lock`, so snapshots can queue out of order (fails closed).
- [NOTE] kx3rig/controller.py:271-276 — Voice reports a frequency or mode mismatch as a push-to-talk failure.
- [NOTE] kx3rig/ft8/engine.py:309-315 — Each refused retry rebuilds the transmit buffer on the main thread.
- [NOTE] kx3rig/ui/radio_page.py — The power scale shows the clamped limit when the radio is above it; its range is fixed at startup.
- [NOTE] kx3rig/ft8/engine.py:132 — Comment cites OM p.18 for other submodes; docs/references.md does not record it.
- [NOTE] kx3rig/ft8/grid.py:14 — `isdigit()` then `int()`, the pattern fixed in cat.py (now reachable from PSKReporter data; see the new NOTE).
- [NOTE] kx3rig/controller.py:369-376 — `_abort_data_tx` cannot tell which transmission an idle-queued event belongs to (low confidence).
- [NOTE] kx3rig/radio.py:232-234, 558-566, kx3rig/config.py:69-74, kx3rig/controller.py:83, 360-376 — Code quality items (redundant `_Pending` reset, duplicated tuning-field list, separate finite check, `_abort_data_tx` duplication).
- [NOTE] docs/references.md:6, 22-24 — references.md cites private notes.
- [NOTE] install.sh:31 — `Exec=` substituted unquoted; a path containing `|` breaks sed.
- [NOTE] kx3rig/ft8/sequencer.py:90-105 — Answering a "73"-only decode reports success but leaves the sequencer idle.
- [NOTE] docs/references.md:155-156 — "Starts up to 3 s late" counts from the period boundary (low confidence).

Resolved since the prior entry: docs/references.md now decodes every `OM` flag (references.md:286-288); the radio.py:548-549 stale-SWR NOTE is folded into the Loop Tune SWR WARN above.

### Fixes Applied

All by /codefix, one cycle, uncommitted in the working tree. 14 new tests. The behavior tests were confirmed to fail against the old code. Two coverage tests (clip routing, and muting during a clip) pin existing behavior. /security re-checked all 12 changed files.

- [WARN] kx3rig/controller.py, kx3rig/ui/smartscan.py — The clip is stopped before keying in `start_talking` and `play_data`, and when the radio reports transmit. `play_clip` refuses while transmitting. The replay buttons go insensitive while keyed. (claude-code, also /security)
- [WARN] kx3rig/looptune/tuner.py, kx3rig/ui/window.py — The new `LoopTuner.open_refusal(ft8)` refuses while transmitting or while the FT8 engine is busy ("Finish the FT8 contact first."). `open_loop_tune` uses it.
- [WARN] kx3rig/smartscan/engine.py — The sweep stops with "Smartscan stopped: radio audio stopped." when `audio.rx` goes false or a step's audio is more than 3 s late. Kept audio is bounded to 10.5 s by time (see the post-fix NOTE). (also claude-code)
- [WARN] kx3rig/controller.py — The clip's error callback and the except branch now stop the player. (also claude-code)
- [WARN] tests/test_station.py — Tests for clip routing (never the Digirig), the Digirig-only refusal, muting live audio during a clip, the error paths, and clips stopped or refused while keyed.
- [WARN] kx3rig/smartscan/engine.py — The bandwidth is used only when the radio is already in the scan mode. Otherwise the sweep is re-planned once with the scan mode's filter, read from the link's state after the mode change. (also claude-code)
- [WARN] kx3rig/smartscan/plan.py, kx3rig/smartscan/engine.py — `Plan.mode_for(kind)` gives each hearing CW for a CW detection and the scan sideband for voice. (claude-code)
- [WARN] kx3rig/radio.py — TQ0 clears `power_out` and `swr`, the periodic clear includes `swr`, and PO and SW are polled only while still keyed. The new test showed that clearing alone was undone by a PO/SW poll after TQ0. (claude-code)
- [WARN] kx3rig/smartscan/heard.py, kx3rig/smartscan/engine.py — `Heard.clip_at` records when the clip was taken. `_needs_clip` tests the clip's age, and `add()` replaces a clip older than `CLIP_REFRESH_S`. (claude-code)

### Accepted Risks

- The author's name in pyproject.toml, the About dialog, the AppStream metainfo, and the LICENSE
  copyright line is deliberate open-source attribution.
- The station's city and 4-character Maidenhead grid square (the Smartscan default grid, the
  README, the docs, the tests, and the scan screenshot) are published by the operator's decision
  (2026-10-12). Anything more precise, such as a 6-character subsquare, stays out of the repo.

---
*Prior review (2026-10-11, commit 4067339): full review of the README hero photo commit, since pushed. No BLOCK or WARN; one NOTE (the photo shows a dummy load while the text describes the loop) and 32 carried NOTEs.*

<!-- REVIEW_META: {"date":"2026-10-11","commit":"00fda49","reviewed_up_to":"00fda49a1f9c937e3246fae4b06e448d922f193a","base":"origin/smartscan","tier":"full","block":1,"warn":0,"note":44} -->
