## Review — 2026-10-10 (commit: 266a725)

**Summary:** Refresh review of 266a725 ("Finish transmit-path hardening from review notes"), the one commit ahead of `origin/main` (6 files). The prior review covered c3b5699, and its fixes (b8090c9) are already pushed. Most of the commit works. The `ptt` ordering gap is closed (verified by /security on the emulator), unknown power and submode now refuse, a contact stops on disconnect, and settings are now repaired per field. The new FT8 retry had two defects, and the new refusals had no tests. These 3 WARNs were fixed in one /codefix cycle; the fixes are uncommitted in kx3rig/bandplan.py, kx3rig/controller.py, kx3rig/ft8/engine.py, and tests/test_station.py. Tests: 215 passed (baseline 208, plus 7 new).

**External reviewers:**
None configured.

**Built-in review:**
`/code-review high`: 9 findings, 9 kept after Step 6 (merged into 3 WARNs and 5 NOTEs).

### Findings

[NOTE] kx3rig/radio.py:248-259, 407-412, 504-508, kx3rig/controller.py:218-220 — Key-down windows. The ordering gap in `ptt` is closed. /security paused the call for 2 s, and a queued change to 40 m or to USB was refused; a control call with nothing queued still keyed. Three windows remain, each reproduced by /security:
  - SPLIT and XIT are read from the main-loop copy, and `ptt` does not compare them.
  - A `?;` reply to a frequency SET leaves the optimistic frequency in the link state. In 5 of 5 runs the radio keyed on 14.230 MHz after the check approved 14.074 MHz.
  - `_handshake` publishes CONNECTED before it reads IF, DT, and PC. An active FT8 contact now stops on disconnect, so FT8 is mostly no longer exposed. Tune and Talk still are, for one round trip. `_drop_port` also keeps `power_set` and `data_submode`, so the new unknown-value refusals do not apply after a reconnect. A power level raised on the front panel during an outage passes until PC is read. (claude-code)
  All are low likelihood in normal use. (/security) (also claude-code)

[NOTE] kx3rig/radio.py:543-547, kx3rig/ft8/engine.py:128-133 — An unknown submode or power now refuses transmit (resolved, and tested). A stale known value still passes. DT and PC are polled every fifth cycle, so a front-panel change to AFSK A, or a power increase above the maximum, is seen about a second late. /security keyed at once after a change to AFSK A, and the link saw the change 0.61 s later. (/security)

[NOTE] kx3rig/config.py:77-79 — The whole-watt clamp also raises the floor from 0.1 W to 1 W. A hand-edited ceiling below 1 W, such as 0.5, is raised to 1 W on load, and a safety ceiling should not go up silently. The Preferences row offers only 1 to 15 W, so only a hand-edited file reaches this. Consider refusing transmit for a ceiling below 1 W, or keeping the value and flooring the requests. (also claude-code)

[NOTE] kx3rig/radio.py:277-286 — `_update` calls `on_state` after it releases `_state_lock`. When the main thread (`set_frequency`, `ptt`) and the worker update at the same time, an older snapshot can be queued to the main loop after a newer one. The main-loop copy then holds the older snapshot until the next change. /security forced this with a pause. It fails closed, because the `ptt` comparison then refuses. Calling `on_state` (an `idle_add`) while holding the lock keeps the order. (/security)

[NOTE] kx3rig/controller.py:260-265 — Voice still reports a frequency or mode mismatch as "The radio did not accept push-to-talk." FT8 now uses the new `TxCheck.retry` flag. `start_talking` could use the same distinction to show an accurate message. (carried, reduced) (also claude-code)

[NOTE] kx3rig/ft8/engine.py:309-315 — Each refused retry rebuilds the full transmit buffer, about 0.6 M float32 samples, on the main thread, up to 10 times per slot. The cost is small: a few MB copied per second while refusals continue. (claude-code)

[NOTE] Commit 266a725 bundles four concerns: the `ptt` check order, the unknown-value refusals, the FT8 retry and disconnect stop, and settings. It follows the review-batch convention, and its message lists every item, so this is not a BLOCK.

[NOTE] SECURITY.md records one personal-data NOTE without its location. Read it there, and do not copy its location into committed files. (/security)

[NOTE] kx3rig/ui/radio_page.py:121-122, 317-320 — Power control residuals. When the radio is above the limit, the scale shows the clamped limit, so choosing that value sends nothing. The scale range is also fixed at startup. The fractional-ceiling part of the prior NOTE is resolved. (carried)

[NOTE] kx3rig/ft8/engine.py:132 — The comment cites "KX3 Owner's Manual p.18" for the behavior of the other submodes, which docs/references.md does not record. (carried)

[NOTE] install.sh:27-28, constraints.txt:5-8 — Supply-chain pinning is partial. pip and the setuptools build backend are not pinned, no documented command installs the pinned test tools, and there are no hashes. (/security, carried)

[NOTE] kx3rig/ft8/grid.py:14 — `isdigit()` followed by `int()` is the pattern fixed in cat.py. Only a hand-edited grid reaches it. (carried)

[NOTE] kx3rig/controller.py:298-314, 356-363 — `_abort_data_tx` cannot tell which transmission an idle-queued link event belongs to. No reachable race was found. (carried, low confidence)

[NOTE] kx3rig/radio.py:232-234, 558-566, kx3rig/config.py:69-74, kx3rig/controller.py:83, 356-363 — Code quality:
  - The `_Pending(power=...)` reset in `ptt(True)` can only discard a queued bandwidth change.
  - The tuning-field list exists twice (`_apply_pending`, `_tuning_pending_locked`).
  - `ft8_tx_offset_hz` has its own copy of the finite-number check. Adding it to the loop's tuple would do the same job. (claude-code)
  - `_abort_data_tx` repeats `failed()`, and `_data_tx_finish` moves in lockstep with `_data_tx_token`.
  (carried)

[NOTE] kx3rig/bandplan.py:187, 213 — `tx_check` and `privilege_segments` still default `license_class` to "General". No current caller omits it. (/security, carried)

[NOTE] README.md:72, docs/references.md:6, 22-24 — README's description of the first-transmit dialog is out of date, and references.md cites private notes that readers cannot open. (carried)

[NOTE] kx3rig/radio.py:548-549 — After a transmission only `power_out` is cleared, so the previous `swr` shows briefly at the start of the next one. (carried)

[NOTE] install.sh:31 — `Exec=` is substituted unquoted, and a repo path containing `|` breaks the sed expression. (carried)

[NOTE] kx3rig/ft8/sequencer.py:90-105 — Answering a decode addressed to us that carries only "73" reports success but leaves the sequencer idle. (carried)

[NOTE] docs/references.md:139-140 — "Starts up to 3 s late" counts from the period boundary. The most waveform skipped is about 2.5 s. (carried, low confidence)

Resolved since the prior review:
- The `ptt` ordering gap (window 4): the comparisons now run under `_pending_lock`, after the pending-tune check. Verified by /security.
- An unknown power setting or data submode now refuses transmit.
- A link drop while a tune is pending no longer leaves a contact waiting: an active contact stops when the radio disconnects.
- An oversized integer resets only its own field, and deeply nested JSON no longer stops startup.
- The maximum power is whole watts on load. The Preferences row accepts only whole numbers: typing 2.6 produced 1.0 in a GTK check.
- FT8 retries a transient key-down refusal instead of stopping the contact.

### Fixes Applied

- [WARN] kx3rig/ft8/engine.py:85, 141, 153, 163, 326-329 — The refusal counter carried across contacts and slots. After one give-up, every later contact stopped on its first transient refusal (emulator probe: counter 11 on the new contact). `_refusals` now resets in `halt()`, `answer()`, and `call_cq()`, and again when a new transmit slot starts (`_refusal_slot`). Re-probed: a new contact stays active after one refusal. (also claude-code) (also /security)
- [WARN] kx3rig/bandplan.py:177, kx3rig/controller.py:324-327, kx3rig/ft8/engine.py:318-323 — The retry also repeated a key-down when transmit audio failed after PTT was raised (emulator probe: 10 RTS rises in about a second). `TxCheck` has a new `retry` flag. `play_data` sets it only for the pending-tune and `ptt` refusals, where nothing was keyed, and the engine stops at once for any other refusal. Re-probed: one RTS rise, then the contact stops. /security confirmed that a retry re-runs the license check and adds no key-down window. (also claude-code) (also /security)
- [WARN] tests/test_station.py:262-355 — The unknown-power and unknown-submode refusals had no tests. Seven tests now cover them, plus the retry flag, a non-retryable refusal, and the per-contact and per-slot counter. (also claude-code)

### Accepted Risks

- The author's name in pyproject.toml, the About dialog, the AppStream metainfo, and the LICENSE
  copyright line is deliberate open-source attribution.

---
*Prior review (2026-10-10): full review of c3b5699, which closed the stale main-loop key-down window and the generic link-error path. It found 4 WARNs (a test that failed without WSJT-X, the hidden Tune Radio to FT8 button, the link retry spin, and untested transmit-safety paths), all fixed by /codefix and pushed as b8090c9, and 18 NOTEs.*

<!-- REVIEW_META: {"date":"2026-10-10","commit":"266a725","reviewed_up_to":"266a72542d83c7825e187147ad14eb209c76445d","base":"origin/main","tier":"refresh","block":0,"warn":0,"note":20} -->
