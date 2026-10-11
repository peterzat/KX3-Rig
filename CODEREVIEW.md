## Review — 2026-10-11 (commit: ff6ea82)

**Summary:** Refresh review of ff6ea82 ("Fix the window freezing once the Digirig's audio is streaming"), the one commit ahead of `origin/main` (7 files: README.md, docs/references.md, kx3rig/controller.py, kx3rig/devices.py, kx3rig/ui/connect_page.py, tests/test_devices.py, tests/test_station.py). Audio discovery moves from an in-process GStreamer DeviceMonitor to an asynchronous `pw-dump` subprocess with a 5 s timeout, and voice and listen routing read the cached result. The approach is sound and fails closed. One WARN, a scan busy flag that an unexpected exception could latch, was fixed in one /codefix cycle. That fix is uncommitted in controller.py, devices.py, and both test files. One WARN is left for the operator: the commit mixes concerns. /security found no BLOCK or WARN, before or after the fix. Tests: 227 passed (baseline 225; 2 added by the fix).

**External reviewers:**
None configured.

**Built-in review:**
`/code-review high`: 7 findings, 6 kept after Step 6 (merged into 1 WARN and 5 NOTEs). One was dropped as style (the closure `state` dict).

### Findings

[WARN] ff6ea82 (commit structure) — The commit mixes concerns. Besides the freeze fix (devices.py, controller.py, both test files, and references.md:96-99 and 169-170), it carries a troubleshooting copy change unrelated to the fix (connect_page.py:183-184, README.md:111, references.md:171-173) and a record of the first live session (references.md:163-168 and 177-179). The commit message discloses both ("Also records ... and leads the not-answering hint with reseating the plugs"), and they are small. Nothing is pushed yet, so splitting is cheap.
  Evidence: `git show --stat ff6ea82`: the NO_REPLY help text and the README troubleshooting row change wording only. They do not depend on the discovery change.
  Suggested fix: Operator action, not a code change. Split into a fix commit and a docs and copy commit before pushing. /codefix left it alone, because it needs a history rewrite.

[NOTE] kx3rig/devices.py:30, 77-80, 202-213, kx3rig/controller.py:403-411 — The Digirig is recognized by node name alone (`DIGIRIG_NODE_RE`). An audio node created by another program with `usb-C-Media` in its name, created before the Digirig appears, is picked first, because `pw-dump` lists nodes in creation order. Transmit audio would then go to it while RTS keys the radio, and receive audio would come from it. /security is confident in the code behavior but has low confidence that a sandboxed app can create such a node (not verified). Name matching predates this commit. Suggested hardening: refuse transmit when a scan finds more than one Digirig-named input or output, or match on device properties an app cannot set. (/security, post-fix)

[NOTE] kx3rig/controller.py:246, 418, kx3rig/audio.py:38-45 — `default_node_name` still runs `wpctl inspect` synchronously on the main loop with a 3 s timeout, from `start_talking` and from `_start_rx` (via `_listen_sink`, called from `_on_audio_nodes`). It is a separate process, so it cannot deadlock, but a slow PipeWire can still stall the window for up to 3 s. The `pw-dump` output already includes the `default` Metadata object (`default.audio.sink` and `default.audio.source`), so the defaults could come from the scan. The code is unchanged by this commit. (also claude-code)

[NOTE] kx3rig/controller.py:248, 422 — The microphone and listen-sink fallbacks now read the cached `_audio_nodes`, which is up to 2 s old, and older while scans fail. A headset plugged in just before push-to-talk can be missed, giving the "No microphone found" refusal (retry works). A microphone unplugged since the last scan fails closed. WirePlumber 0.4.17 does not fall back to the default source for a stream with `node.dont-reconnect` and a missing defined target; it destroys the node (/usr/share/wireplumber/scripts/policy-node.lua:718, 814-816, read this session). (also claude-code)

[NOTE] kx3rig/controller.py:128-137, kx3rig/devices.py:172-193 — `shutdown` cannot cancel a scan in flight, because `scan_audio_nodes` returns no handle. If the app quits while `pw-dump` hangs on a wedged PipeWire, the expiry timer never runs and the child outlives the app. Low likelihood. (claude-code)

[NOTE] kx3rig/devices.py:167 — The 2 s poll spawns `pw-dump` and parses the whole graph each time. On this machine one run took 0.01-0.02 s wall and produced 213 KB, which parsed in 1.8 ms to 4 audio nodes (measured this session). The cost is negligible. `pw-dump --monitor` would avoid it if it ever matters. (claude-code)

[NOTE] install.sh:12-15, README.md:54 — `install.sh` does not check for `pw-dump`. It ships in `pipewire-bin`, which the `pipewire` package depends on (apt-cache, this machine), so any system running PipeWire has it. `wpctl` (wireplumber) is unchecked too. Low. (claude-code)

[NOTE] docs/references.md:165-166 — `OM A-F----BX-02;` is described as "ATU and roofing filter fitted". By `cat.parse_om` (cat.py:278, offset 10), the `B` means the KXBC3 charger is also fitted, and the `X` at offset 11 is not decoded anywhere. Decode every flag from PR p.21, or say which ones are undecoded.

[NOTE] docs/references.md:178-179 — "before WSJT-X ran today" sits in the undated Open items list. "On 2026-10-11" keeps it accurate later.

From the 2026-10-11 cable-guide review (85228ff, fix pushed as d70f14d), still present:
- [NOTE] docs/screenshots/connect.png — still predates the d70f14d layout change (d70f14d did not update it).
- [NOTE] kx3rig/ui/connect_page.py:55-67, 183-184, 227-230, kx3rig/ui/style.css:87-89 — The plug-to-jack mapping is written four times and the plug colors twice. Nothing checks that `JACK_ROW` and `PLUGS` agree. This commit rewrote one of the four copies, the NO_REPLY help text. (also claude-code)
- [NOTE] kx3rig/ui/connect_page.py:231, 233-302 — The `notify::dark` handler is never disconnected and is likely redundant. Paths and layouts are rebuilt on each draw (negligible). (claude-code)
- [NOTE] kx3rig/ui/connect_page.py:204 — The diagram row takes keyboard focus (low confidence). (claude-code)
- [NOTE] kx3rig/ui/connect_page.py:59 — KEY is labeled "leave empty", but a CW operator may have a paddle there (low confidence).

Carried, still present:
- [NOTE] kx3rig/radio.py:248-259, 407-412, 504-508, kx3rig/controller.py:220-222 — Key-down windows: SPLIT and XIT are not compared in `ptt` (re-run by /security in this scan: the link saw SPLIT and XIT after about 0.2 s, the window's copy did not, and the emulator keyed), a `?;` reply to a frequency SET leaves the optimistic frequency, and `_handshake` publishes CONNECTED before IF, DT, and PC are read. (/security)
- [NOTE] kx3rig/radio.py:543-547, kx3rig/ft8/engine.py:128-133 — A stale known submode or power passes for about one DT/PC poll. (/security)
- [NOTE] kx3rig/bandplan.py:187, 213 — `tx_check` and `privilege_segments` default `license_class` to "General". The only caller (controller.py:223) passes the setting. (/security)
- [NOTE] install.sh:27-28, constraints.txt:5-8 — pip and the setuptools build backend are unpinned; no hashes. (/security)
- [NOTE] SECURITY.md records one personal-data NOTE without its location. Do not copy its location into committed files. (/security)
- [NOTE] kx3rig/config.py:77-79 — The whole-watt clamp raises a hand-edited ceiling below 1 W to 1 W.
- [NOTE] kx3rig/radio.py:277-286 — `_update` calls `on_state` after releasing `_state_lock`, so snapshots can queue out of order (fails closed).
- [NOTE] kx3rig/controller.py:262-267 — Voice reports a frequency or mode mismatch as a push-to-talk failure.
- [NOTE] kx3rig/ft8/engine.py:309-315 — Each refused retry rebuilds the transmit buffer on the main thread.
- [NOTE] kx3rig/ui/radio_page.py:121-122, 317-320 — Power scale shows the clamped limit when the radio is above it; range fixed at startup.
- [NOTE] kx3rig/ft8/engine.py:132 — Comment cites OM p.18 for other submodes; docs/references.md does not record it.
- [NOTE] kx3rig/ft8/grid.py:14 — `isdigit()` then `int()`, the pattern fixed in cat.py.
- [NOTE] kx3rig/controller.py:360-367 — `_abort_data_tx` cannot tell which transmission an idle-queued event belongs to (low confidence).
- [NOTE] kx3rig/radio.py:232-234, 558-566, kx3rig/config.py:69-74, kx3rig/controller.py:83, 351-367 — Code quality items (redundant `_Pending` reset, duplicated tuning-field list, separate finite check, `_abort_data_tx` duplication).
- [NOTE] README.md:73, docs/references.md:6, 22-24 — README's first-transmit dialog description is out of date; references.md cites private notes.
- [NOTE] kx3rig/radio.py:548-549 — The previous `swr` shows briefly at the start of the next transmission.
- [NOTE] install.sh:31 — `Exec=` substituted unquoted; a path containing `|` breaks sed.
- [NOTE] kx3rig/ft8/sequencer.py:90-105 — Answering a "73"-only decode reports success but leaves the sequencer idle.
- [NOTE] docs/references.md:155-156 — "Starts up to 3 s late" counts from the period boundary (low confidence).

### Fixes Applied

- [WARN] kx3rig/devices.py:187, kx3rig/controller.py:388-395 — The scan's busy flag was a latch that only `on_done` released. `finished` caught only `GLib.Error` and `ValueError`, so a `RecursionError` from deeply nested `pw-dump` output (reproduced offline by /security) or a `MemoryError` skipped `on_done` and stopped audio discovery for the rest of the session. `finished` now catches `Exception`, logs it, and reports `None`. `_check_audio` clears the flag if starting a scan raises, so the next tick retries. New tests: `test_scan_reports_none_when_parsing_raises_other_errors` and `test_audio_scan_that_fails_to_start_retries`. /security re-ran the original trigger after the fix (nesting 10,007 and 100,000 deep): `None` within 0.03 s, and the next scan starts. (also claude-code, /security)

### Accepted Risks

- The author's name in pyproject.toml, the About dialog, the AppStream metainfo, and the LICENSE
  copyright line is deliberate open-source attribution.

---
*Prior review (2026-10-11, commit 85228ff): refresh review of the cable-guide commit. Its one WARN (the jack drawing ignored text size) was fixed by /codefix and pushed as d70f14d; it left 24 NOTEs, no BLOCK or WARN open.*

<!-- REVIEW_META: {"date":"2026-10-11","commit":"ff6ea82","reviewed_up_to":"ff6ea825951f62a736bf134034d831500a20522c","base":"origin/main","tier":"refresh","block":0,"warn":1,"note":32} -->
