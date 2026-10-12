## Review — 2026-10-12 (commit: d664373)

**Summary:** Full review of the seven unpushed commits on `main` against `origin/main` (c9f2670 through d664373). They add the SWR guard, waiting for faded FT8 stations, FT4, decode filters, waterfall callsigns, the PSK31 and CW modems and the Keyboard view, the WSPR engine and view, the one-keyer rule, their docs, and the prior review's fixes: 56 files, about 5,500 insertions. The refresh conditions failed because the history rewrite left the prior reviewed commit (548d7e0) off this branch, so every file got full-depth review. Tests ran under Homebrew python3.14 with the venv's site-packages on PYTHONPATH, because this Mac's .venv cannot import gi. Baseline: 437 passed, 10 skipped. After /codefix: 438 passed, 10 skipped, with no regressions and one new test. Two of the prior three WARNs are resolved: the regenerated ft4-dark.png reads 0 km for CN87, and the old blob is not in the push set (confirmed by /security); d664373 added the engine-level wait tests. /codefix fixed the one new WARN. The commit-structure WARN remains and needs the operator. The fix and SECURITY.md are uncommitted.

**External reviewers:**
None configured.

**Built-in review:**
`/code-review high`: 10 findings, 10 kept after Step 6. 4 matched existing NOTEs or this review's own; 6 were new. All were confirmed against the code, and all are NOTEs.

### Findings

Remaining:

[WARN] Commit structure (c9f2670, da063e7, 0b96cc5, 6c87961, fdf3ea7) — Carried from the prior review at its original severity, because it is not in Accepted Risks. The rewrite replaced only the screenshot, and these commits still mix concerns:
  - c9f2670 bundles the FT8 wait with the SWR guard.
  - da063e7 bundles the FT4 encoder with the PSK31 and CW modems.
  - 0b96cc5 ("Add FT4 to the FT8 view, ...") also adds kx3rig/wspr/protocol.py and tests/test_wspr_protocol.py, about 500 lines its message does not mention.
  - 6c87961 carries a Smartscan doc edit, and fdf3ea7 (docs) carries the Preferences name field and an FT8 engine message change. Both messages now say so.
  Confidence: high on the facts.
  Suggested fix: operator action. Split the history before pushing (at least move wspr/protocol.py and its test out of 0b96cc5), or record the decision to keep it under Accepted Risks. /codefix cannot do either.

Fixed in this run (see Fixes Applied):

[WARN] kx3rig/ui/wspr_page.py:289-298; kx3rig/keyboard/engine.py:407-418 — An FT8 or FT4 contact kept transmitting after the WSPR view or the Keyboard view retuned the radio. Each Tune Radio button checked only its own engine. `Ft8Engine._maybe_transmit` and `check_tx` (kx3rig/ft8/engine.py:147-162, 349-371) never require the FT8 dial. On the emulator, a contact keyed "W1AW N0CALL DM79" at 14.0971 MHz after a retune to the 20 m WSPR dial: the center of the WSPR window. After the Keyboard view's retune it keyed at 14.0715 MHz, in the PSK31 activity. Each transmission still passed the license check. Confidence: high (reproduced).

Notes:

[NOTE] kx3rig/ft8/engine.py:257-261 — The faded-station wait ends as soon as the period after `wait_until` begins, while the decode of the wait's last period can still be running. `_tick` then halts with "didn't come back", and `_on_decoded` finds `seq.waiting` false and drops a reply heard in that period. It happens when jt9 finishes after the period boundary: FT4 decodes from 6.2 s with 1.3 s left, and FT8 from 13.4 s with 1.6 s left. Confidence: high on the code; low impact, since only the wait's last period is affected. Suggested fix: expire the wait only when `_decoding_slot` is not the wait's last slot. (claude-code)

[NOTE] kx3rig/ft8/sequencer.py:221-234 — When a faded station is heard calling CQ or signing off, the "call" resume keeps the old stage. A contact that faded in REPORT or ROGER_REPORT therefore sends a signal report, measured minutes earlier, to a station that is calling CQ again, where a fresh Tx1 may serve better. Neither resume path refreshes `report_sent`. How WSJT-X Improved's Wait and Call handles this was not checked. Confidence: medium; this is a design question. (claude-code)

[NOTE] kx3rig/keyboard/engine.py:200-202, 239-241; kx3rig/keyboard/psk31.py:242-251 — `_drain` copies `_browser.channels` on the main loop without the lock, while the audio thread reassigns and sorts that list in `Browser._scan`. CPython empties a list during `sort` and runs the key function as Python code, so the copy can come back empty. The signal list then drops every row until the next update. Confidence: medium; rare and cosmetic. Copy the list under `self._lock`. (claude-code)

[NOTE] kx3rig/wspr/engine.py:243-248 — The beacon's audio lead is computed from the `now` taken at the start of the tick, after the 5.3-million-sample waveform was synthesized on the main loop (63 ms on this Mac, likely longer on the ThinkPad). Audio starts late by that time, and the window stalls for it. WSPR tolerates the offset. The waveform never changes during a beacon, so it can be built at start and the lead measured just before `play_data`. Confidence: high; low impact. (claude-code)

[NOTE] kx3rig/keyboard/engine.py:407-418; kx3rig/controller.py:245-250; kx3rig/smartscan/engine.py:129-132; kx3rig/looptune/tuner.py:93-96 — Duplication:
  - `KeyboardEngine.tune_radio` repeats `Station.go_dial`.
  - `Station.go_ft8` has no callers left.
  - Smartscan and Loop Tune call `auto_keying()` twice, and they keep a separate `ft8.busy` check that the registry already covers.
  Confidence: high. (claude-code)

[NOTE] kx3rig/keyboard/engine.py:292-296, 312 — `duration_s` for PSK31 measures `text + " "`, but `send` transmits `" " + text + " "`. The estimate and the MAX_TX_S check are one character (about 0.1 s) short. Confidence: high; negligible impact. (also claude-code)

[NOTE] kx3rig/ui/radio_page.py; kx3rig/ft8/engine.py:147-162; kx3rig/ui/wspr_page.py:293-296 — The retune fix covers the Keyboard and WSPR views. The Radio page's band buttons and frequency changes, which are already on origin, can still move the radio under an active FT8 contact. `Ft8Engine.check_tx` still does not require the protocol's dial. The WSPR view's new guard has no test because it lives in ui/. /security exercised it by hand on the demo radio. Confidence: high.

[NOTE] kx3rig/screenshots.py:188, 194 — The keyboard screenshot plan calls `tune_radio` directly, which now refuses while an FT8 contact is active. If the "qso" plan's contact is still in progress when the keyboard plan starts, psk31-dark.png would show the wrong frequency. The "ft4" plan already had the same dependency through `set_protocol`. Confidence: low; not checked by running the plans. (/security)

Carried from the prior entry, re-checked and still present:
- [NOTE] kx3rig/ui/ft8_page.py — A band change, or a switch between FT8 and FT4, clears the decode list but not the waterfall labels. Old-band callsigns stay on screen and can be double-clicked until the next decode.
- [NOTE] kx3rig/ft8/engine.py:467; kx3rig/ft8/adif.py:91-108; kx3rig/ft8/filters.py:67; kx3rig/ui/ft8_page.py — The worked set holds the full logged call, but lookups use `base_call()`, so a logged K1ABC/P never matches. Contacts logged from the Keyboard view reach `engine.worked` only after a restart. (also claude-code)
- [NOTE] kx3rig/ft8/adif.py:34-36 — `_field` writes a character count, but the file is UTF-8, so a non-ASCII "Their Name" gets the wrong length.
- [NOTE] kx3rig/ui/ft8_page.py:191, 223; kx3rig/ft8/engine.py:155, 161 — Several labels are not FT4-aware: the 50 Hz TX marker at startup, "Tune Radio to FT8", and "to transmit FT8". (also claude-code)
- [NOTE] kx3rig/ft8/ft4.py:187-203; kx3rig/wspr/engine.py:55, 76-79 — `parse_jt9_ft4_line` copies `decode.parse_jt9_line`, `wspr.engine.band_on_dial` repeats `Protocol.band_on_dial`, and `PTT_LEAD_S` in wspr/engine.py is unused.
- [NOTE] kx3rig/ui/keyboard_page.py:350-354; kx3rig/keyboard/varicode.py — Received PSK31 text can contain control characters, and GTK truncates at NUL.
- [NOTE] kx3rig/ui/wspr_page.py:258-259 — Changing "Transmit" while the beacon runs reseeds the scheduler, so two transmissions can land back to back.
- [NOTE] kx3rig/keyboard/engine.py:183-189 — `set_offset` is accepted while a message is going out. The waterfall marker and the logged frequency then follow the new offset.
- [NOTE] kx3rig/controller.py:181-195 — What `SW` reads between the elements of software CW is unverified.
- [NOTE] tests/test_wspr_engine.py:115-135; tests/test_keyboard_engine.py:39-44 — The WSPRnet upload test is guarded only by a patch of the global `threading.Thread`. The `kb` fixture builds `KeyboardEngine(station)` with the real log path. An autouse conftest fixture that redirects the XDG directories and blocks socket connects would cover both. (/security, widened this run)

The other /security NOTEs are detailed in SECURITY.md (0 BLOCK, 0 WARN, 14 NOTE).

Carried from earlier entries, not re-checked (the files are unchanged by this diff):
- [NOTE] docs/looptune.md:18-19, 101-102 — The "2 or 3 W" TUN PWR advice can trip the guide's warning above 3.0 W (kx3rig/looptune/tuner.py:31, 158).
- [NOTE] docs/looptune.md:17-18 — "Let go" can read as releasing XMIT, which does not end TUNE.
- [NOTE] docs/custom-shack.md:105 — The doc says the guide "is tested", but `LoopTuneDialog` has no test.
- [NOTE] README.md, docs/screenshots/confirm.png — confirm.png shows the old confirmation dialog.

### Fixes Applied

These are uncommitted in the working tree.
- [WARN] kx3rig/keyboard/engine.py:413-414; kx3rig/ui/keyboard_page.py:288-291; kx3rig/ui/wspr_page.py:293-296 — `KeyboardEngine.tune_radio` returns False while `station.auto_keying(exclude=self)` reports another activity. The Keyboard and WSPR views check the same first, toast the reason (for example "Finish the FT8 contact first."), and leave the radio alone. tests/test_keyboard_engine.py adds `test_tune_radio_refused_during_an_ft8_contact`, which fails against the old code (/security). /security also exercised both views on the demo radio during a CQ, during a faded-station wait, and with the beacon armed.

The re-review of the fix found no new BLOCK or WARN. The post-fix /security re-check added no finding.

### Accepted Risks

- The author's name in pyproject.toml, the About dialog, the AppStream metainfo, and the LICENSE
  copyright line is deliberate open-source attribution.
- The station's city and 4-character Maidenhead grid square (the Smartscan default grid, the
  README, the docs, the tests, and the scan screenshot) are published by the operator's decision
  (2026-10-12). Anything more precise, such as a 6-character subsquare, stays out of the repo.

---
*Prior review (2026-10-12, commit 548d7e0): refresh review of the same six feature commits before the history rewrite. It ended at 0 BLOCK, 3 WARN, and 14 NOTEs after /codefix fixed one BLOCK (a flaky FT4 test) and five WARNs, which became d664373. Of the three remaining WARNs, the screenshot subsquare and the untested engine wait are resolved here; the commit structure is carried above.*

<!-- REVIEW_META: {"date":"2026-10-12","commit":"d664373","reviewed_up_to":"d6643738c6d4bfcc24cbe1af8550aabff88161aa","base":"origin/main","tier":"full","block":0,"warn":1,"note":22} -->
