## Review — 2026-10-10 (commit: 3f84f8a)

**Summary:** First-push full review of the whole tree on the again-rewritten `main` (empty-tree base, 9 commits). The rewrite only removed the private-repo links from three commits; the final tree is identical to the one reviewed last time plus 3f84f8a (the second round of review fixes, settings hardening, and docs/live-test.md). No BLOCK or WARN findings; no fixes applied. Tests: 196 passed.

**External reviewers:**
None configured.

**Built-in review:**
`/code-review high`: 10 findings, 10 kept after Step 6 (merged into 6 NOTEs).

### Findings

[NOTE] kx3rig/radio.py:245-252, 493-494, 546-554, kx3rig/controller.py:104, 201-215 — Narrow key-down windows remain. The license check reads the main-loop copy `Station.radio` (idle priority) while the PTT gate reads the link's live `_tuning` flag, so once a tune or band change (which has no optimistic update) is applied, the gate opens before the check sees the new frequency. `_tuning` also clears when the readback is `?;` or times out, leaving the optimistic frequency in state. SPLIT/XIT changes made on the radio are seen only at the next IF poll, and `_handshake` reports CONNECTED before reading IF. /security reproduced the first window again (checked 14.074 MHz, keyed on 14.230 MHz DATA). Low likelihood in normal use. A sturdier design has `ptt(True)` confirm frequency, mode, SPLIT, and XIT against the checked values from a fresh readback. (/security) (also claude-code)

[NOTE] kx3rig/radio.py:302-304, kx3rig/cat.py:284-288, 316-324 — The link's generic `except Exception` path drops the port and PTT without emitting "lost" or "watchdog", so `_abort_data_tx` never runs: the data clip keeps playing unkeyed and `on_done(True)` reports it as sent, which can credit or log an FT8 message that was cut off. Reproduced on the emulator (RuntimeError in `read`: PTT dropped, no event, `on_done` reported `[True]`). One concrete trigger: `parse_if` and `parse_om` guard with `str.isdigit()`, which accepts latin-1 superscript digits (0xB2, 0xB3, 0xB9), and then `int()` raises ValueError (verified). In receive this only causes a spurious reconnect; during transmit only TQ/PO/SW are parsed (regex, safe), so the transmit case needs a code bug. Suggested fix: emit "lost" from the generic handler, and use `isascii() and isdigit()` (or try/except) in the two parsers. (also claude-code)

[NOTE] kx3rig/controller.py:316-317, kx3rig/ft8/engine.py:486-491 — When FT8 or Tune key-down is refused because a tune is still in flight, the reason is "The radio did not accept push-to-talk." and an active contact is halted as "blocked". Voice now says "Still tuning". Checking `link.tuning_pending` in `can_transmit` would give one message on every path, and the engine could retry within MAX_LATE_S rather than halt. (also claude-code)

[NOTE] kx3rig/controller.py:201-215, kx3rig/bandplan.py:166-170 — The license check ignores the data submode and treats DATA as upper sideband, which docs/references.md:79 confirms only for DATA A. In AFSK A, FSK D, or PSK D (set from the front panel) the occupied span may differ. Refusing data transmit unless `data_submode` is DATA A closes it. Low confidence in the on-air effect. (/security)

[NOTE] kx3rig/controller.py:298-314, 348-355 — `_abort_data_tx` cannot tell which transmission an idle-queued link event belongs to. No reachable race was found: both the EOS completion and the link event go through `GLib.idle_add` in arrival order, and clip lengths (FT8 about 12.9 s, Tune 10 s) are below their limits (15 s, 11 s). Low confidence. (claude-code)

[NOTE] kx3rig/radio.py:249-252, 549, kx3rig/controller.py:83, 309-314, 348-355 — Code quality after the fixes: the `_Pending(power=...)` reset in `ptt(True)` can now only discard a queued bandwidth change, and its comment history suggests tuning is still dropped; the tuning-field list exists twice (`_apply_pending` and `_tuning_pending_locked`, which differ by `data_submode`); `_abort_data_tx` repeats `failed()`; `_data_tx_finish` is set and cleared in lockstep with `_data_tx_token`. (claude-code)

[NOTE] kx3rig/config.py:68-73, 101-103, kx3rig/controller.py:136 — JSON booleans pass the numeric checks (`"max_power_w": true` loads as 1 W and is saved back as `true`). An integer literal over about 308 digits makes `math.isfinite` raise OverflowError, which `load()` does not catch, so the app fails to start. Invalid JSON still yields defaults that `Station.shutdown()` saves over the operator's file. All need a hand-edited file. (/security) (also claude-code)

[NOTE] kx3rig/ui/preferences.py:71-74, kx3rig/ui/radio_page.py:121-133, kx3rig/controller.py:201-215 — The maximum power is a ceiling on requests only. Key-down is allowed when the radio's own PC setting is above it, lowering it in Preferences does not lower the radio's current power, and the power slider keeps the range from startup. README.md:96-97 words this accurately ("never asks for more"); config.py:37 calls it a "hard ceiling".

[NOTE] kx3rig/bandplan.py:186, 212 — `tx_check` and `privilege_segments` still default `license_class` to "General"; only the unknown-class fallback became Technician. No current caller omits the argument. (/security)

[NOTE] Commits 85bb20a, f5c2437, and 3f84f8a each bundle several unrelated fixes. They follow the review-batch convention and their messages list every item, so this is not a BLOCK. After the rewrite, 9003c0b ("Drop links to a private repo; generalize the antenna reminder") no longer drops any links; those removals now live in 04ead39, 85bb20a, and f5c2437. Reword it if the history should read accurately; nothing is pushed yet.

[NOTE] README.md:72, docs/references.md:6, 22-24, docs/live-test.md:183 — README still says the first-transmit dialog reminds you to retune a magnetic loop; the dialog now reminds every operator to tune the antenna. references.md cites station-verified facts to private notes readers cannot open (carried). live-test.md expects Hold to Talk on 14.200 MHz to be disabled, which holds for General and Technician only; an Extra licensee would key on that step (into the dummy load).

[NOTE] kx3rig/radio.py:536-537 — After a transmission only `power_out` is cleared; the previous `swr` shows briefly at the start of the next one. (carried)

[NOTE] install.sh:31 — `Exec=` is substituted unquoted, and a repo path containing `|` breaks the sed expression. (carried)

[NOTE] kx3rig/ft8/sequencer.py:90-105 — Answering a decode addressed to us that carries only "73" reports success but leaves the sequencer idle. (carried)

[NOTE] docs/references.md:139-140 — "Starts up to 3 s late" counts from the period boundary; the most waveform skipped is about 2.5 s. (carried, low confidence)

[NOTE] /security NOTEs (see SECURITY.md): dependencies with lower bounds only and no lock file; the shared `/tmp/shots` path in CLAUDE.md:47; the author's name as attribution (accepted below, but SECURITY.md's Accepted Risks does not list it yet).

Resolved since the prior review: the `pre-scrub` branch WARN (the branch is gone and `main` is the only ref; the old commits survive only in the local reflog, which `git push` never sends), the private-repo links in history (rewritten out; only the repository name remains in CLAUDE.md:7 and docs/references.md:6), the stale docs/screenshots/confirm.png (regenerated with the new dialog text and now shown in the README), and the `"serial_port": null` startup crash.

### Fixes Applied

None.

### Accepted Risks

- The author's name in pyproject.toml, the About dialog, the AppStream metainfo, and the LICENSE
  copyright line is deliberate open-source attribution.

---
*Prior review (2026-10-10): first-push review of 26f3355; two fix cycles (later committed as 3f84f8a) refused key-down while a tune is in flight, ended the FT8 transmission on a link-initiated PTT drop, and refused transmit under SPLIT or XIT; the `pre-scrub` branch WARN was left for the operator and is now resolved.*

<!-- REVIEW_META: {"date":"2026-10-10","commit":"3f84f8a","reviewed_up_to":"3f84f8a1a2d2c2fd8a2743f7ea73e8a3f55f0d34","base":"4b825dc642cb6eb9a060e54bf8d69288fbee4904","tier":"full","block":0,"warn":0,"note":16} -->
