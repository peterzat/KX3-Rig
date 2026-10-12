## Review — 2026-10-12 (commit: 548d7e0)

**Summary:** Full review of the six unpushed commits on `main` against `origin/main` (c9f2670 through 548d7e0). They add the SWR guard, waiting for faded FT8 stations, FT4, decode filters, waterfall callsigns, the PSK31 and CW modems and the Keyboard view, the WSPR engine and view, the one-keyer rule, and their docs: 58 files, about 5,300 insertions. The refresh conditions were met (prior entry 9ec21fc, block 0, base origin/main), but every file had changed since that commit, so the whole diff got full-depth review. 548d7e0 (README.md and CLAUDE.md only) landed while the review ran and was read. Tests ran under Homebrew python3.14 with the venv's site-packages on PYTHONPATH, because this Mac's .venv has no system site packages and cannot import gi. Baseline: 427 passed, 10 skipped. After /codefix: 433 passed, 10 skipped, with no regressions and six new tests. /codefix fixed the one BLOCK (a flaky test) and five WARNs. Three WARNs remain: two need the operator to rewrite the unpushed history, and one needs tests written by hand. The fixes are uncommitted.

**External reviewers:**
None configured.

**Built-in review:**
`/code-review high`: 10 findings, 10 kept after Step 6. 4 matched this review's own findings and 6 were new; all were confirmed against the code. 548d7e0 landed during the built-in run. It touches docs only, and no built-in finding concerns it.

### Findings

Remaining:

[WARN] docs/screenshots/ft4-dark.png (added in eb84865) — The screenshot's distance column reveals the station's 6-character subsquare, the precision the 2026-10-12 history rewrite removed. Accepted Risks covers only the 4-character square. The value is withheld here. Confidence: high. (/security)
  Evidence: SECURITY.md, first finding. The FT4 view computes distances from the full configured grid (kx3rig/ui/ft8_page.py), and demo mode loads the real settings (kx3rig/app.py:115).
  Suggested fix: Operator action, not a code change. Regenerate the image with a neutral identity (the published FT8 shots use K1ABC and FN42) and put it into eb84865 itself by rewriting the unpushed commits. A later commit that replaces the file would still push the original blob. Before rewriting, record `git rev-parse eb84865:docs/screenshots/ft4-dark.png`; afterwards, confirm that `git rev-list --objects origin/main..main` no longer lists it. The root cause (demo and screenshot runs use the real settings) is a /security NOTE.

[WARN] Commit structure (c9f2670, da063e7, 0b96cc5, 6c87961, eb84865) — The commits mix unrelated concerns:
  - c9f2670 bundles the FT8 wait with the SWR guard.
  - da063e7 bundles the FT4 encoder with the PSK31 and CW modems.
  - 0b96cc5 ("Add FT4 to the FT8 view, ...") also adds kx3rig/wspr/protocol.py and tests/test_wspr_protocol.py, about 500 lines its message does not mention.
  - 6c87961 carries a Smartscan doc edit.
  - eb84865 (docs) carries the Preferences name field.
  Confidence: high on the facts.
  Suggested fix: Operator action. Nothing is pushed, so the history can be split before pushing, as was done for ff6ea82. At least move wspr/protocol.py and its test out of 0b96cc5. The screenshot WARN above needs a rewrite of the same commits anyway. /codefix left this alone.

[WARN] kx3rig/ft8/engine.py:257-261, 329-337, 438-445 — The engine side of waiting for a faded station is untested. This is the path that keys the radio again with no new operator action: `_tx_done` starting the wait, `_on_decoded` resuming it, `_tick` ending it, and `_maybe_transmit` keying after a resume. tests/test_ft8_sequencer.py covers only the `Sequencer` methods. Confidence: high.
  Suggested fix: add engine-level tests to tests/test_station.py, using the `engine` fixture and patching `_wave` as test_ft4_runs_through_the_same_engine does:
  1. After the repeats run out with no reply, an "event" "waiting" fires, and `_maybe_transmit` does not key during the wait.
  2. A decode from the contact addressed to us, fed through `_on_decoded`, emits "resumed", and `_maybe_transmit` then keys in the parity opposite to that decode's.
  3. A `_tick` after `wait_until` halts with "gave-up".
  4. `halt()` during the wait ends it.
  /codefix skipped this because it exceeds its 20-line limit; it needs manual work.

Fixed in this run (see Fixes Applied):

[BLOCK] tests/test_station.py:545-553 — `test_ft4_runs_through_the_same_engine` was flaky: 5 of 8 runs failed in isolation, and /security saw 2 of 6 fail. The pump waited only for the new frequency. The link's tune was often still pending, so `_maybe_transmit` returned at `if self.station.link.tuning_pending` (kx3rig/ft8/engine.py:362). A scratch copy that also waited for `not station.link.tuning_pending` keyed 6 of 6 times. Confidence: high.

[WARN] kx3rig/ui/ft8_page.py:382-385 — Toggling FT8 and FT4 retuned the radio and forced DATA A whenever it was anywhere in an amateur band, against the comment "when the radio was on the old one". From 160 m it jumped to 14.080 MHz. Confidence: high. (also claude-code)

[WARN] kx3rig/wspr/engine.py:285-319 — WSPRnet uploads used the radio's frequency when decoding finished, not the dial the slot was recorded on. That could send a wrong `rqrg` to public data after a retune. Confidence: high on the code. (also claude-code)

[WARN] kx3rig/ui/ft8_page.py:226 — Double-clicking a callsign over the waterfall answered any sender, including a station mid-contact. The decode list allows only a CQ or a call to us. Confidence: high that the paths differed. (also claude-code)

[WARN] kx3rig/keyboard/engine.py:51-55; kx3rig/demo.py:259-271 — The repo's own dial tables show the 17 m and 12 m PSK31 defaults landing inside the FT8 window (18.101 MHz) and the FT4 window (24.921 MHz). The demo also played PSK31 on the 17 m FT8, 12 m FT4, and 30 m FT8 dials. Confidence: high on the arithmetic. (also claude-code)

[WARN] kx3rig/wspr/engine.py:164-236 — The beacon kept transmitting after a band change made elsewhere, without the per-band confirmation. The Radio page's band buttons restore the KX3's per-band memory, which can be another band's WSPR dial in DATA A. This radio's firmware (2.38) gives the SWR guard nothing to read. Confidence: medium.

Notes:

[NOTE] kx3rig/ui/ft8_page.py:471-479, 512-515, 371-386 — A band change, or a switch between FT8 and FT4, clears the decode list but not the waterfall labels. A band change also leaves `engine.decodes` in place. Old-band callsigns stay on screen and can be double-clicked until the next decode, or indefinitely when nothing is decoded (for example after leaving DATA mode). Only answerable ones can now be answered. `_pick_clear_offset` also judges the new band from old decodes. Confidence: high. (claude-code)

[NOTE] kx3rig/ft8/engine.py:79, 467; kx3rig/ft8/adif.py:91-108; kx3rig/ft8/filters.py:64; kx3rig/ui/ft8_page.py — The worked set holds the full logged call, but lookups use `base_call()`. A logged K1ABC/P never matches, so "New" still shows and "Hide Stations in the Log" does not hide it. Contacts logged from the Keyboard view reach `engine.worked` only after a restart. Confidence: high. (also claude-code)

[NOTE] kx3rig/ft8/adif.py:34-36 — `_field` writes a character count, but the file is UTF-8. A non-ASCII "Their Name" (José) writes `<name:4>` over 5 bytes. ADI String fields are meant to be ASCII, and importers differ on characters versus bytes. Confidence: medium; the spec wording was not re-read this session. (also claude-code)

[NOTE] kx3rig/ui/ft8_page.py:191, 223; kx3rig/ft8/engine.py:155, 161 — Several labels are not FT4-aware. When FT4 is the saved mode, the TX marker starts 50 Hz wide (FT4 is 90 Hz) until a toggle. The setup button always reads "Tune Radio to FT8". `check_tx` says "to transmit FT8" and "Tune Radio to FT8 does this." Confidence: high. (claude-code)

[NOTE] kx3rig/ft8/ft4.py:187-203; kx3rig/wspr/engine.py:55, 77-80 — Duplication and dead code:
  - `parse_jt9_ft4_line` copies `decode.parse_jt9_line` except for the marker.
  - `wspr.engine.band_on_dial` repeats `Protocol.band_on_dial` with another table.
  - `PTT_LEAD_S` in wspr/engine.py is unused.
  Confidence: high. (partly claude-code)

[NOTE] kx3rig/ui/keyboard_page.py:346-354; kx3rig/keyboard/varicode.py:15-35 — Received PSK31 text can contain control characters, because Varicode covers 0-31. GTK truncates at NUL: `Gtk.TextBuffer.insert(iter, "ab\x00cd")` inserts "ab", and `Gtk.Label.set_label` does the same (checked this session). Noise that decodes to NUL drops the rest of that 150 ms chunk. Filter received text to printable characters plus newline. Confidence: high on the GTK behavior; low on how often it happens.

[NOTE] kx3rig/ui/wspr_page.py:258-259; kx3rig/wspr/engine.py — Changing "Transmit" while the beacon runs replaces the scheduler with a new random seed, so two transmissions can land in consecutive periods despite the no-two-in-a-row rule. The last transmission can also start just before the chosen end time and run about 111 s past it. Confidence: high on the code; low impact.

[NOTE] kx3rig/keyboard/engine.py:183-189 — `set_offset` is accepted while a message is going out. The audio stays where it was checked, but the waterfall TX marker and the logged frequency follow the new offset. Confidence: high; low impact.

[NOTE] kx3rig/controller.py:181-195 — The SWR guard samples `SW` during software CW. What `SW` reads between the elements of a keyed tone, when there is no RF, is unverified at this station. live-test.md section 7 tests the guard only with FT8 Tune. Confidence: low.

[NOTE] tests/test_wspr_engine.py:115-135 (added by /codefix) — `test_upload_uses_the_dial_the_slot_was_recorded_on` turns off both upload guards (`eng.demo = False`, `wspr_upload = True`). The only thing that stops a real POST to wsprnet.org is a monkeypatch of `threading.Thread`. Also patch `eng._upload`, or make `urllib.request.urlopen` raise. An autouse conftest fixture that blocks `socket.socket.connect` would protect future tests. Confidence: high that it works today. (/security)

The other /security NOTEs from this run are detailed in SECURITY.md:
- The WSPRnet upload follows redirects, reads the reply with no size limit, and does not re-check the setting after its 0-20 s delay.
- Software CW gets a 50 Hz edge margin, against 100 Hz for real CW.
- Demo and screenshot runs use the real settings, and a setting changed in demo mode can persist to the real settings file.
- Nine earlier /security NOTEs were re-checked and are still present; two were carried unchanged.

Carried from the prior entry, not re-checked (the files are outside or unchanged by this diff):
- [NOTE] docs/looptune.md:18-19, 101-102 — The "2 or 3 W" TUN PWR advice can trip the guide's warning above 3.0 W (kx3rig/looptune/tuner.py:31, 158).
- [NOTE] docs/looptune.md:17-18 — "Let go" can read as releasing XMIT, which does not end TUNE.
- [NOTE] docs/custom-shack.md:105 — The doc says the guide "is tested", but `LoopTuneDialog` has no test.
- [NOTE] README.md, docs/screenshots/confirm.png — confirm.png shows the old confirmation dialog.

### Fixes Applied

All of these are uncommitted in the working tree.
- [BLOCK] tests/test_station.py:546 — The pump also waits for `not station.link.tuning_pending`. The test then passed 8 of 8 runs (/security) and 5 of 5 here.
- [WARN] kx3rig/ui/ft8_page.py:375, 386; kx3rig/ft8/protocol.py:84-89 — The toggle records `was_on = engine.on_ft8_frequency()` before `set_protocol`. It retunes only when `follow_dial(was_on, proto)` returns a dial, so 160 m to FT4 stays put. Tested in tests/test_station.py.
- [WARN] kx3rig/wspr/engine.py:282, 308-325 — `_on_spots` takes `dial: int | None = None`, passed from `_decode_worker` and the demo path. Uploads use it and fall back to the current frequency, so the screenshot plan's 3-argument call still works. Tested with the upload thread faked.
- [WARN] kx3rig/ft8/sequencer.py:70-73; kx3rig/ui/ft8_page.py:81, 226-227 — A new `answerable(d, my_call)` is used by `DecodeRow` and the label handler. Tested in tests/test_ft8_sequencer.py.
- [WARN] kx3rig/keyboard/engine.py:48-55; kx3rig/demo.py:262-271; docs/references.md:343-346 — The 17 m and 12 m PSK31 dials are removed until a current, cited dial exists, and references.md says why. `_keyboard_kind` returns "" within 500 Hz of an FT8, FT4, or WSPR dial. Two tests were added to tests/test_keyboard_engine.py.
- [WARN] kx3rig/wspr/engine.py:101, 172-173, 193, 205, 221 — `start_beacon` records `beacon_band`, and `check_tx` refuses with "The band changed. Start the beacon again on <band>." while the beacon is on. The band is cleared on stop and at the end. Tested: start on 20 m, move to the 40 m WSPR dial, no key-down, and the beacon stops.

Re-review of the fixes found no new BLOCK or WARN. The post-fix /security re-check added one NOTE (the test upload guard, above).

### Accepted Risks

- The author's name in pyproject.toml, the About dialog, the AppStream metainfo, and the LICENSE
  copyright line is deliberate open-source attribution.
- The station's city and 4-character Maidenhead grid square (the Smartscan default grid, the
  README, the docs, the tests, and the scan screenshot) are published by the operator's decision
  (2026-10-12). Anything more precise, such as a 6-character subsquare, stays out of the repo.

---
*Prior review (2026-10-12, commit 9ec21fc): light review of README.md, docs/custom-shack.md, and docs/looptune.md, ending at 0 BLOCK, 0 WARN, and 4 NOTEs, all carried above.*

<!-- REVIEW_META: {"date":"2026-10-12","commit":"548d7e0","reviewed_up_to":"548d7e0c1bad291998d81cdd8f1f41b3022cdd68","base":"origin/main","tier":"refresh","block":0,"warn":3,"note":14} -->
