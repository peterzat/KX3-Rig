## Security Review: 2026-10-11 (scope: paths)

**Summary:** Path-scoped review at HEAD (4067339) of docs/screenshots/station.jpg, the station photo that 4067339 adds as the README hero image. The commit is not yet pushed. No new findings. The photo is a 1600x956 baseline JPEG re-encoded by a macOS screenshot. It carries no location, camera, owner, date, or thumbnail metadata, and its visible content shows no callsign, grid locator, name, address, face, outdoor view, serial number, or asset tag. Six NOTEs in files outside this scope are carried.

### Findings

[NOTE] kx3rig/devices.py:30, 77-80, and 202-213; kx3rig/controller.py:209, 253, 338, 403-411, and 431 (line numbers as of the 2026-10-11 post-fix pass, since committed as dc44093). The Digirig is recognized by node name alone, so another PipeWire client's node can stand in for it (carried from the 2026-10-11 scan, not re-checked). `parse_pw_dump` keeps every Audio/Source and Audio/Sink node, whoever created it. `pick_digirig_audio` takes the first source and the first sink whose name matches `usb-C-Media|USB_PnP_Sound_Device`. Confidence: high on the selection behavior (reproduced offline); low that a sandboxed client can create such a node (not tested).
  Attack vector: A sandboxed client with access to the PipeWire socket creates an Audio/Sink or Audio/Source node whose name contains `usb-C-Media`, for example before the radio is plugged in. `pw-dump` lists nodes in creation order, so the impostor comes first and is selected (controller.py:403-404). KX3-Rig then sends voice, FT8, and Tune audio to it (controller.py:253 and 338) while the link keys the radio by RTS. The waterfall and FT8 decoder read the impostor's audio (controller.py:431). An impostor sink alone also passes the `audio.tx` gate (controller.py:411 and 209). The added reach is limited, because a client that can play audio to the Digirig output can already mix sound into a transmission. The impostor adds two things: it replaces KX3-Rig's transmit audio instead of mixing with it, and it supplies the receive audio that the operator and the FT8 sequencer act on.
  Evidence: From the 2026-10-11 scan. Offline, a synthetic dump listed impostor nodes before the real Digirig nodes, and `pick_digirig_audio` returned the impostor as both source and sink. On the live session, `pw-dump` listed its nodes in ascending `object.serial` order. WirePlumber's default access config gives Flatpak clients "rx" ("all" for the Manager category); whether "rx" permits creating a node was not verified.
  Remediation: Refuse transmit, with an error, when a scan finds more than one Digirig-named source or sink. This also catches a second C-Media adapter. Prefer properties a stream client cannot choose, such as a `device.id` that resolves to an ALSA Device with the CM108's USB IDs, after confirming that a client cannot set them.

[NOTE] kx3rig/controller.py:220-222; kx3rig/radio.py:253-260, 408-413, 505-509, and 558-582. Key-down can still be approved against SPLIT, XIT, or frequency state that is not the radio's current one (carried from the 2026-10-10 scan, not re-checked). `can_transmit` reads SPLIT and XIT from the main-loop copy (controller.py:220), and the `ptt` gate compares only frequency and mode (radio.py:256-259). The 2026-10-11 scan at ff6ea82 last re-checked it. Confidence: high that each window exists; low that any occurs in normal operation.
  Attack vector: No adversary.
  - (1) The link has read a SPLIT or XIT change that the main loop has not yet applied. Key-down passes, because `ptt` compares neither flag.
  - (2) A rejected frequency SET. `_get("FA;")` returns the SET's `?;` as its answer (radio.py:412-413), and `_tuning` then clears (radio.py:564-566). Both copies hold the requested frequency until the next IF reply.
  - (3) Reconnect. `_handshake` publishes CONNECTED (radio.py:505) before it reads IF (radio.py:506-509). An active FT8 contact stops when the main loop sees the link down, but Tune, Talk, and a newly started contact are exposed for one IF round trip.
  Evidence: From the 2026-10-11 scan, on the demo emulator in DATA mode. The link saw SPLIT after 0.20 s and XIT after 0.21 s while the main-loop copy still showed them off. `can_transmit` and `play_data` were allowed, and the emulator's RTS rose. Windows (2) and (3) were reproduced in the 2026-10-10 scan: in 5 of 5 runs, the check approved 14.074 MHz and the rejected SET then keyed on 14.230 MHz.
  Remediation:
  - In `ptt(True)`, refuse when the link's live `split` or `xit_on` is set.
  - Keep `tuning_pending` true until an FA or IF reply read after the SET confirms the new frequency. Treat `?;` or a missing reply as unconfirmed, and match the GET's own reply rather than a `?;` left over from the SET.
  - Read IF before publishing CONNECTED, in the same state update. Ideally, read IF just before asserting RTS.

[NOTE] kx3rig/ft8/engine.py:128-133; kx3rig/radio.py:253-260, 419-431, and 543-547. The FT8 submode check can pass on a stale submode (carried from the 2026-10-10 scan, not re-checked). An unknown submode refuses (engine.py:129-130, tested at tests/test_station.py:349-355), but a stale known value passes. In a data mode the link reads DT only every fifth poll cycle (radio.py:543-547). It does not read DT when an IF reply shows a change into DATA (radio.py:419-431), and the `ptt` gate does not compare the submode. Confidence: high on the code behavior; low on the on-air effect, because the sourced references do not describe the sideband and signal source of the other submodes.
  Attack vector: No adversary. An operator changes the submode on the front panel and starts FT8 or Tune within about a second. The check passes on the old value.
  Evidence: From the 2026-10-11 scan at 85228ff, on the emulator. After the emulator's submode was set to AFSK A, `check_tx` and `play_data` were allowed at once, and RTS rose. The link saw AFSK A 0.60 s later.
  Remediation: Read DT whenever an IF reply changes the mode into DATA. Include the submode in the `ptt` gate for data transmissions, for example as an `expect_submode` argument compared with the link's live value.

[NOTE] kx3rig/bandplan.py:187 and 213. `tx_check` and `privilege_segments` still default `license_class` to "General" (carried from the 2026-10-10 scan, not re-checked). Confidence: high that no current caller omits it. As of the 2026-10-11 scan, the only app caller of `tx_check` is `Station.can_transmit` (controller.py:223). It passes `settings.license_class`, which defaults to Technician and is reset to Technician when unknown (config.py:35 and 67-68). `privilege_segments` has no app caller; only tests/test_bandplan.py:89 calls it, with "General".
  Attack vector: No adversary; the gap is latent. A future transmit path that called `tx_check(dial, mode)` would approve General segments for a Technician operator.
  Remediation: Make `license_class` a required parameter in both functions, or default it to "Technician".

[NOTE] install.sh:27-28, constraints.txt:1-8, pyproject.toml:2. Install-time code is still fetched unpinned (carried from the 2026-10-10 scan, not re-checked). numpy and pyserial resolve to the versions in constraints.txt. install.sh:27 upgrades pip with no version. The `setuptools>=64` build backend is installed into pip's isolated build environment, where `-c` does not apply. The pins carry no hashes. Confidence: high that pip and setuptools are unpinned; exploitation needs a compromised release.
  Attack vector: A compromised future release of pip or setuptools on PyPI runs with the user's privileges during `./install.sh`. It builds the venv of an app that keys a transmitter.
  Remediation: Pin pip (for example `pip install 'pip==26.2.1'`) or drop the upgrade. Add a tested `setuptools==` pin to constraints.txt and pass `--build-constraint constraints.txt`. Consider hashed pins with `--require-hashes`, and run `pip-audit` before releases.

[NOTE] HEAD tree, location withheld (outside this run's scope). One line still contains the 4-character prefix of the grid locator that the history scrub removed (carried from the 2026-10-10 scan, not re-checked). The scrub replaced that prefix in the tests, where it was paired with the scrubbed callsign. This line pairs it with a different callsign, so it does not identify the operator by itself. The file and line are not recorded here because this repository is public; they were given in the 2026-10-10 scan's session output. Confidence: high that the value matches. Low that it matters, because a 4-character locator spans 1 degree of latitude by 2 degrees of longitude.
  Attack vector: A reader of the public repository learns the operator's region only if something ties this locator to the operator. Nothing in the tree does; a precise citation in a committed file would.
  Remediation: Replace the locator in that line with one unrelated to the station, as the scrub did in the tests, or record it under Accepted Risks. Include the 4-character prefix in future identity searches. Keep the location out of SECURITY.md, CODEREVIEW.md, and commit messages.

### Coverage

The one in-scope file, docs/screenshots/station.jpg, was reviewed at HEAD (4067339). The working tree copy is identical to the committed blob (6f4466f). The file is a static image that only README.md references, so the review dimensions reduce to checks on the file itself.

- Data exposure and PII, metadata. exiftool is not installed, so a stdlib parser enumerated every JPEG segment and decoded each TIFF IFD.
  - APP0 is JFIF at 144 dpi. APP1 EXIF holds IFD0 (orientation, resolution, the ExifIFD pointer) and ExifIFD (EXIF version, components, a UserComment reading "Screenshot", FlashpixVersion, 1600x956, scene type). APP2 holds Apple's generic "Display P3" ICC profile.
  - Absent: a GPS IFD, an IFD1 thumbnail, make, model, body or lens serial, owner, artist, copyright, capture date, software, and host fields, and any XMP, IPTC, Photoshop, COM, or MPF segment.
  - The file has one baseline scan, nothing after EOI, and no second SOI signature. `mdls` and `sips` agree (`kMDItemImageIsScreenshot` is 1). The `com.apple.provenance` extended attribute is local filesystem state and is not committed.
- Data exposure and PII, visible content. The whole image was viewed. Each region with text or labels was then cropped and enlarged 2x to 8x with macOS `sips` (ImageMagick is not installed), and the labels were also rotated 90 and 180 degrees.
  - Legible text: the KX3 front panel and display (7.245.85, 7.300, ATU, ANT1, TX DATA). The KX3-Rig Radio page (7.245.850 MHz, 40 m, DATA, Receiving, S0, 5 W, band and mode buttons, Hold to Talk, the data-mode hint, 500 Hz zoom). The Ubuntu top bar (the date and time, 96% battery), "Lenovo" and "T480s", the Digirig Mobile logo, and a 10 W, DC to 3 GHz rating label on the part fitted to the antenna jack.
  - The Radio page and window code reference neither the callsign nor the grid (radio_page.py and window.py). The FT8 page uses both, and it is not on screen.
  - The label on the orange case lid is illegible at the published resolution (about 130 by 45 pixels). Its layout resembles a manufacturer's label; this is not confirmed.
  - No face, reflection, document, outdoor view, landmark, serial number, or asset tag is visible. The background is wood paneling, chairs, and a table.
  - The left edge has a uniform 1 to 2 pixel border from the screenshot (column 0 standard deviation 3.1), too narrow to hold text. The other three edges are photo content.
- Identity. The photo adds nothing that ties the carried locator NOTE, or anything else, to the operator. The file bytes contain no email-shaped string and no locator-shaped token. All 16 callsign-shaped byte runs lie inside the Huffman-coded scan data (offset 27486 onward), which is compression noise, not text. The operator's callsign was not looked up in this session, so no exact-value search was run; the visual review covers what a reader can see.
- Secret leaks. No credential, token, password, or key is visible on screen. The file bytes contain no private-key header, no AWS, GitHub, or `sk-` token prefix, no URL, and no printable string of 10 or more characters beyond "Screenshot", the ICC names, and Huffman table bytes.
- Input and output sanitization. The file is a well-formed baseline JPEG with standard segments. It is not a polyglot: there is no HTML, SVG, PHP, ZIP, or PDF signature and no trailing data. No app code reads it.
- AI-specific risks. The image holds no instruction-like text that an agent reading it could act on.
- Not applicable, so not reviewed: authentication and authorization, dependency and supply chain, and infrastructure configuration. The file is an image, not code or configuration. Its git mode is 100644.

Not fully reviewed:
- The README.md change in 4067339 is outside this run's scope. It was read for context only. The new alt text names the laptop, the band, the Digirig, and the KX3.
- All six findings are in files outside this scope. They were carried without re-checking; each file still exists.

Git history checked for secrets: no credential-handling files are in scope. docs/screenshots/station.jpg has one commit (4067339, not pushed; `main` is one commit ahead of `origin/main`), so no earlier version of the photo, such as one with camera metadata, is in history. No other photo was ever added or deleted; the only other image blobs are the six PNG app screenshots added in cf5d4bc. No tags, stash entries, or other refs exist.

### Accepted Risks

- The author's name in pyproject.toml, the About dialog, the AppStream metainfo, and the LICENSE
  copyright line is deliberate open-source attribution.

---
*Prior review (2026-10-11, commit ff6ea82, later split into dc44093 and 8a0d4ed): A path-scoped review of the five code and test files behind the asynchronous `pw-dump` audio scan, with no BLOCK or WARN. Its new NOTE, a scan busy flag that deeply nested `pw-dump` output could latch, was resolved in the same run's post-fix re-check, which added a NOTE that the Digirig is recognized by node name alone. The SPLIT and XIT key-down windows were re-checked and still present. The stale FT8 submode, the `tx_check` default of General, unpinned install-time code, and a 4-character locator prefix (location withheld) were carried. The routing invariants held, and transmit stays refused until the first successful scan.*

<!-- SECURITY_META: {"date":"2026-10-11","commit":"4067339d4036ad17ff1ef17eaa11c7ca23b71855","scope":"paths","scanned_files":["docs/screenshots/station.jpg"],"block":0,"warn":0,"note":6} -->
