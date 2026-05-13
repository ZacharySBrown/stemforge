# StemForge Configurator — Full State Dump (2026-05-13)

> A self-contained snapshot of the configurator stack as of v0.2.0 + Phase 3 + the
> 2026-05-13 on-device debugging session. Intended to be pasted into a fresh
> design session for re-architecture discussion. **No project-tree access
> required to follow this.**

---

## 1. Glossary — what every "thing" is

The names have been slipping; locking them down here.

| Name | What it is | File / location | Status |
|---|---|---|---|
| **StemForge.amxd** | The original, full-featured M4L device. Has its own UI: preset dropdown, manifest dropdown, FORGE / COMMIT / BOUNCE buttons, status text. Drives Live's LOM directly. **This is "the big device"** in my earlier shorthand. | `v0/build/StemForge.amxd`, JS in `v0/src/m4l-js/stemforge_loader.v0.js` | Works, with warts. User keeps it as-is. |
| **ConfiguratorStrip.amxd** | The new Phase 3 M4L device, built fresh. Thin horizontal strip with 7 labelled buttons (LOAD / SLICE / RECOMPUTE / RE-ANCHOR / CURATE / EXPORT / OPEN EDITOR), connection-status dot, and a "Start Server" CTA. **This is "the strip"** in my shorthand. | `v0/build/ConfiguratorStrip.amxd`, JS in `v0/src/m4l-devices/configurator-strip/js/sf_configurator.js` | Only OPEN EDITOR works reliably. Other buttons fire HTTP via `[shell]` which silently no-ops in this M4L sandbox config. |
| **Configurator Server** | Local Python FastAPI process. Holds an in-memory `ProjectSpec`. Exposes intent endpoints (`POST /intent/*`) and an SSE stream (`GET /state/stream`). Server-side native file picker. Bound `127.0.0.1` only. | `stemforge/configurator/` Python module. Entry: `stemforge-configurator` console script. Port file: `~/stemforge/.configurator_port` | Works. |
| **Popup** (or "Web UI") | The browser-rendered configurator UI. React + TS + Vite + Tailwind + shadcn + Framer Motion. Loads from `http://127.0.0.1:<port>/` in a Chrome tab. Subscribes to server SSE; fires `/intent/*` via fetch. **This is "the popup"**. | `web/configurator/`, build output served by the Python server | Renders pad state. Load button works. Commit/Export buttons exist but the underlying server handlers don't actually drive Live or persist to disk. |
| **CLI** | `stemforge` Click CLI. Headless deck-building. | `stemforge/cli.py` | Works. `stemforge deck-from-manifest` + `stemforge build-deck` are the proven .ppak production path. |
| **sf-remote** | Tiny Python CLI that fires UDP/OSC messages at the running Max/Live instance. Existing infrastructure. | `tools/sf_remote.py` | Works. Big device listens via `[udpreceive 7420]`. |

---

## 2. Current physical architecture

```
                    ┌─────────────────────┐
                    │   Live + M4L host   │
                    │                     │
   ┌───────────┐    │  ┌─────────────┐    │
   │ sf-remote │────UDP→│ StemForge   │    │
   │  (CLI)    │    │  │ .amxd       │←─── direct LOM ───→ Live tracks
   └───────────┘    │  │ (legacy)    │    │              (A/B/C/D, etc.)
                    │  └─────────────┘    │
                    │                     │
                    │  ┌─────────────┐    │
                    │  │Configurator │    │
                    │  │ Strip .amxd │── [shell] (broken) ──╳
                    │  │ (new)       │    │
                    │  └──────┬──────┘    │
                    │         │           │
                    │   messnamed launchbrowser
                    │         │           │
                    └─────────┼───────────┘
                              ↓
                       ┌────────────┐
                       │   Chrome   │
                       │  (Popup)   │←────┐
                       └─────┬──────┘     │ SSE
                             │ fetch      │
                             ↓            │
                    ┌────────────────────┴───┐
                    │ Configurator Server    │
                    │ (FastAPI, Python)      │
                    │ Holds: ProjectSpec     │──── osascript ───→ native file dialogs
                    │ Port: 7430-7440        │
                    └────────────────────────┘
```

The big arrows that are broken or missing:

- **Strip → Server (HTTP)**: dead. `[shell]` in this M4L sandbox config doesn't actually execute the curl commands the strip's JS emits. Confirmed by clicking RECOMPUTE — server logs no incoming POST. Only `messnamed("max", "launchbrowser", url)` works from the strip, which is how OPEN EDITOR launches Chrome.
- **Server → Live LOM**: doesn't exist. Python FastAPI process has no way to drive Ableton's LOM. The Configurator Server is "headless" with respect to Live.
- **Popup → Live**: same — only the server is reachable. The popup can't directly write to Live.
- **StemForge.amxd ↔ Server**: no link. Both maintain their own state.

---

## 3. Current operation surface — three meanings of "commit", two of "load"

### LOAD

| Surface | What "load" does today |
|---|---|
| StemForge.amxd's FORGE/LOAD button | Reads selected manifest from Max `[Dict sf_manifest]`. If `layout_mode: production` OR `session_tracks` populated (added today), dispatches to `loadSong()` which creates tracks + clips in Live via LOM. |
| Strip's LOAD button | Sends `POST /intent/load-manifest` via `[shell]` curl. Currently broken (shell doesn't fire). |
| Popup's Load button | Sends `POST /intent/pick-manifest` to the server, which uses `osascript` (Python subprocess) to pop a native file dialog, then internally dispatches to `handle_load_manifest`. **Works.** State lives only in the server's in-memory `ProjectSpec`. **Does NOT touch Live tracks.** |
| `sf-remote fire manifest-loader load <path>` | UDP message to the StemForge.amxd. |

**Result:** "Load" in the popup and "Load" in StemForge.amxd populate two completely independent state stores. They don't share data.

### COMMIT

| Surface | What "commit" does today |
|---|---|
| StemForge.amxd's COMMIT button | Calls `commitOffsets()` with **no args** — Dict mode. Walks Live's A/B/C/D via LOM, builds `session_tracks`, writes into the in-memory Max `[Dict sf_manifest]`. **Does NOT touch the manifest file on disk.** |
| `sf-remote fire forge commitOffsets <path>` | Same walker, but writes the file at `<path>` with an atomic rename. **This is the only path that persists to disk today.** |
| Strip → no COMMIT button | (Was deliberately excluded from the 7-button surface.) |
| Popup's Commit button | `POST /intent/commit`. Server-side handler reconciles its in-memory ProjectSpec. **Does NOT touch Live's LOM or the manifest file.** |

**Result:** Three different "commit"s, only one of which (the sf-remote path) actually persists to disk. None of them keep the popup's state in sync with Live's state.

### BOUNCE

| Surface | What "bounce" does today |
|---|---|
| StemForge.amxd's BOUNCE button | Reads A/B/C/D Live tracks, exports each clip as a fresh WAV via track.freeze + clip.crop, captures per-clip `warp_bpm`, writes a brand-new deck-shape manifest at a chosen path. This is what built `breaks-n-beats1.ppak`. |
| `sf-remote fire forge bounceTracks <path>` | UDP-fired equivalent. |
| Strip / Popup | No bounce button. |

### EXPORT (manifest → .ppak)

| Surface | What "export" does today |
|---|---|
| CLI: `stemforge deck-from-manifest <manifest> --out deck.yaml` + `stemforge build-deck deck.yaml --out out.ppak` | The proven, working .ppak production path. Reads `session_tracks` from manifest, projects onto EP-133, writes `.ppak`. |
| Popup's Export button | `POST /intent/export`. Server-side handler tries to run the same projection, but it requires `state.last_manifest_path` to be set (only set if you loaded via popup, AND the project must have valid session_tracks). Hasn't been smoke-tested end-to-end. |
| Strip's EXPORT button | `POST /intent/export` via `[shell]` curl. Broken. |

---

## 4. Where state lives — multiple disconnected sources of truth

| State | Where it lives | Updated by |
|---|---|---|
| Currently-loaded manifest content (legacy, in-Live editing) | Max `[Dict sf_manifest]` (in-memory in StemForge.amxd) | StemForge.amxd's FORGE button reading from disk |
| Live tracks/clips state | Ableton itself (LOM) | User editing + StemForge.amxd's loader creating clips |
| Configurator ProjectSpec (new) | Python server in-memory dict | Popup's Load → server's `/intent/load-manifest` |
| Manifest file on disk | `~/stemforge/decks/<name>/curated/manifest.json` (or similar) | Only `sf-remote fire forge commitOffsets <path>` OR the BOUNCE flow with explicit path |
| Audio hash cache | `~/stemforge/.audio_hash_cache.json` | Server-side at commit time |

**No two of these stay in sync today.**

---

## 5. The user's actual workflow (what they want)

Verse-swap deck for EP-133:

1. **Source material**: hand-curated WAVs from previously-forged tracks. Already on disk under `~/stemforge/processed/<slug>/curated/manifest.json` for each source song.
2. **Arrange in Live**: drop clips onto A/B/C/D session-view slots, manually choose what goes where. Trim, rearrange, taste-make.
3. **Persist the arrangement** as a deck-shape manifest on disk (with `session_tracks`).
4. **Produce a `.ppak`** from that manifest.
5. **Iterate**: re-open the deck manifest later, tweak in Live, re-persist, re-build.

This is the loop. Today only step 4 (.ppak production via CLI) and step 1 (sources on disk) are clean. Steps 2/3/5 require a mix of StemForge.amxd buttons and sf-remote terminal commands, with knowledge of which "commit" actually writes to disk.

---

## 6. Known gaps + sharp edges

### 6.1 [shell] doesn't fire commands in the strip's M4L sandbox

The strip's JS dispatches all HTTP via `outlet(4, "exec", "curl ...")` to a `[shell]` object. Confirmed by clicking RECOMPUTE — no incoming POST in the server log, no stdout in Max console. The same `[shell]` object works for `messnamed("max", "launchbrowser", url)` (OPEN EDITOR opens Chrome) because that bypasses `[shell]` entirely.

Could be sandbox / permissions / Max version specific. Not debugged to root cause; we pivoted to the popup instead.

### 6.2 COMMIT button only writes to in-memory Dict, not disk

Big device's COMMIT button fires `commitOffsets` with no arg → in-memory mutation only. To persist, the user has to fire `sf-remote fire forge commitOffsets <path>` from terminal. Surprises everyone.

Patch sketch: cache `_lastManifestPath` on load; default `commitOffsets()` to that path if no arg.

### 6.3 No "load deck manifest" path until today's patch

Deck-shape manifests (only `session_tracks`, no `stems[]`) hit the early-return in `loadFromDict` / `loadSong`. Patched today: `loadFromDict` now also dispatches to `loadSong` when `session_tracks` is populated; `loadSong` skips the stem-loading loop and goes straight to `_restoreSessionTracks`.

### 6.4 Popup state and StemForge.amxd state don't share

Click Load in the popup → server's `ProjectSpec` gets populated → popup re-renders. But nothing happens in Live. Click Forge in StemForge.amxd → Live tracks populated → popup unchanged.

### 6.5 SSE typed-event mismatch (fixed today)

Server emits `event: state\ndata: <json>` (standard SSE typed events). Frontend was using `onmessage` which only catches default unnamed events. Frontend also expected a `{type, payload}` wrapper that the server doesn't send. **Fixed today**: frontend now uses `addEventListener("state", ...)` etc. and parses `data` directly.

### 6.6 Frontend types didn't match server Pydantic shape (fixed today)

Frontend was reading `state.project_name`, `state.songs[0].scenes[0].groups[0]`, `pad.clip_id`, `group.group`, `pad.pad`. Server actually emits `state.name`, `state.songs[0].groups[0]` (no intermediate `scenes` layer), `pad.clip.path`, `group.group_id`, `pad.pad_id`. **Fixed today** by realigning the TS types to mirror Pydantic.

### 6.7 Hand-curated deck manifests have no `stems[]` AND no `layout_mode`

The breaks-n-beats1-style deck manifest is created by `bounceTracks`. It has `bpm`, `source_dir`, `session_tracks`, `notes` — that's it. No `layout_mode` field. The original loader required `layout_mode: production`. Today's patch adds the `session_tracks`-only branch so these manifests load.

### 6.8 macOS + Chrome won't honor "new window" launches

`open -na "Google Chrome" --args --new-window --app=<url>` silently drops the new-window request when Chrome is already running. AppleScript Tell-Chrome-to-make-new-window times out on AppleEvent permissions. Falls back to default browser → opens in an existing tab. Workaround: drag the tab out. Future fix: in-popup "Pop out" button using `window.open()`.

### 6.9 The strip's status dot stays amber even when connected

Cosmetic. `live.text` widget's `bgcolor` attribute doesn't re-paint on the second `bgcolor` message after the first sets it. Functional state is correct.

---

## 7. What the popup already does well

- Server-side native file dialog via osascript (full GUI permission — sidesteps the M4L sandbox entirely)
- Live SSE state subscription with reconnect semantics
- Renders the loaded ProjectSpec as a polished 4-group × 12-pad grid (`PadCanvas`)
- Tabular numeric fields, glass chrome, Inter font, Framer Motion micro-interactions (the snazzy aesthetic from Phase 3)
- 11 vitest cases passing for the hook + intent + topbar layers

---

## 8. Open architectural questions for the design session

1. **Who's the source of truth?** Three plausible answers:
   - StemForge.amxd's Max Dict (legacy authority)
   - Configurator server's ProjectSpec (new, but disconnected from Live)
   - The manifest file on disk (everyone reads/writes it; risky concurrent-write surface)
2. **How does Live's LOM get driven from a non-Max process?** The Python server can't access LOM. Options:
   - UDP/OSC bridge (sf-remote already exists). Server fires UDP at the StemForge.amxd's verb handlers.
   - Strip device becomes the LOM-side worker; popup talks to it via... what? `[shell]` doesn't work; would need UDP or a fresh transport.
   - Keep LOM-touching strictly in the legacy StemForge.amxd; popup/strip just observe.
3. **What's the canonical verb set?** Honest minimal: LOAD, COMMIT, BOUNCE, EXPORT. Each with a single sentence definition. Today there are 3+ meanings of LOAD/COMMIT — none of them aligned.
4. **Where does file-on-disk I/O happen?** Today it's split across `commitOffsets <path>` (Max JS), `bounceTracks <path>` (Max JS), `handle_load_manifest` (Python), `deck-from-manifest` (Python CLI). A unified writer would simplify reasoning.
5. **What's the strip device actually for?** If `[shell]` doesn't fire, the strip can't do operations. Three plausible answers:
   - Drop the strip; the popup is the editor. Strip is a phase-4 polish item.
   - Rewire the strip's transport over UDP (use sf_remote infrastructure). Then it can fire ops without `[shell]`.
   - Strip becomes a thin "status + Open Editor" launcher only.
6. **Does StemForge.amxd live on?** User said yes — they keep it with all its warts. But: does the new architecture observe its state? Or stay completely disjoint?
7. **What's the failure mode for "two surfaces edit the same manifest file"?** If the popup and StemForge.amxd both think they own state, who wins on disk write? Need explicit ownership rule.

---

## 9. Today's deltas (uncommitted)

In the working tree as of this dump, not yet committed:

- `stemforge/configurator/intents.py` + `server.py`: added `/intent/pick-manifest` endpoint with server-side osascript dialog
- `web/configurator/src/lib/{api,types}.ts`: added `pickManifest` HTTP client + realigned ProjectSpec/GroupSpec/PadSpec types to the Pydantic shape
- `web/configurator/src/hooks/useProjectState.ts`: switched from `onmessage` to `addEventListener("state"/"log"/"progress"/"error", ...)`, dropped the `{type, payload}` wrapper expectation
- `web/configurator/src/hooks/useIntent.ts`: added `usePickManifest` hook
- `web/configurator/src/components/{LeftRail,PadCanvas,StatusBar,TopBar}.tsx`: aligned to new types
- `web/configurator/src/test/mockEventSource.ts` + `useProjectState.test.ts`: support typed-event dispatch
- `v0/src/m4l-js/stemforge_loader.v0.js` + deploy copies: `loadFromDict` dispatches deck-shape manifests to `loadSong`; `loadSong` skips per-stem loop when no `stems[]` and goes straight to `_restoreSessionTracks`
- `v0/src/m4l-devices/configurator-strip/`: lots of debug instrumentation (shell-based `_post`, osascript file-picker plumbing, `[print SHELL_OUT]` patcher debug) — most of which is dead code now since `[shell]` doesn't fire

---

## 10. Outstanding PRs

- **PR #99** open: `fix(configurator-strip): native file pickers + Chrome app-mode editor window` — title is misleading now; it's accumulated multiple pivots. Should likely be closed or split. Tracking the strip's now-dead [shell]-based file picker.
- Today's working-tree changes are uncommitted entirely.

---

## 11. Where to push next — the user's ask

> "Get everything aligned. New browser UI, new strip, all forge/bounce/commit/save/load logic, unified common interface and set of operations. Don't blow up the current StemForge device. Just get to a consistent workflow."

This implies: design ONE set of verbs with ONE meaning each, decide ONE source of truth, route everything through it, deprecate-but-keep the legacy StemForge.amxd. Architecture choice should anchor on:

- Who can drive Live's LOM (only Max [js]; FastAPI server can't).
- Which transport actually works in the user's M4L sandbox: UDP/OSC ✓, `messnamed` ✓, `[shell]` ✗ (per the 2026-05-13 session).
- What the user actually does in a session (loop in §5 above).

---

## 12. Detailed button-by-button inventory + UX flows

This section enumerates every clickable / interactive surface across the three M4L devices, the popup, the CLI, and `sf-remote`. For each: its label, position, what it actually does, what state it touches, and where it sits in the user's mental workflow.

### 12.1 StemForge.amxd (the legacy big device) — drawn via v8ui canvas, 820×149

The device is laid out as three vertical zones:

```
┌─────────────────────────────────────────────────────────────────────────┐
│ LEFT (x 0-716)              CENTER                  RIGHT (x 716-820)   │
│ ┌─────────────────────┐                              ┌───────────────┐  │
│ │ PRESET dropdown     │                              │ FORGE/CANCEL/ │  │
│ │ "Pick preset…"      │                              │  DONE/RETRY   │  │
│ └─────────────────────┘                              │  (primary)    │  │
│ ┌─────────────────────┐                              ├───────────────┤  │
│ │ SOURCE dropdown     │                              │ COMMIT        │  │
│ │ "Pick source…"      │     (status text +           ├───────────────┤  │
│ └─────────────────────┘      progress/phase area)    │ BOUNCE        │  │
│                                                      ├───────────────┤  │
│                                                      │ EXPORT        │  │
│                                                      ├───────────────┤  │
│                                                      │ LOAD │ ANCH   │  │
│                                                      └───────────────┘  │
└─────────────────────────────────────────────────────────────────────────┘
```

#### 12.1.1 PRESET dropdown (left, top)

- **What it shows**: list of preset JSON files scanned from `presets/` and StemForge data dirs. Each preset describes a curation pipeline + UI palette + target-track layout. Examples: `production_idm`, `ambient_veil`, `brutalism`, `dub_echo`, `spectral_glitch`, `drums_only`.
- **What clicking does**: writes selection into the Max `[Dict sf_preset]`. Updates the device's internal "preset chosen?" state to true.
- **State affected**: `sf_preset` Dict (in-memory). Subsequent loads/commits read this when applying a pipeline's effect-chain templates.
- **Workflow position**: Step 1 of source-loading. Required to unlock the primary action button (state machine demands both a preset AND a source).

#### 12.1.2 SOURCE / MANIFEST dropdown (left, below preset)

- **What it shows**: list of manifests auto-scanned from canonical paths (`~/stemforge/processed/<slug>/curated/manifest.json`, plus user-configured roots). Last two items are special: `"Browse manifest..."` (opens a native file dialog) and `"Browse audio..."` (opens a dialog to pick a raw audio file to forge).
- **What clicking does**:
  - Picking a manifest entry: writes manifest content into `[Dict sf_manifest]`. Status updates to `"manifestPath: <name> · <BPM> BPM · <N stems>"`.
  - Picking "Browse manifest...": fires `[opendialog]` → file path → loads into the dict.
  - Picking "Browse audio...": fires `[opendialog sound]` → audio path → ready to forge.
- **State affected**: `sf_manifest` Dict.
- **Workflow position**: Step 2 of source-loading. With both preset + source picked, the primary action button activates.

#### 12.1.3 Primary action button (right column, top) — label cycles through FORGE / CANCEL / DONE / RETRY

- **Label states**:
  - **FORGE** (idle, ready): both preset + source picked, no operation running.
    - If audio source: runs Demucs separation → produces stems → writes a fresh curated manifest → loads clips into Live tracks.
    - If manifest source: dispatches `loadFromDict` → walks the manifest's `stems[]` (or `session_tracks` after today's patch) → creates clips on A/B/C/D session-view slots via LOM.
  - **CANCEL**: operation in progress, click to abort.
  - **DONE**: operation just completed, click to dismiss / return to idle.
  - **RETRY**: operation failed, click to re-attempt with same params.
- **State affected**: Live's LOM (tracks/clip slots), Max Dicts, and potentially filesystem (if forge writes stems).
- **Workflow position**: The main "do the thing" button. Most of every session starts here.

#### 12.1.4 COMMIT button (right column, below primary)

- **Always visible**, no state-machine gating.
- **What clicking does**: fires `commitOffsets` to the JS — **no path argument**. Walks Live's A/B/C/D session view + arrangement view, builds a `session_tracks` block, writes into the in-memory `[Dict sf_manifest]`.
- **What it does NOT do today**: write the updated manifest back to the file on disk. The on-disk version is unchanged.
- **State affected**: Max `[Dict sf_manifest]` only. Live state is unchanged.
- **Workflow position**: User believes "commit = save my arrangement." Reality is "commit = update in-memory state that no one reads." Persisting to disk requires `sf-remote fire forge commitOffsets <path>` from terminal.

#### 12.1.5 BOUNCE button (right column, below COMMIT)

- **Always visible.**
- **What clicking does**: triggers the bounce pipeline:
  1. Pre-crop metadata capture: reads each A/B/C/D clip's `warp_markers` to compute slope = displayed `warp_bpm` (since `clip.warp_bpm` is read-only/unset).
  2. Collapses each clip's loop region into its play region (`_collapseToLoopRegion`).
  3. For each clip on A/B/C/D, calls `clip.call("crop")` to render the visible loop into a fresh WAV.
  4. Writes a deck-shape manifest to a user-chosen path with `bpm`, `source_dir`, `session_tracks`, `notes`.
  5. Each clip's `warp_bpm` is tagged into the bounced WAV's TNGE chunk + per-clip in the manifest.
- **State affected**: filesystem (new WAVs + manifest), nothing in Live changes structurally (the cropped clips replace the prior clip content but stay in the same slot).
- **Workflow position**: This is the "produce a deck" action. Was used to build `breaks-n-beats1.ppak`. The output manifest is fed to the CLI `deck-from-manifest` + `build-deck` for `.ppak` production.

#### 12.1.6 EXPORT button (right column, below BOUNCE)

- **Always visible.**
- **What clicking does**: fires the **arrangement-view export** (EP-133 song mode). Walks arrangement-view clips on tracks A/B/C/D + scene markers, builds a song-mode `.ppak` (not the deck-mode kit). Uses `stemforge export-song` under the hood.
- **State affected**: filesystem (new `.ppak`).
- **Workflow position**: EP-133 song-mode export. **Different** from deck-mode `.ppak` (which goes via CLI `build-deck`). Not the verse-swap deck workflow.

#### 12.1.7 LOAD button (right column, bottom-left half of split row)

- **Always visible.**
- **What clicking does**: fires `[opendialog]` to pick an arrangement-view chunk manifest (the `prechop_manifest.json` shape, not the curated/manifest.json shape). Then `sf_arrangement_loader.js` lays out the chunks in the arrangement view across A/B/C/D.
- **State affected**: Live's arrangement view.
- **Workflow position**: For arrangement-mode loading (laying out a chunked song in arrangement view for editing).

#### 12.1.8 ANCH (anchor) button (right column, bottom-right half of split row)

- **Always visible.**
- **What clicking does**: reads Live's first cue_point (locator), back-computes the source-audio time, shells out to `stemforge re-anchor` CLI to re-cut the prechop chunks at that anchor, then reloads the arrangement.
- **State affected**: filesystem (rewritten chunks), Live's arrangement view (reloaded).
- **Workflow position**: For re-anchoring a pre-existing forge when the auto-detected downbeat was off.

#### 12.1.9 Status text + phase-progress display (center area)

- **Not a button**, but the device's main feedback surface. Shows things like:
  - `"waiting - pick a preset and a source"`
  - `"detected production manifest → song loader"`
  - `"session_tracks restored: 46 clips (A=12 B=12 C=10 D=12)"`
  - per-phase progress for FORGE operations
- **State affected**: none (display only).
- **Workflow position**: Primary user feedback channel. **Often the only signal that something worked or didn't.**

### 12.2 ConfiguratorStrip.amxd — 820×100, 7 labelled rectangles

```
┌────────────────────────────────────────────────────────────────────────────┐
│  ConfiguratorStrip                                                         │
│  ┌──────┐ ┌──────┐ ┌──────────┐ ┌──────────┐ ┌──────┐ ┌──────┐ ┌──────────┐│
│  │ LOAD │ │SLICE │ │RECOMPUTE │ │RE-ANCHOR │ │CURATE│ │EXPORT│ │OPEN      ││
│  │      │ │      │ │          │ │          │ │      │ │      │ │EDITOR    ││
│  └──────┘ └──────┘ └──────────┘ └──────────┘ └──────┘ └──────┘ └──────────┘│
│  status:                                                          ●  edit │
│  footer line — http://127.0.0.1:7430                              v0.1.0   │
└────────────────────────────────────────────────────────────────────────────┘
```

All 7 buttons go through the same per-button chain: `[live.text mode=1]` → `[t b]` → `[message <handler>]` → `[js sf_configurator]`. The JS handler is supposed to fire `outlet(4, "exec", "curl ...")` → `[shell]` → HTTP → server. **`[shell]` doesn't actually execute in this M4L sandbox config, so 6 of 7 buttons are dead.**

#### 12.2.1 LOAD

- **Intended**: fire `POST /intent/load-manifest` with an osascript-picked file path.
- **Today**: clicks; JS function runs; emits the curl command to outlet 4; `[shell]` silently drops the command. No file dialog appears, no manifest loads. Status footer shows `"waiting for file pick…"` indefinitely.
- **Workaround**: load via the popup's Load button instead.

#### 12.2.2 SLICE

- **Intended**: fire `POST /intent/slice`. (Server handler not yet implemented; currently a no-op endpoint.)
- **Today**: dead. Same `[shell]` issue.

#### 12.2.3 RECOMPUTE

- **Intended**: fire `POST /intent/recompute`. Re-run curation / refresh available clips.
- **Today**: dead. Confirmed by clicking and observing no incoming POST in server logs.

#### 12.2.4 RE-ANCHOR

- **Intended**: fire `POST /intent/re-anchor`. Re-cut prechop chunks at the current locator.
- **Today**: dead. (Server-side handler also not yet implemented.)

#### 12.2.5 CURATE

- **Intended**: fire `POST /intent/curate`. Re-run curation pipeline.
- **Today**: dead. (Server-side handler not yet implemented.)

#### 12.2.6 EXPORT

- **Intended**: fire osascript save-dialog for the `.ppak` output path, then `POST /intent/export` with that path. Server runs `deck-from-manifest` + `build-deck`.
- **Today**: dead. (Server handler partially implemented but never reached.)

#### 12.2.7 OPEN EDITOR — the one button that works

- **Intended**: open the popup URL in the user's default browser.
- **Today**: calls `messnamed("max", "launchbrowser", "http://127.0.0.1:<port>/")` which bypasses `[shell]` entirely and goes through Max's URL launcher. Opens in a new Chrome tab.
- **Caveats**: macOS pops a permission dialog the first time ("Live wants to control Google Chrome") that's easy to miss behind Live's window. Tab opens in existing Chrome session, not a new window — drag the tab out for a dedicated window.

#### 12.2.8 Status dot (right side, 14×14)

- **Color states**: green `DOT_OK` (connected), amber `DOT_WARN` (checking), red `DOT_ERROR` (server not running).
- **Today's quirk**: stays amber even when functionally connected because `live.text`'s `bgcolor` attribute message only takes effect on first write. Functional connection state (`_serverBase` set, intents fire — well, they would if `[shell]` worked) is correct underneath.

#### 12.2.9 Status text (right side, beside dot)

- Shows: `"checking…"`, `"connected"`, `"server down"`, or transient action text like `"editor opened"`, `"waiting for file pick…"`.

#### 12.2.10 Footer text (full-width, below buttons)

- Shows the server URL when connected, or last action result. Currently the most diagnostic surface on the strip.

#### 12.2.11 Version stamp (right side, below dot)

- Static text `v0.1.0` of the strip device build.

#### 12.2.12 Implicit "Start Server" CTA

- When `~/stemforge/.configurator_port` is missing, the strip's JS surfaces `"server not running — click Start Server"`. Clicking the status dot at that point fires a shell `exec stemforge-configurator &` to launch the Python server. (This CTA exists in JS but isn't visually distinct — folded into the dot.)

### 12.3 Popup (Web UI) — Chrome tab at `http://127.0.0.1:<port>/`

```
┌──────────────────────────────────────────────────────────────────────────┐
│ ◯ StemForge          verse_swap_v1                  EP133 ● connected   │ ← TopBar
│   CONFIGURATOR       loaded curated/manifest.json · 46 clips             │
├──────────┬───────────────────────────────────────────────────────────────┤
│OPERATIONS│  scene                                          4 groups  48  │
│          │  ┌─────────────────────────────────────────────┐              │
│ [Load    │  │ group A · VOCALS                            │              │
│ manifest]│  │  ┌──┐┌──┐┌──┐┌──┐┌──┐┌──┐┌──┐┌──┐┌──┐┌──┐┌──┐┌──┐         │ ← PadCanvas
│          │  │  │A1││A2││A3││A4│ ...                                       │
│ Commit   │  │  └──┘└──┘└──┘└──┘                                          │
│          │  │ group B · VOCALS (ALT)                                     │
│ Recompute│  │ group C · DRUMS                                            │
│          │  │ group D · TEXTURE / IDM                                    │
│ Export   │  │                                                            │
│          │  └─────────────────────────────────────────────┘              │
│LeftRail  │                                                               │
├──────────┴───────────────────────────────────────────────────────────────┤
│ 48.0 / 64.0 MB     A·VOCAL B·VOCAL C·DRUM D·TEXTURE     load · 842ms    │ ← StatusBar
└──────────────────────────────────────────────────────────────────────────┘
```

#### 12.3.1 TopBar — project header

- **Project name** (or "no project loaded" placeholder). Reads `state.name` (after today's schema fix).
- **Manifest microcopy** — `"loaded curated/manifest.json · 46 clips"`. Reads `state.manifest_path` and `state.clip_count`.
- **Target chip** — fixed `"EP133"` for v1.
- **Connection status** — pulsing dot + tooltip showing SSE state (idle/connecting/connected/disconnected/error).
- **State affected**: none (display only).
- **Workflow position**: At-a-glance "is the system alive?" + "what's loaded?"

#### 12.3.2 LeftRail — operations panel

Four buttons, top to bottom. Each is wired via TanStack Query mutation hooks that fire `POST /intent/*`.

##### `Load manifest` (orange accent, always enabled)

- **What clicking does (today)**: fires `POST /intent/pick-manifest` (no body). Server runs Python `subprocess.run(["osascript", "-e", "POSIX path of (choose file ...)"])`. Native macOS file dialog pops. On pick, server internally dispatches `handle_load_manifest(path)`. ProjectSpec updates. SSE state event fires. Popup re-renders.
- **State affected**: Configurator server's in-memory ProjectSpec; persistent `last_manifest_path` stored. **Does NOT touch Live's LOM.**
- **Workflow position**: "Show me a deck's structure" — the popup becomes a read-only view of the picked manifest's session_tracks block.

##### `Commit` (disabled when no project)

- **What clicking does (today)**: fires `POST /intent/commit` (no body). Server-side handler attempts to reconcile the in-memory ProjectSpec.
- **What it DOESN'T do**: walk Live (the FastAPI process can't access LOM); write the manifest file to disk (no writer path implemented).
- **State affected**: in-memory ProjectSpec; that's it.
- **Workflow position**: Currently a stub. The user-facing intent ("snapshot Live") isn't actually wired.

##### `Recompute` (disabled when no project)

- Stub. `POST /intent/recompute` handler is mostly a no-op.

##### `Export` (disabled when no project)

- **What clicking does (today)**: fires `POST /intent/export` with `{target: "ep133", out_path: <user-prompted>}`. Server projects the in-memory ProjectSpec onto EP-133 shape and writes a `.ppak`. **Untested end-to-end against a real manifest.**
- **State affected**: filesystem (new `.ppak`).
- **Workflow position**: Should be the equivalent of running CLI `deck-from-manifest` + `build-deck`. Today the CLI path is the safer bet.

#### 12.3.3 PadCanvas — main 4×12 grid

- **48 pads** (4 group rows × 12 pads each). Each pad cell shows:
  - Group letter + pad index (e.g. `A · 01`)
  - Clip filename stem (if `clip.path` is non-empty)
  - Play-mode chip (KEY / ONESHOT / LOOP)
  - Subtle group-color edge cue (cyan A, violet B, red C, green D)
- **No click interactions yet** — Phase 3 ships read-only. Hover shows tooltip; "click to assign — phase 4" on empty pads.
- **State affected**: none (display only).
- **Workflow position**: User's mental model of the deck. Currently the only place that shows "what's in this deck" without opening the manifest JSON.

#### 12.3.4 StatusBar — bottom rollup

- **Memory usage** (`48.0 / 64.0 MB`) — currently shows hardcoded cap (64 MB EP-133); used-bytes is server-supplied via `state.capacity.used_bytes`. (Server doesn't actually compute this yet, so it'll often be 0.)
- **Per-group format chips** — `A·VOCAL B·VOCAL C·DRUM D·TEXTURE`. Reads `group.format_profile`.
- **Last operation elapsed-time** — `"load manifest · 842ms"`. Reads `state.last_operation`.
- **Live progress bar** — slides in when an SSE `progress` event fires for a long-running operation.
- **State affected**: none.
- **Workflow position**: "Will my deck fit?" + "did the last thing finish?"

### 12.4 sf-remote — terminal CLI for firing UDP/OSC at the big device

```bash
uv run sf-remote fire <target> <verb> [<args>...]
uv run sf-remote dump <dict-name>
uv run sf-remote log [--follow]
uv run sf-remote status
uv run sf-remote setstate <canned-state-name>
```

#### Available `<target>`s (matched in `cmd_fire` allowlist)

- `state` — fires into `sf_state_mgr`
- `forge` — fires into `sf_forge`, the big device's orchestrator
- `preset-loader` — fires into `sf_preset_loader`
- `manifest-loader` — fires into `sf_manifest_loader`
- `settings` — fires into `sf_settings`
- `ui` — fires into `sf_ui`
- `logger` — fires into `sf_logger`

#### Key verbs the user actually fires today

| Command | Effect |
|---|---|
| `sf-remote fire forge bounceTracks <manifest_path>` | Runs the BOUNCE pipeline (same as the BOUNCE button), writing the deck manifest to the given path |
| `sf-remote fire forge commitOffsets <manifest_path>` | The disk-write variant of COMMIT. **This is the verb the COMMIT button SHOULD call but doesn't.** |
| `sf-remote fire forge reload` | Tries to reload `stemforge_loader.v0.js`. PR #74 made this work via autowatch toggle. |
| `sf-remote fire manifest-loader scanManifests` | Re-scan canonical manifest dirs |
| `sf-remote fire manifest-loader load <path>` | Load a manifest by path (UDP-driven equivalent of the dropdown) |
| `sf-remote fire forge startForge` | Equivalent to pressing the FORGE button |
| `sf-remote dump sf_manifest` | Dump the current in-memory manifest dict |

**Workflow position:** sf-remote is the "back door" for everything the device buttons should do but don't quite. Every workaround we hit involved sf-remote. The popup + strip both need to converge to NOT requiring sf-remote knowledge to do basic things.

### 12.5 CLI (`stemforge` Click commands)

Headless equivalents that compose with everything above.

#### Marquee commands for the deck workflow

| Command | What it does |
|---|---|
| `stemforge forge <audio>` | Full split → curate pipeline. Produces `~/stemforge/processed/<slug>/{stems.json, curated/manifest.json, prechop_manifest.json}`. |
| `stemforge split <audio>` | Stems-only step. Produces `stems.json`. |
| `stemforge deck-from-manifest <manifest> --out <deck.yaml>` | Reads `session_tracks` block from manifest, projects onto EP-133 deck.yaml format. |
| `stemforge build-deck <deck.yaml> --out <out.ppak>` | Reads deck.yaml, writes `.ppak`. Final step of the verse-swap workflow. |
| `stemforge export-song <manifest>` | Arrangement-view export (different from deck-mode). Uses `Ep133Projector.project_from_spec`. |
| `stemforge re-anchor <slug>` | Re-cut prechop chunks at a new downbeat. |
| `stemforge reslice-curated <slug>` | Re-cut curated bar loops at the current first downbeat. |

#### Other commands (less central to the deck workflow)

`analyze`, `clean-beats`, `create-templates`, `ep133-clear-pad`, `export`, `export-koala`, `generate-pipeline-json`, `list`, `route`.

---

## 13. The user's mental workflow — mapped to today's buttons

Here's what an experienced user (you, Zak) does to build a new verse-swap deck today, mapping each step to the actual button/command they fire and what's broken:

| # | What you want to do | Button / command you use today | Friction |
|---|---|---|---|
| 1 | Forge each source song from raw audio | `stemforge forge <audio>` (CLI) | Smooth — works via CLI |
| 2 | Open the StemForge.als template in Live | (manual, in Ableton) | — |
| 3 | Load the first source manifest into Live | StemForge.amxd: pick preset → pick source → click FORGE button (which functions as LOAD for an existing manifest) | Works but UX is muddled — "FORGE" means both "split audio" AND "load manifest" depending on source type |
| 4 | Repeat for additional source songs | Same flow — clear the previous, load the next | Repeat |
| 5 | Drag/rearrange clips across A/B/C/D | Live session view (drag) | Smooth |
| 6 | Bounce the final arrangement to a deck manifest | `sf-remote fire forge bounceTracks <out-manifest-path>` (terminal) OR BOUNCE button in StemForge.amxd | Bounce button works but the OUTPUT path is hardcoded / depends on dialog; sf-remote path is reliable but requires terminal context |
| 7 | Generate the .ppak | `stemforge deck-from-manifest <manifest> --out <yaml> && stemforge build-deck <yaml> --out <ppak>` (CLI) | Two-step CLI; could be one command |
| 8 | Import on EP-133 | Drag-drop .ppak into Sample Tool → import as project | Smooth |
| 9 | Want to tweak the deck later | (today, awkward): no clean re-open path. The big device's loader didn't accept deck-shape manifests until today's patch. Now it does, but COMMIT-button-doesn't-persist still bites. | The "iterate on an existing deck" loop is the most broken thing |

The popup + strip are supposed to make steps 3, 6, 7, 9 cleaner. Today they don't.

---

## 14. What "consistent" should look like (architectural targets)

If we were designing fresh, these are the invariants that would make the user's loop clean:

1. **ONE verb set** — `LOAD`, `COMMIT`, `BOUNCE`, `EXPORT` — each defined once with one canonical implementation. Every UI surface (popup, strip, big device) calls into that one implementation.
2. **ONE source of truth for the deck state** — likely the manifest file on disk (it's the artifact that crosses session boundaries). Live's LOM and the server's ProjectSpec are projections of the manifest; they read it on load, mutate it on commit.
3. **ONE driver for LOM operations** — only Max [js] can drive LOM. So LOM-touching ops (load clips into tracks, walk Live, bounce) must originate from a Max device. Server fires UDP at the legacy device to drive LOM.
4. **ONE failure mode** — operations succeed or surface a structured error. No "succeeds in Dict, fails on disk" silent-divergence.
5. **The popup is the editor view**, the strip is a button panel, the big device is the LOM worker. None of them store independent state.

---

## 15. End of dump

Take this to a fresh design session. The minimum questions to answer before any more code:

1. Which surface owns "do the thing" vs "show the thing"?
2. Where does the manifest file live in the lifecycle (read at load, written at commit, projected at export)?
3. How does a non-Max process drive Live (or do we just refuse to try)?
4. What's the strip's actual job — operations, or just a launcher?
5. What gets deprecated — anything?
