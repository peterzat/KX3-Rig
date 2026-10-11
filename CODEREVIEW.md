## Review — 2026-10-10 (commit: c3b5699)

**Summary:** Full review of c3b5699 ("Close key-down windows and harden settings"), the one commit ahead of `origin/main` (13 files). The fixes for the prior NOTEs mostly work. The stale main-loop key-down window is now refused, verified on the emulator for both a tune and a band change. A generic link error now ends the data transmission in flight, verified with `on_done(False)` and RTS off. The review found 4 WARNs, and one /codefix cycle fixed all 4. The fixes are uncommitted in kx3rig/radio.py, kx3rig/ui/ft8_page.py, and tests/test_station.py. Tests: 205 passed (baseline 201, plus 4 new); without the WSJT-X tools on PATH, 198 passed and 7 skipped.

**External reviewers:**
None configured.

**Built-in review:**
`/code-review high`: 10 findings, 10 kept after Step 6 (merged into 3 WARNs and 5 NOTEs).

### Findings

[NOTE] kx3rig/radio.py:248-259, 407-412, 504-508, kx3rig/controller.py:216-218 — Key-down windows are only partly closed, and the commit title overstates this.
  Closed and verified: a tune or band change the link applied before the main-loop copy updates is now refused.
  Still open, each reproduced by /security:
  - SPLIT and XIT are read from the main-loop copy, and `ptt` does not compare them.
  - A `?;` reply to a frequency SET leaves the optimistic frequency in the link state. `_get` also returns the `?;` as the answer and drops the real FA reply.
  - `_handshake` publishes CONNECTED before it reads IF, so the pre-outage frequency is approved on reconnect.
  - Ordering gap in `ptt`: the frequency and mode comparisons (lines 248-251) run before, and outside, the `_pending_lock` block that checks for a pending tune (lines 256-259). /security reproduced it with a forced 2 s pause between the two: a queued change to 40 m keyed on 7.185 MHz LSB after the check approved 14.074 MHz DATA. FT8 and Tune cannot reach it, because `play_data` checks for a pending tune just before calling `ptt`. Voice (`start_talking`) can, but only if the main thread stalls for several serial round trips at that exact point.
  Fix for the ordering gap: move the comparisons inside the lock, after the pending check. All of these are low likelihood in normal use. (/security) (also claude-code)

[NOTE] kx3rig/ft8/engine.py:125-128, kx3rig/controller.py:212-213, kx3rig/radio.py:543 — Both new checks pass when the value is unknown: the submode check allows `data_submode is None`, and the power check allows `power_set is None`. DT is polled only every fifth cycle in data modes, so a change to AFSK A on the front panel is seen late. /security keyed at once after such a change; the link saw it 0.61 s later. If the submode check is made to refuse an unknown submode, ui/ft8_page.py:392-393 must show the setup button for that case too, or the hidden-button problem returns. (/security)

[NOTE] kx3rig/controller.py:261-263, 321-325, kx3rig/ft8/engine.py:281, 305-309, kx3rig/radio.py:248-259 — `ptt` returns only a bool, so each caller repeats the pending-tune check to pick a message: the engine, `play_data` before `ptt`, and `start_talking` after it. When the new frequency or mode comparison refuses, the reason shown is "The radio did not accept push-to-talk." This happens, for example, when the operator nudges the VFO just before a slot. FT8 then halts the contact as "blocked" instead of retrying on the next tick. Returning a reason from `ptt` would give one accurate message on every path. (also claude-code)

[NOTE] kx3rig/ft8/engine.py:281-282, kx3rig/radio.py:341-353 — If the link drops while a tune is still pending, `tuning_pending` stays true for the whole outage. `_drop_port` does not clear `_pending`, and `_service` does not run while disconnected. The tick returns before `check_tx`, so an active contact is neither halted nor told "The radio isn't connected", as it was before this commit. It resumes after reconnect, once the queued change is applied. This needs a drop within the brief pending window. Checking `self.station.connected` before `tuning_pending` in the tick closes it. (claude-code)

[NOTE] kx3rig/config.py:73-75, 93-110 — One oversized integer resets every setting, including callsign, grid, and license class. The OverflowError is caught in `load()`, not per field in `clamp()`. The `.bad` copy keeps the data, but the file itself is still overwritten with defaults on exit; the commit message says the file is "kept... instead of being overwritten". /security also found that deeply nested JSON raises RecursionError, which `load()` does not catch, so the app fails to start. All of these need a hand-edited file. (/security) (also claude-code)

[NOTE] kx3rig/cat.py:137-140, kx3rig/controller.py:212-215, kx3rig/ui/radio_page.py:121-122, 317-320 — The new power check interacts badly with how the app sets power.
  - `cat.set_power` rounds to whole watts. `clamp()` allows a fractional maximum from 0.1 W, and the Preferences SpinRow holds 2.6 when given 2.6. With such a maximum the app requests more than the ceiling (2.6 W sends PC003), and the check then blocks transmit for good.
  - A maximum below 1 W cannot be met, because the Power scale starts at 1.
  - When the radio is above the limit, the scale shows the clamped limit, so choosing that value sends nothing. The operator must move off it and back.
  - The scale range is fixed at startup (carried).
  Fix: round the request down to the ceiling, or keep `max_power_w` a whole number. (claude-code)

[NOTE] kx3rig/ft8/engine.py:126 — The comment cites "KX3 Owner's Manual p.18" for "Other submodes change sideband and audio handling". docs/references.md:79-80 records only DATA A's behavior from that page, and the prior scan found the references do not cover the other submodes. CLAUDE.md asks for hardware claims to come from a source read in the session. Record the fact in references.md, or soften the comment. The check itself is conservative either way.

[NOTE] install.sh:27-28, constraints.txt:5-8 — Supply-chain pinning is partial.
  - numpy and pyserial are pinned.
  - `pip install --upgrade pip` is not pinned.
  - pip's `-c` constraints do not apply to the isolated build environment, so the newest setuptools is always fetched. /security confirmed this in pip 26.2.1's source.
  - No documented command applies the pytest, pluggy, iniconfig, and packaging pins. install.sh installs only the project, and README.md:119 does not say how pytest gets into the venv.
  - There are no hashes.
  (/security) (also claude-code)

[NOTE] kx3rig/ft8/grid.py:14 — `g[2:4].isdigit()` followed by `int()` is the same pattern this commit fixed in cat.py. Only a hand-edited grid in settings.json could hold a superscript digit, because jt9 decodes use the ASCII FT8 alphabet. Low.

[NOTE] Commit c3b5699 bundles nine unrelated review fixes: key-down, link error, parsers, power check, DATA A, settings, pins, screenshot path, and the live-test doc. It follows the review-batch convention and its message lists every item, so this is not a BLOCK.

[NOTE] kx3rig/controller.py:298-314, 356-363 — `_abort_data_tx` cannot tell which transmission an idle-queued link event belongs to. No reachable race was found. (carried, low confidence)

[NOTE] kx3rig/radio.py:259, 557-566, kx3rig/controller.py:83, 356-363 — Code quality:
  - The `_Pending(power=...)` reset in `ptt(True)` can only discard a queued bandwidth change.
  - The tuning-field list exists twice (`_apply_pending`, `_tuning_pending_locked`).
  - `_abort_data_tx` repeats `failed()`.
  - `_data_tx_finish` moves in lockstep with `_data_tx_token`.
  (carried)

[NOTE] kx3rig/bandplan.py:186, 212 — `tx_check` and `privilege_segments` still default `license_class` to "General". No current caller omits it. (/security, carried)

[NOTE] README.md:72, docs/references.md:6, 22-24 — README says the first-transmit dialog reminds you to retune a magnetic loop, but the dialog now reminds every operator to tune the antenna. references.md cites station-verified facts to private notes that readers cannot open. (carried; the live-test.md Extra-class item is resolved)

[NOTE] kx3rig/radio.py:547-548 — After a transmission only `power_out` is cleared, so the previous `swr` shows briefly at the start of the next one. (carried)

[NOTE] install.sh:31 — `Exec=` is substituted unquoted, and a repo path containing `|` breaks the sed expression. (carried)

[NOTE] kx3rig/ft8/sequencer.py:90-105 — Answering a decode addressed to us that carries only "73" reports success but leaves the sequencer idle. (carried)

[NOTE] docs/references.md:139-140 — "Starts up to 3 s late" counts from the period boundary; the most waveform skipped is about 2.5 s. (carried, low confidence)

Resolved since the prior review:
- The generic link-error path now ends the data transmission (verified on the emulator).
- CAT parsers accept ASCII digits only.
- Settings files: JSON booleans no longer pass the numeric checks, oversized numbers no longer crash startup, and a corrupt file is copied to `settings.json.bad`.
- FT8 and Tune refuse any data submode other than DATA A.
- The stale main-loop key-down window is refused (verified for a tune and a band change).
- Key-down is refused when the radio's power is above the maximum.
- The screenshot recipe no longer uses `/tmp/shots`; it uses `mktemp -d`, and screenshots.py prints each path.
- The live-test step for Extra licensees is fixed.

### Fixes Applied

- [WARN] tests/test_station.py:108-121 — `test_ft8_requires_data_a` failed without WSJT-X and wrote to the real data directory. It now sets `XDG_DATA_HOME` to `tmp_path` and stubs `encode.available`. Verified: 198 passed and 7 skipped with `PATH=.venv/bin`; it was 1 failed before the fix.
- [WARN] kx3rig/ui/ft8_page.py:392-393 — The "Tune Radio to FT8" button was hidden in the state where the DATA A refusal tells the operator to press it. It now also shows when the data submode is known and is not DATA A, the same condition the engine refuses on. (also claude-code)
- [WARN] kx3rig/radio.py:305-315 — The link retried with no delay after an exception, flooding the main loop with "lost" events. Both `except` branches now wait `RETRY_INTERVAL`. /security measured one event per 1.5 s, down from about 43,000 per second. (/security) (also claude-code)
- [WARN] tests/test_station.py:124-212 — The new transmit-safety paths had no tests. Four emulator tests now cover them:
  - a link error ends the data transmission;
  - a stale main-loop copy never keys after a tune;
  - `play_data` is refused while a tune is pending;
  - FT8 waits while a tune is pending.
  /codefix confirmed the first two fail when their fix is removed. (also claude-code)

### Accepted Risks

- The author's name in pyproject.toml, the About dialog, the AppStream metainfo, and the LICENSE
  copyright line is deliberate open-source attribution.

---
*Prior review (2026-10-10): first-push full review of 3f84f8a on the rewritten `main` (empty-tree base). It had no BLOCK or WARN and 16 NOTEs; the most important were the narrow key-down windows, the generic link-error path that left a data transmission running, and settings-file robustness. c3b5699 addresses most of them.*

<!-- REVIEW_META: {"date":"2026-10-10","commit":"c3b5699","reviewed_up_to":"c3b56996badc75e772c0d4c0f9e1a651d4b528ac","base":"origin/main","tier":"full","block":0,"warn":0,"note":18} -->
