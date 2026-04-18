# StemForge v0 — Ableton validation runbook

**Status:** manual-test runbook for v0 ship acceptance.
**Target:** macOS (Apple Silicon) + Ableton Live 12.1.x.
**Expected total time:** ~10 minutes (install + one round-trip split).

This runbook is what you (zak) follow after the v0 `.pkg` is built, to
confirm StemForge drops into Ableton Live 12.1.x cleanly and completes a
full audio → stems round-trip. It cross-references the source-of-truth
spec at [`docs/v0-ship-spec.md`](./v0-ship-spec.md) §1 "Definition of
Done" and the workstream artifacts referenced inline. It is deliberately
low-ceremony — if something diverges from the steps below, that
divergence is the bug report.

---

## 1. Prerequisites

- **macOS on Apple Silicon** (M1 / M2 / M3 / M4). Intel / Rosetta is
  out of scope for v0; see §8.
- **Ableton Live 12.1.x** installed. Any 12.1 point release is fine;
  12.1.5 is the reference build.
- **StemForge v0 `.pkg` built** at
  `/Users/zak/zacharysbrown/stemforge/v0/build/StemForge-0.0.0.pkg`.
  If it's not there, build it first:

  ```bash
  cd /Users/zak/zacharysbrown/stemforge
  bash v0/build/build-pkg.sh
  ```

  Expected pkg size: ~0.9–1.0 GB (the fused 697 MB ONNX model is
  bundled under the user component).

- A **short test `.wav` file** (< 30 seconds, 44.1 kHz stereo
  recommended). Anything drummy works; `v0/tests/fixtures/short_loop.wav`
  in the repo is a known-good choice.

---

## 2. Install

Pick one of the two install paths. Both produce identical filesystem
state.

### 2a. CLI install (recommended for repeatability)

```bash
sudo installer -pkg /Users/zak/zacharysbrown/stemforge/v0/build/StemForge-0.0.0.pkg -target /
```

### 2b. GUI install (click-through)

```bash
open /Users/zak/zacharysbrown/stemforge/v0/build/StemForge-0.0.0.pkg
```

Then click through the Installer.app wizard. Enter your admin password
when prompted.

### 2c. Expected postinstall console output

The warmup step runs once, at install, as the target user (not root),
so the CoreML MLProgram compile cache lands in *your*
`~/Library/Caches/onnxruntime`. You should see the following lines in
the installer log window (GUI) or stdout (CLI):

```
==> Pre-warming neural engine (one-time, may take 2-3 min)
    <stemforge-native warmup output, variant ft-fused>
```

If warmup succeeds, the final line will indicate the cache was
populated. If it fails, you'll see:

```
    (warmup failed — first split will pay the cold compile cost)
```

That's non-fatal — the install still completes — but it flips you into
the 125 s first-split failure mode described in §5.

### 2d. Gatekeeper / ad-hoc signing

The v0 `.pkg` is ad-hoc signed (not Developer-ID / not notarized; see
[`docs/v0-ship-spec.md`](./v0-ship-spec.md) §5). Depending on your
Gatekeeper settings, macOS may refuse to open it. Workarounds:

```bash
# Option 1 — control-click → Open (one-off GUI override).
# Option 2 — whitelist the specific pkg for Gatekeeper:
spctl --add /Users/zak/zacharysbrown/stemforge/v0/build/StemForge-0.0.0.pkg
# Option 3 — CLI install (§2a) sidesteps Gatekeeper entirely when run under sudo.
```

### 2e. Expected filesystem layout after install

Everything below should exist after a clean install. The user-scope
portion lands under the installing user's `$HOME`.

```
/usr/local/bin/stemforge-native
/usr/local/lib/libonnxruntime.1.24.4.dylib
~/Library/Application Support/StemForge/models/htdemucs_ft/htdemucs_ft_fused.onnx   # 697 MB
~/Library/Application Support/StemForge/models/manifest.json
~/Music/Ableton/User Library/Presets/Audio Effects/Max Audio Effect/StemForge.amxd
~/Music/Ableton/User Library/Presets/Audio Effects/Max Audio Effect/stemforge_bridge.v0.js
~/Music/Ableton/User Library/Presets/Audio Effects/Max Audio Effect/stemforge_loader.v0.js
```

Notes:
- If your Live 12.1.x user library lives somewhere other than
  `~/Music/Ableton/User Library`, the postinstall script reads that
  path from `~/Library/Preferences/Ableton/Live */Preferences.cfg`
  and installs the `.amxd` + `.js` pair into *your* configured
  location instead. The three M4L files always land together in the
  same directory.
- `~/stemforge/inbox`, `~/stemforge/processed`, and `~/stemforge/logs`
  are also created by the postinstall script. Processed stems will
  land under `~/stemforge/processed/<track>/`.

### 2f. Model verification

Confirm the bundled fused ONNX is intact:

```bash
shasum -a 256 ~/Library/Application\ Support/StemForge/models/htdemucs_ft/htdemucs_ft_fused.onnx
```

Expected output:

```
71828190efe191a622f9c9273471de1458fe0e108f277872d43c5c81cbe29ce9  .../htdemucs_ft_fused.onnx
```

This sha256 is the canonical value recorded in
[`v0/build/models/manifest.json`](../v0/build/models/manifest.json) and
confirmed in [`v0/state/A/fusion_succeeded.md`](../v0/state/A/fusion_succeeded.md).
If the hash differs, stop — the pkg payload is wrong, rebuild with
`bash v0/build/build-pkg.sh` and try again.

Binary sanity check:

```bash
/usr/local/bin/stemforge-native --version
```

Expected output: `0.0.0`.

---

## 3. Ableton setup

1. Launch **Ableton Live 12.1.x**.
2. Open any empty Live set (File → New Live Set is fine).
3. Open the browser (left pane, or `cmd-option-B`).
4. Browser → **Categories → Max Audio Effect**.
5. In the browser search box, type `StemForge`. The
   `StemForge.amxd` device should appear under Max Audio Effects.
6. **Drag `StemForge` onto an audio track** in your set. Live will
   load the device and the Max patch will open in the device slot.

### What the UI looks like

Per [`v0/interfaces/device.yaml`](../v0/interfaces/device.yaml)
§`ui.elements`, the device is a 400 × 260 px patch containing:

- **"StemForge"** title label (top-left).
- **"Drop audio here"** file-drop target (large, across the top).
  Accepts `wav`, `mp3`, `aiff`, `m4a`, `flac`, `ogg`.
- **Backend** dropdown — options `auto`, `demucs`, `lalal`,
  `musicai`. Default `auto`. For v0 local-only testing, leave on
  `auto` (resolves to demucs).
- **Pipeline** dropdown — options `default`, `idm_crushed`,
  `glitch`, `ambient`. Default `default`.
- **Slice beats** toggle — default on.
- **Progress bar** (horizontal, below the dropdown row).
- **Status text** line (below the progress bar).
- **Split** button (bottom right).

If any of these elements look visibly wrong (missing, garbled text,
etc.) relative to the YAML, that's a device-build regression — see
§7 for how to report it. If an element is unclear from the YAML, see
[`v0/interfaces/device.yaml`](../v0/interfaces/device.yaml) §`ui.elements`.

---

## 4. First test — dropping a `.wav`

1. Drag your short test `.wav` from Finder onto the **"Drop audio
   here"** target in the StemForge device. (You can also hit the
   **Split** button if the device has a file already queued.)
2. The device's Node-for-Max child process (`stemforge_bridge.v0.js`)
   spawns `stemforge-native forge --json-events` and begins streaming
   NDJSON events to the patch.

### Expected NDJSON event sequence

Per [`v0/interfaces/ndjson.schema.json`](../v0/interfaces/ndjson.schema.json),
the events arrive in roughly this order (one JSON object per line on
stdout):

1. `started` — one event, includes `track`, `audio`, `output_dir`.
2. `progress` — multiple, `phase` cycles through
   `loading_model → splitting → analyzing → slicing → writing_manifest`,
   `pct` climbs 0 → 100.
3. `stem` — one event per stem written (4 total for
   `htdemucs_ft_fused`: `drums`, `bass`, `vocals`, `other`), with
   the absolute `path` to each `.wav`.
4. `bpm` — one event, with detected `bpm` and `beat_count`.
5. `slice_dir` — one event per stem after beat slicing, with the
   `*_beats/` directory and slice `count` (only if the **Slice beats**
   toggle is on).
6. `complete` — one event, with `manifest` (absolute path to
   `stems.json`), `bpm`, `stem_count`, and `duration_sec`.

The device's **status text** and **progress bar** UI elements track
the `progress` events in real time.

### Expected wall time (critical)

Warmup has already happened at install time (§2c), so the CoreML
MLProgram cache is populated and the first user-facing split runs
**warm**, not cold:

- **Expected:** ~5 s of inference per 10 s of input audio (4.54 s per
  10 s segment, per [`v0/state/A/fusion_succeeded.md`](../v0/state/A/fusion_succeeded.md)).
  A 20 s input should complete in roughly 10 s of inference + a few
  seconds of file I/O + Live track-staging → **~15–30 s end-to-end**.
- **Failure mode:** if the split pauses for ~125 s on `loading_model`
  before any `progress` events advance, warmup did **not** run (see
  §2c). The install still works, but you paid the cold-compile cost
  now instead of at install. Report this — the postinstall warmup
  hook should have prevented it.

### After `complete`

The bridge's `stemforge_loader.v0.js` reads the manifest and drives
Ableton's LOM to:

- Create four new tracks in the Live set named per the stems:
  `drums`, `bass`, `vocals`, `other`.
- Load each stem `.wav` into clip slot 0 of its matching track.
- Set the Live set tempo on the master track from the manifest's
  detected BPM.

---

## 5. What to verify (acceptance checklist)

Tick each box before declaring v0 shipped.

- [ ] **All 4 stems playable.** Solo each new track
      (`drums` / `bass` / `vocals` / `other`), hit play, confirm audio
      comes out of that track in isolation.
- [ ] **Combined playback resembles the original.** Un-solo everything,
      play all four tracks together. It should sound like the input
      `.wav` (some phase/quality loss is expected; obvious artifacts
      or silence on any track is not).
- [ ] **Master tempo reflects detected BPM.** The Live transport BPM
      field should match the `bpm` value from the `bpm`/`complete`
      events. Sanity check: within ~1 BPM of the input.
- [ ] **Max Console shows no `ERROR` lines.** Open Max's console
      (Max menu → Window → Console, or from the device patch:
      `cmd-shift-M`). `warning` lines are acceptable; `error` lines
      are not.
- [ ] **Second split runs warm.** Drop a second `.wav` onto the same
      device. The inference phase should again run at ~5 s / 10 s of
      input. If it re-pays the 125 s compile cost, the CoreML cache
      is being invalidated between runs — report it.

If all five boxes are ticked, v0 is accepted. Move on to the rest of
the v0 ship close-out (PR merge cadence, issue #14 closure, etc.).

---

## 6. Known caveats / out of scope for v0

- **`StemForge.als` project template is NOT bundled.** The device
  works standalone in any Live set. Shipping a pre-populated
  `StemForge.als` template is a post-v0 follow-up blocked on the
  one-time human `skeleton.als` capture step — see
  [`docs/skeleton-als-capture.md`](./skeleton-als-capture.md) and
  issue [#12](https://github.com/ZacharySBrown/stemforge/issues/12).
- **`.pkg` is ad-hoc signed, not notarized.** Gatekeeper may prompt
  or refuse; workarounds in §2d.
- **Apple Silicon only.** `stemforge-native` is an arm64 binary.
  Rosetta / Intel is not supported; v0 spec explicitly defers
  universal2.
- **`cp -R` symlink-through quirk (#18).** Affects re-installs on a
  dev machine where the production support directories are already
  symlinked into a worktree. Clean Macs are unaffected. If you hit
  it on your dev machine, remove the old symlinks under
  `~/Library/Application Support/StemForge/` and re-run the install.
- **Fallback models not bundled.** v0 bundles only the default
  `htdemucs_ft_fused` model (the one the M4L flow calls).
  `stemforge-native --variant ft-fused` is the only working variant
  after a clean install. The Python CLI variants that reference
  `ast`, `clap`, `htdemucs`, or `htdemucs_6s` (see
  [`v0/build/models/manifest.json`](../v0/build/models/manifest.json))
  will fail to load until you manually stage those ONNX files, and
  they're post-v0 work.

---

## 7. How to report failure

If any step fails — install error, device doesn't appear in the Live
browser, Max Console shows errors, stems missing / silent, 125 s
first-split pause, etc. — collect the following before writing up
the bug:

### 7a. Screenshots

- The Live set (tracks + device UI + transport BPM visible).
- The Max Console window (full visible error trace).
- The installer window if the failure happened at install time.

### 7b. Log contents

```bash
cat ~/stemforge/logs/*.log
```

(If the directory is empty, include that fact in the report —
some failure modes never produce a log.)

### 7c. Installed filesystem state

```bash
ls -laR ~/Library/Application\ Support/StemForge/
```

Confirm which of the §2e paths actually landed.

### 7d. Binary version

```bash
stemforge-native --version
```

Expected: `0.0.0`. A mismatch or "command not found" indicates the
pkg's system component didn't install or `/usr/local/bin` is missing
from `$PATH`.

### 7e. Where to post

Post all of the above (screenshots + log + `ls -laR` output +
`--version` output) alongside a one-paragraph description of what you
did and what you expected vs. what happened. The v0 ship GitHub issue
is [#14](https://github.com/ZacharySBrown/stemforge/issues/14) until
it closes; file follow-up issues against the repo.

---

## 8. See also

- [`docs/v0-ship-spec.md`](./v0-ship-spec.md) — source-of-truth spec,
  §1 Definition of Done, §W5 workstream brief.
- [`docs/skeleton-als-capture.md`](./skeleton-als-capture.md) — W3
  output; the `.als` template handoff.
- [`v0/state/A/fusion_succeeded.md`](../v0/state/A/fusion_succeeded.md)
  — fused-model performance numbers (4.54 s warm / 125 s cold
  compile) referenced throughout this runbook.
- [`v0/build/models/manifest.json`](../v0/build/models/manifest.json)
  — canonical model sha256s and metadata.
- [`v0/interfaces/device.yaml`](../v0/interfaces/device.yaml) — UI
  element spec described in §3.
- [`v0/interfaces/ndjson.schema.json`](../v0/interfaces/ndjson.schema.json)
  — NDJSON event schema described in §4.
- [`v0/src/installer/scripts/postinstall`](../v0/src/installer/scripts/postinstall)
  — the install-time behavior described in §2c / §2e.
