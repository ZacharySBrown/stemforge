# StemForge Configurator — Design Spec v1.0

> Supersedes `CURRENT_STATE_DUMP_2026-05-13.md`. Authored 2026-05-13 after a
> design conversation that unwound the multi-source-of-truth mess into a clean
> three-noun model. The goal of this document is to be implementable: a fresh
> Claude Code session should be able to take this and build/refactor toward it
> without further design negotiation.

---

## 0. TL;DR for the impatient

- **Three nouns**: `forge` (source material on disk), `curation` (the persistable curated artifact), `staging` (the in-Live editing surface).
- **One Max device** drives Live. **One web popup** orchestrates and inspects. `ConfiguratorStrip.amxd` is **deleted**.
- **Five verbs**: `FORGE`, `LOAD`, `COMMIT`, `BOUNCE`, `RE-ANCHOR`. Each has one meaning, one owner, one writer.
- **Staging tracks** (`STG-A`..`STG-N`, count determined by target device) are the **only** clip-backed connection between Live and the curation. The popup never sees Live's clip state directly. Live never sees the popup's curation directly. Both project through the curation file on disk.
- **Curations are documents**: named, persistable, scoped to one curation pass. The popup browses them; the device's COMMIT writes them.
- **No drag-and-drop curation in the popup**. Curation happens in Live (drag from forge tracks to staging). The popup edits curation *metadata* (target, templates, name) and triggers operations.
- **Testing**: aggressive automation. Most of the system is testable headlessly — the curation file is the contract, the device's COMMIT/LOAD/BOUNCE can be exercised via UDP without human clicking, and the popup is React + a typed API. The Live-in-the-loop dependency is isolated to one well-defined boundary.

---

## 1. Concepts and vocabulary

### 1.1 Forge

A **forge** is the output of running the StemForge pipeline on a single audio file. It produces a set of files on disk under `~/stemforge/processed/<slug>/`:

- `arrangement_manifest.json` — describes the arrangement-view chunks (longer, song-position-anchored sections of the source).
- `auto_curation_manifest.json` — describes the auto-curated short clips (loops, hits, snippets) suitable for pad assignment.
- `stems/` — the raw separated stems (drum, bass, vocal, other).
- `curated_audio/` — short WAV files referenced by `auto_curation_manifest.json`.
- `arrangement_chunks/` — WAV files referenced by `arrangement_manifest.json`.

A forge has a **slug** (e.g. `breaks-n-beats-1`) which is its identifier across the system. Forges live independently on disk; the system discovers them by scanning `~/stemforge/processed/`.

### 1.2 Curation

A **curation** is a named, persistable artifact representing one curation pass: which clips go in which pads, which config templates apply per group, what target device, when it was last bounced/exported. Curations live at `~/stemforge/curations/<name>.yaml`.

A curation is the unit of work the user iterates on. Examples: `verse_swap_v1`, `live_set_oct_2026`, `breaks-n-beats-deck`. A curation references one or more forges by slug; it does not embed clip audio (which lives in the referenced forges' `curated_audio/` or `arrangement_chunks/`).

Curations have a `type`: `deck` for hardware-export-shaped curations (target device pad grid) and `arrangement` reserved for v2 (scene-based curations for Flow B). **v1 implements `deck` only**; the `type` field exists in the schema for forward compatibility.

### 1.3 Staging

**Staging tracks** are a set of specially-named Live tracks (`STG-A`, `STG-B`, ...) whose contents reflect the active curation's `curated_layout`. The number and identity of staging tracks is determined by the curation's target device:

- EP-133 → 4 staging tracks (`STG-A` through `STG-D`)
- (Future targets) → different counts and naming

Staging tracks are the **only** path for clip-level data to flow between Live and the curation:

- **Curation → staging** happens on `LOAD curation` (one-shot population from disk).
- **Staging → curation** happens on `COMMIT` (the device walks staging and writes to the active curation file).

Non-staging tracks in Live (e.g. `FORGE/<slug>/*` source tracks, user-added audition tracks) are **invisible to the curation**. Edits there don't affect the curation; they exist for the user to audition and assemble material before deciding what to commit.

### 1.4 Active curation

At any moment, there is at most one **active curation** in the system. The active curation is:

- The curation whose `curated_layout` is currently mirrored in staging.
- The destination of the next `COMMIT`.
- Persisted server-side (not in the `.als`), keyed by Live's project file path, so it survives Live restarts.

If no curation is active, `COMMIT` is an error and the popup prompts the user to create or open one.

### 1.5 Global workspace vs local workspace (vocabulary only)

These are descriptive terms, not data structures:

- **Global workspace** = everything StemForge knows about on disk: all forges, all curations, all templates. The popup is a window into the global workspace.
- **Local workspace** = the subset currently materialized in Live: forge tracks that have been loaded, staging tracks for the active curation. Lives in the `.als` file.

The system has no "workspace" file. The global workspace is just "what's under `~/stemforge/`." The local workspace is just "what's in the current `.als`."

### 1.6 Config template

A **config template** is a Live device rack (`.adg` file) stored under `~/stemforge/templates/<name>.adg`. Templates are authored by the user in Ableton (Save Device Group). Templates apply **per-group**, not per-pad, in v1.

When a template is assigned to a curation group (e.g. group `A` → template `dry-direct`), the device loads the corresponding `.adg` onto the `STG-A` staging track. `BOUNCE` renders staging through Live, so the template's effect chain is baked into bounced audio.

Templates also apply to `FORGE/<slug>/*` source tracks at forge-load time, using the forge's `default_template` field (or a system default if unset).

---

## 2. Data model

### 2.1 Filesystem layout

```
~/stemforge/
  processed/                      # one subdir per forge, scanned for the catalog
    <forge-slug>/
      arrangement_manifest.json
      auto_curation_manifest.json
      stems/
        drum.wav
        bass.wav
        vocal.wav
        other.wav
      curated_audio/
        <clip-id>.wav             # referenced by auto_curation_manifest
      arrangement_chunks/
        <chunk-id>.wav            # referenced by arrangement_manifest

  curations/                      # one file per curation
    <curation-name>.yaml

  templates/                      # Ableton device racks
    <template-name>.adg

  bounced/                        # one subdir per curation, regenerated by BOUNCE
    <curation-name>/
      <pad-id>.wav
      bounce_manifest.json

  exports/                        # one file per export
    <curation-name>.ppak

  .stemforge_state.json           # server-side runtime state (active curation per .als)
  .configurator_port              # port file (unchanged from current)
```

### 2.2 Forge manifest schemas

**`auto_curation_manifest.json`**:

```json
{
  "schema_version": 1,
  "forge_slug": "breaks-n-beats-1",
  "source_audio": "/path/to/original.wav",
  "bpm": 138.0,
  "first_downbeat_sec": 0.142,
  "manifest_hash": "<sha256 of clips array>",
  "default_template": "dry-direct",
  "clips": [
    {
      "clip_id": "drum-bar4-8",
      "audio_path": "curated_audio/drum-bar4-8.wav",
      "stem": "drum",
      "source_bar_range": [4, 8],
      "duration_bars": 4,
      "tags": ["loop", "tight"]
    }
  ]
}
```

**`arrangement_manifest.json`**:

```json
{
  "schema_version": 1,
  "forge_slug": "breaks-n-beats-1",
  "source_audio": "/path/to/original.wav",
  "bpm": 138.0,
  "first_downbeat_sec": 0.142,
  "manifest_hash": "<sha256 of chunks array>",
  "chunks": [
    {
      "chunk_id": "drum-section-1",
      "audio_path": "arrangement_chunks/drum-section-1.wav",
      "stem": "drum",
      "source_position_sec": 0.142,
      "duration_sec": 14.2,
      "bar_position": 0,
      "duration_bars": 8
    }
  ]
}
```

The `manifest_hash` field is the SHA-256 of the canonicalized clips/chunks array. It's the stale-reference detection mechanism for curations: a curation stores the manifest_hash it was last committed against; if the forge's hash has changed, the popup surfaces "this curation references a forge that has been modified."

**Critical**: re-running auto-curation rewrites `auto_curation_manifest.json` but **never touches `curations/*.yaml`**. The stale-detection at the curation side is how the system stays safe across re-curations.

### 2.3 Curation file schema

```yaml
curation_version: 1
name: verse_swap_v1
type: deck                          # deck | arrangement (v2)
created_at: 2026-05-10T14:22:00Z
modified_at: 2026-05-13T09:14:00Z

target:
  device: ep133
  groups: 4
  pads_per_group: 12

referenced_forges:                  # derived from pad sources at COMMIT time
  - slug: breaks-n-beats-1
    manifest_hash: "abc123..."      # auto_curation_manifest hash at last commit
  - slug: dub-vault-3
    manifest_hash: "def456..."

groups:
  A:
    label: "Vocals"
    template: "dry-direct"
    pads:
      - pad_id: A01
        source:
          forge: breaks-n-beats-1
          clip_id: "vocal-bar12-16"
          audio_path: "curated_audio/vocal-bar12-16.wav"  # cached resolved path
        clip_settings:
          warp_bpm: 138.0           # captured from Live at commit
          loop_start_bar: 0
          loop_end_bar: 4
      - pad_id: A02
        source:
          forge: dub-vault-3
          clip_id: "vocal-alt-bar4"
          audio_path: "curated_audio/vocal-alt-bar4.wav"
      - { pad_id: A03 }             # empty pad
      # ... 12 total pads, empty ones are objects with just pad_id
  B:
    label: "Drums"
    template: "tight-compressed"
    pads: [...]
  C:
    label: "FX"
    template: null                  # no template = dry passthrough
    pads: [...]
  D:
    label: "Bass"
    template: "warm-saturated"
    pads: [...]

last_bounce:
  bounced_at: 2026-05-13T09:30:00Z
  manifest_path: "bounced/verse_swap_v1/bounce_manifest.json"
  pad_audio_hashes:                 # for diff detection on next bounce
    A01: "sha256..."
    A02: "sha256..."

last_export:
  exported_at: 2026-05-13T09:35:00Z
  target_format: ppak
  output_path: "exports/verse_swap_v1.ppak"
```

**Schema rules**:

- Empty pads are present in the list as `{ pad_id: X }` with no `source`. Don't omit them — the pad ordering and identity is preserved.
- `audio_path` in the `source` block is denormalized (also derivable from forge + clip_id) for resilience: if the forge moves on disk, the recorded path may still resolve. Always recompute it from the forge manifest at LOAD time for safety.
- `clip_settings` captures Live-side clip state at COMMIT (warp BPM, loop region, etc) so that on next LOAD the staging clip is restored faithfully.
- `referenced_forges` is computed at COMMIT from the union of pad sources.

### 2.4 Server-side runtime state

`~/stemforge/.stemforge_state.json`:

```json
{
  "schema_version": 1,
  "active_curation_by_als": {
    "/Users/zak/Music/Ableton/Verse Swap.als": "verse_swap_v1",
    "/Users/zak/Music/Ableton/Mashup Lab.als": "breaks-n-beats-deck"
  },
  "last_known_port": 7430,
  "last_seen_at": "2026-05-13T09:14:00Z"
}
```

This is the **only** persistent runtime state outside of curation files. It's small, server-owned, and survives Live restarts so the popup can re-attach to "the right curation" when Live reopens a known `.als`.

---

## 3. Surfaces and their roles

### 3.1 StemForge.amxd (the one Max device)

**Physical layout** (820×149, unchanged dimensions):

```
┌─────────────────────────────────────────────────────────────────────────┐
│  LEFT (x 0-716)              CENTER                  RIGHT (x 716-820)  │
│  ┌─────────────────────┐                            ┌───────────────┐   │
│  │ [ Pick source… ]    │     (status text +         │ FORGE / LOAD  │   │
│  │ <picked path/type>  │      progress / phase)     │  (label varies)   │
│  └─────────────────────┘                            ├───────────────┤   │
│                                                     │ COMMIT        │   │
│                                                     ├───────────────┤   │
│                                                     │ BOUNCE        │   │
│                                                     ├───────────────┤   │
│                                                     │ RE-ANCHOR     │   │
│                                                     └───────────────┘   │
│  [ Open Editor ]    ● connected · http://127.0.0.1:7430 · v1.0          │
└─────────────────────────────────────────────────────────────────────────┘
```

**Buttons** — only these. No PRESET dropdown, no SOURCE dropdown, no separate LOAD/ANCH split-row, no EXPORT button:

| Slot | Label | Enabled when | What it does |
|------|-------|--------------|--------------|
| Picker | `Pick source…` | always | Opens native file dialog (`[opendialog]`). Accepts audio (`.wav .aiff .mp3 .flac`) or text (`.json .yaml`). Sniffs the picked file: audio → `picked.type = "audio"`. JSON → peek shape: `arrangement_manifest` / `auto_curation_manifest` / forge directory → `"forge_manifest"`. YAML → if `curation_version` present → `"curation"`. Status text updates: `"audio: my-track.wav — ready to FORGE"` or similar. |
| Primary | `FORGE` (audio) / `LOAD FORGE` (forge manifest) / `LOAD CURATION` (curation) | source picked, no op running | Audio: runs forge pipeline via CLI subprocess. Forge manifest: creates `FORGE/<slug>/*` tracks, loads auto-curation into session view and arrangement chunks into arrangement view, applies default template. Curation: creates/recreates staging tracks per target, populates from `curated_layout`, applies templates per group, sets active curation. |
| COMMIT | (fixed) | active curation set, staging tracks present | Walks `STG-*` tracks, snapshots each slot's clip (source resolution, `clip_settings`), writes to active curation's YAML file via the server. |
| BOUNCE | (fixed) | active curation set, staging populated | Renders each staging slot's clip through Live (track freeze + crop, baking the group's template chain), writes WAVs to `~/stemforge/bounced/<curation>/`, updates curation's `last_bounce`. |
| RE-ANCHOR | (fixed) | a forge is the "active forge" (last loaded, or selected in popup) | Reads first Live locator → fires CLI `stemforge re-anchor <slug>` → reloads the forge's tracks in Live. Updates `arrangement_manifest.json` and `auto_curation_manifest.json` (new manifest_hash). |

**Footer**:

- `[ Open Editor ]` button — fires `messnamed("max", "launchbrowser", server_url)`. The only [shell]-free way that's proven to work.
- Connection dot — green when server reachable, red when not. Fix the bgcolor re-paint bug from §6.9 of the dump by using a `[live.text]` with a single dynamic color rather than re-issuing bgcolor.
- Version stamp.

**What this device does NOT have**:

- No PRESET dropdown. Presets-as-pipeline-configs are CLI args at FORGE time; presets-as-effect-chains are config templates.
- No SOURCE dropdown. The picker replaces it.
- No EXPORT button. Export lives in the popup (target-specific, output-path-specific — popup territory).
- No separate LOAD button distinct from FORGE. One primary action button whose label/behavior switches based on picker state.
- No ANCH button distinct from RE-ANCHOR. There's one re-anchor verb.

### 3.2 The popup (web UI)

**Purpose**: inspector for the global workspace + orchestrator for curation lifecycle. Not a clip editor.

**Top bar**:

- Active curation name (or "no curation active")
- Target device chip
- Save / Save as / Close active curation
- Connection status (SSE state)

**Left rail — Forges**:

- List of all forges discovered under `~/stemforge/processed/` (scan-based).
- Each forge: name, BPM, source path, clip counts (auto-curation + arrangement chunks), "loaded in Live" indicator if currently materialized, "stale" indicator if manifest_hash has changed since active curation last referenced it.
- Per-forge actions: `Load into Live`, `Unload from Live`, `Re-anchor`, `Re-curate`, `Show in Finder`.
- `Add forge…` button (file picker → calls server which dispatches device LOAD-forge).

**Center — Active curation**:

- If no active curation: empty state with "New curation…" and "Open curation…" buttons.
- If active: read-only grid view of `curated_layout` (target-shaped). Each pad shows clip name, source forge, bar range, "stale" badge if forge has changed.
- Per-group: template selector (dropdown of available templates), label field (editable), "load template to STG-X" indicator showing which template is currently applied in Live.
- Below grid: bounce status, export status, action buttons (Trigger BOUNCE in Live, Export to .ppak…).

**Right rail — Curations**:

- List of all curations under `~/stemforge/curations/`.
- Each: name, target, modified_at, last bounce/export timestamps, "active" badge if it's the active curation.
- Per-curation actions: `Open as active`, `Duplicate`, `Rename`, `Delete`.

**No drag-and-drop curation UI.** No clip browser as a drop source. Pad assignments are not editable in the popup. They are display-only, reflecting the state of the active curation as last committed.

### 3.3 CLI

Unchanged in scope from current state. Verbs:

- `stemforge forge <audio>` — produces `processed/<slug>/{arrangement_manifest, auto_curation_manifest}.json` + audio outputs.
- `stemforge re-anchor <slug> --downbeat-sec <s>` — re-cut a forge's chunks at a new downbeat.
- `stemforge re-curate <slug> [--params...]` — re-run auto-curation only.
- `stemforge bounce <curation-name>` — headless bounce. **Not** the same as the device's BOUNCE button (which requires Live). This is a degraded fallback: it renders pad audio from the source forge through a Python approximation of the template (or just dry, in v1). Useful for CI tests; user-facing BOUNCE goes through the device.
- `stemforge export <curation-name> --target ep133 --out <path>.ppak` — builds the `.ppak` from the curation's last bounce.

The server proxies these for the popup.

### 3.4 sf-remote

Unchanged in role: UDP transport for firing verbs at the legacy device. Still exists as the "back door" for debugging and as the transport the server uses to drive the device.

---

## 4. Verbs, ownership, transports

### 4.1 The verb table

| Verb | Owner (writer) | Transport | Trigger surfaces |
|------|---------------|-----------|------------------|
| FORGE | CLI subprocess | direct invocation by device JS | device (FORGE button), popup (Add forge…) |
| LOAD forge | Device Max JS (LOM) | device → LOM | device (LOAD FORGE), popup (Load into Live) |
| LOAD curation | Device Max JS (LOM) + server (active curation state) | device → LOM + server | device (LOAD CURATION), popup (Open as active) |
| COMMIT | Device Max JS (walks LOM, writes via server) | device → server → file | device (COMMIT) — only |
| BOUNCE | Device Max JS (track freeze + crop) | device → LOM + server (writes bounce manifest) | device (BOUNCE), popup (Trigger BOUNCE in Live → UDP → device button) |
| RE-ANCHOR | CLI subprocess | device → CLI | device (RE-ANCHOR), popup (Re-anchor) |
| EXPORT | CLI subprocess | server → CLI | popup (Export to .ppak…) — only |
| Unload forge | Device Max JS | device ← UDP from server | popup (Unload from Live) |
| Save as | Server (file copy + rename) | popup → server | popup |
| Switch active curation | Server + LOAD curation cascade | popup → server → UDP → device | popup |

**Rules enforced by this table**:

1. **Curation files are written by exactly one path**: device COMMIT → server → file. Server proxies the write; device originates it.
2. **Forge manifests are written by exactly one path**: CLI (forge, re-curate, re-anchor) → file.
3. **Live's LOM is touched by exactly one process**: the Max device. Everything else fires UDP at it.
4. **The popup never writes curation files directly**. It fires intents at the device which then COMMITs. The two exceptions are *metadata* edits (template assignment, group labels, target change) which the server writes directly because they don't require walking Live — but the server still writes through a single guarded path that all writers share (locking, atomic rename).

### 4.2 Transports — what works, what doesn't

From the 2026-05-13 debugging session:

- ✅ UDP (`[udpreceive]`): works. Server fires UDP at port 7420 to trigger device verb handlers.
- ✅ `messnamed("max", "launchbrowser", url)`: works. Footer's Open Editor uses this.
- ✅ Server-side `osascript`: works. Native file dialogs from the server (used for popup's Add forge…, etc).
- ❌ `[shell]` in M4L sandbox: does not fire `exec` commands. **Don't use it for anything.**
- ✅ SSE (`event: state\ndata: <json>`): works once frontend uses `addEventListener("state", ...)` (the fix from §6.5 of the dump).

The single transport rule: **device ⟷ server uses UDP and SSE**. UDP is server-to-device (intent firing). SSE is server-to-popup (state push). HTTP is popup-to-server (intents from UI). `[shell]` is dead.

### 4.3 Server intents (popup → server HTTP, server → device UDP)

The popup talks to the server via HTTP. The server, on receipt, may write to disk and/or fire UDP at the device. SSE pushes state updates back to the popup. Endpoint catalog:

| Endpoint | Method | Body | Effect |
|----------|--------|------|--------|
| `/forges` | GET | — | Scan `~/stemforge/processed/`, return forge index. |
| `/forges/{slug}/load` | POST | — | UDP → device: `forge load <slug>`. |
| `/forges/{slug}/unload` | POST | — | UDP → device: `forge unload <slug>`. |
| `/forges/{slug}/re-anchor` | POST | `{downbeat_sec}` | CLI `re-anchor`, then UDP → device: reload. |
| `/forges/{slug}/re-curate` | POST | `{params}` | CLI `re-curate`, then UDP → device: reload if loaded. |
| `/curations` | GET | — | Scan `~/stemforge/curations/`. |
| `/curations` | POST | `{name, target}` | Create empty curation file. UDP → device: create staging, set active. |
| `/curations/{name}/open` | POST | — | Set active. UDP → device: populate staging from curation. |
| `/curations/{name}/save-as` | POST | `{new_name}` | Copy file. Set new as active. |
| `/curations/{name}` | DELETE | — | Delete file (if not active). |
| `/curations/{name}/template` | PATCH | `{group, template_name}` | Update curation file. UDP → device: load template rack on group's staging track. |
| `/curations/{name}/target` | PATCH | `{device, groups, pads_per_group}` | Update curation file. UDP → device: recreate staging tracks for new target. |
| `/curations/{name}/export` | POST | `{out_path, target_format}` | CLI `export` against curation's last bounce. |
| `/curations/{name}/trigger-bounce` | POST | — | UDP → device: fire BOUNCE button. |
| `/state/stream` | GET (SSE) | — | Server-sent events for state changes. |

The device-side UDP receiver is `[udpreceive 7420]` in the existing infrastructure. Add handlers for the new verbs that aren't already covered.

---

## 5. Workflows — walked step-by-step

### 5.1 First-time forge from raw audio

1. User clicks `Pick source…` on the device. Picks `~/Music/raw/my-track.wav`.
2. Device status: `"audio: my-track.wav — ready to FORGE"`. Primary button label changes to `FORGE`.
3. User clicks `FORGE`.
4. Device JS spawns CLI subprocess: `stemforge forge ~/Music/raw/my-track.wav`. Phase updates stream to status.
5. CLI completes. Writes `~/stemforge/processed/my-track/{arrangement_manifest, auto_curation_manifest}.json` + audio outputs.
6. Status: `"forged: my-track (138 BPM, 47 clips, 12 arrangement chunks). Click LOAD to bring into Live, or open the editor."`
7. **Nothing is in Live yet.** The user can now use the popup or the device to load it.

### 5.2 Loading a forge into Live

1. User clicks `Pick source…`, picks the forge manifest. Device sniffs → curation type `forge_manifest`, primary becomes `LOAD FORGE`.
2. User clicks `LOAD FORGE`.
3. Device JS creates Live tracks: `FORGE/my-track/drum`, `.../bass`, `.../vocal`, `.../other`.
4. Each track gets the forge's `default_template` (or system default) loaded as an effect rack.
5. Session view slots on each track populated from `auto_curation_manifest.clips` (filtered by stem).
6. Arrangement view populated from `arrangement_manifest.chunks` (filtered by stem).
7. Status: `"loaded forge my-track (4 tracks, 47 session clips, 12 arrangement chunks)"`.

Alternative trigger: popup's `Load into Live` button on the forge entry. Fires `/forges/my-track/load` → server UDP → device runs the same code path.

### 5.3 Creating and committing a curation

1. User has forge `my-track` loaded. Wants to start a new curation.
2. In popup, clicks `New curation…`. Names it `verse_swap_v1`, target = EP-133.
3. Server creates `~/stemforge/curations/verse_swap_v1.yaml` with empty layout. Sets as active. UDP → device: create `STG-A`..`STG-D` tracks, empty.
4. User drags clips in Live from `FORGE/my-track/drum` session slot 5 onto `STG-B` slot 3. Trims to taste, sets warp BPM.
5. Repeats for other pads across `STG-A`..`STG-D`.
6. User clicks `COMMIT` on device.
7. Device JS walks `STG-*` tracks. For each clip in each slot, resolves: which forge does this audio path belong to? Which clip_id? What's the slot's bar range and warp state?
8. Builds a pad list per group. Sends `commit` UDP to server (or HTTP POST — see §6.1) with serialized layout.
9. Server writes to `verse_swap_v1.yaml` atomically (write-tmp + rename). Updates `referenced_forges` from new pad sources. Recomputes `modified_at`.
10. SSE pushes new state to popup. Popup grid view updates.

### 5.4 Iterating: load curation, add a new forge, save-as

This is the workflow Zak described:

1. User opens Live (fresh `.als` or existing). Popup is open.
2. Popup: clicks `verse_swap_v1` in curations list, `Open as active`.
3. Server marks active. UDP → device: create staging tracks if absent, populate pads from `verse_swap_v1.curated_layout`, apply per-group templates.
4. User auditions in Live. Decides they want to pull from a new source.
5. Popup: clicks `Add forge…` (or device picker). Picks `~/stemforge/processed/dub-vault-3/auto_curation_manifest.json`.
6. UDP → device LOAD-forge: creates `FORGE/dub-vault-3/*` tracks alongside existing staging.
7. User drags a clip from `FORGE/dub-vault-3/vocal` session slot 7 onto `STG-A` slot 9 (overwriting whatever was there).
8. User has two options now:
   - **Commit to v1**: click COMMIT. `verse_swap_v1.yaml` updates. Pad A·09 now references `dub-vault-3` instead of whatever was there before.
   - **Save as v2**: in popup, click `Save as…`, name it `verse_swap_v2`. Server copies the curation file and switches active. Next COMMIT writes to v2; v1 is preserved.

### 5.5 Bouncing and exporting

1. Active curation `verse_swap_v1` is loaded, staging is populated, user is satisfied with how it sounds in Live.
2. User clicks `BOUNCE` on device (or `Trigger BOUNCE in Live` in popup, which fires UDP at the device to press its own BOUNCE button).
3. Device JS for each staging track:
   - Solos the track.
   - For each clip slot containing a pad:
     - Triggers the clip.
     - Uses Live's track freeze + clip crop to render the pad's audio with the group's template chain baked in.
     - Writes the rendered WAV to `~/stemforge/bounced/verse_swap_v1/<pad-id>.wav`.
     - Records SHA-256 of the WAV.
   - Un-solos the track.
4. Writes `bounced/verse_swap_v1/bounce_manifest.json` with all pad paths and hashes.
5. Updates `verse_swap_v1.yaml.last_bounce` via server.
6. SSE pushes state. Popup shows "Bounced 2 minutes ago — 48 pads — Export?"
7. User clicks `Export to .ppak…` in popup. Native save dialog (osascript). Picks output path.
8. Server runs `stemforge export verse_swap_v1 --target ep133 --out <path>.ppak`. Reads `bounce_manifest.json`, projects onto EP-133 deck format, writes `.ppak`.
9. Updates `verse_swap_v1.yaml.last_export`.
10. Popup shows export success with path. User drags `.ppak` to EP-133 Sample Tool.

### 5.6 Re-anchoring an existing forge

1. User has forge `my-track` loaded. Notices the downbeat is off.
2. In Live, drops a locator at the true downbeat.
3. Clicks `RE-ANCHOR` on device (or in popup on the forge entry).
4. Device reads first Live locator's time.
5. Fires CLI: `stemforge re-anchor my-track --downbeat-sec 0.247`.
6. CLI rewrites the forge's manifests and audio chunks (new `first_downbeat_sec`, new clip start positions, new `manifest_hash`).
7. Device JS reloads `FORGE/my-track/*` tracks from the rewritten manifests.
8. **If the active curation references `my-track`**: popup shows a "forge re-anchored — curation may have stale pad refs" warning. User can `Refresh from forge` (re-derives clip refs against new manifest) or ignore.

### 5.7 Switching active curations mid-session

1. Active is `verse_swap_v1`, staging is populated.
2. User wants to work on `live_set_oct_2026` for a bit.
3. Popup: clicks `live_set_oct_2026`, `Open as active`.
4. Popup warns: "Current active curation has uncommitted staging changes. Commit before switching, or switch (changes will be lost)?"
   - **Commit**: COMMIT runs first. Then switch.
   - **Switch (discard)**: staging is repopulated from `live_set_oct_2026.curated_layout`, current Live state is overwritten.
5. After switch, `live_set_oct_2026` is active. Staging mirrors its layout. `verse_swap_v1` is on disk unchanged.

For v1, "uncommitted changes" detection can be approximate (compare current staging snapshot hash to last-committed snapshot hash). False positives are OK; false negatives must be impossible (always warn if in doubt).

---

## 6. Pre-emption — issues from current state, fixed by design

This section explicitly addresses each of the §6 "Known gaps + sharp edges" entries from the current state dump.

### 6.1 [shell] doesn't fire commands in the M4L sandbox

**Resolution**: `[shell]` is not used anywhere in the new design. All device-side HTTP-style operations go through UDP to the server, which then does whatever I/O it needs to. Server uses `osascript` for native dialogs (works); CLI subprocesses (work); file writes (work). Device uses UDP receive and `messnamed launchbrowser` only.

**Test enforcement**: a CI lint rule that fails if any `[shell]` object appears in a `.amxd` patch file. Greppable.

### 6.2 COMMIT writes only to in-memory Dict, not disk

**Resolution**: in the new design, COMMIT *always* writes to disk via the server. The device's COMMIT button fires UDP → server, server writes the curation file atomically (tmp + rename), server pushes SSE update. No in-memory-only path exists. The bug class is eliminated because no surface offers an in-memory-only COMMIT.

**Test enforcement**: integration test that fires COMMIT via UDP with a fixture Live state, then asserts the curation file on disk matches expected. No Live required — see §7.

### 6.3 No "load deck manifest" path

**Resolution**: there are no longer two manifest shapes ("production" vs "deck") competing. The schemas in §2 are explicit and versioned. Curation files have `curation_version: 1`; forge manifests have `schema_version: 1`. Device's LOAD branches on the sniffed file type, not on heuristic content shape. The legacy "session_tracks" terminology is replaced by `curated_layout.groups[*].pads`.

**Migration note**: existing `breaks-n-beats1.ppak`-style deck manifests need a migration script. See §8.

### 6.4 Popup state and StemForge.amxd state don't share

**Resolution**: the popup and device share state through the curation file on disk + SSE updates from the server. Neither holds independent authoritative state. The server's in-memory `ProjectSpec` is replaced by a thin cache over the active curation file; on any mutation it writes through to disk and re-reads.

### 6.5 SSE typed-event mismatch

**Resolution**: keep the §6.5 fix. Frontend uses `addEventListener("state", ...)` etc. Server emits typed events. Document this in the API spec.

### 6.6 Frontend types don't match server Pydantic shape

**Resolution**: in v1, the Pydantic shapes for `Curation`, `ForgeManifest`, `Pad`, etc. are defined in `stemforge/configurator/schemas.py` and a TypeScript client is **generated from them** via `datamodel-codegen` or similar (or hand-mirrored with a CI check that diffs them). Manual type drift is eliminated.

**Test enforcement**: CI step that regenerates the TS types and fails the build if the regenerated output differs from the committed file.

### 6.7 Hand-curated deck manifests have no schema fields

**Resolution**: all curation files have `curation_version`, `type`, `target`, etc. as required fields. Old files get migrated (§8). The device's LOAD verb rejects files without `curation_version` with a clear error.

### 6.8 macOS + Chrome won't honor "new window" launches

**Resolution**: keep the current workaround (open in default browser; user drags tab out). Add a "Pop out" button inside the popup that calls `window.open(location.href, "stemforge", "popup,width=1200,height=800")`. The popup itself becomes responsible for the new-window-ness, sidestepping the OS-level launcher issue.

### 6.9 Strip's status dot stays amber

**Resolution**: strip is deleted. Footer status dot on the main device uses a different rendering approach: `[live.text]` with `mode 1` (toggle-style) and a JS-set color via `setattr bgcolor <r> <g> <b>` issued exactly once per state change, not as a continuous stream. If the bgcolor-resets-once bug recurs on the main device, an alternative is using `[lcd]` or a custom drawn rect via `js` and `mgraphics`.

**Test enforcement**: visual smoke test exists but isn't blocking. Manual eyeball during release.

---

## 7. Testing strategy — automate aggressively

> The historical pain has been "loops with Zak loading and clicking in Ableton." Designing this away is a primary goal of v1.

### 7.1 The testability surface

The system has four boundaries, in decreasing order of testability:

1. **CLI** — pure Python subprocesses with file I/O. **100% headless testable**.
2. **Server** — FastAPI process with file I/O and UDP out. **100% headless testable** with UDP mocked or captured.
3. **Popup** — React + TS, fetches from server. **100% headless testable** with vitest + msw mocks.
4. **Device Max JS** — runs inside M4L, touches LOM. **Partially headless testable** (see §7.5).

The strategy: make boundaries 1-3 cover as much of the design as possible. Push functionality *out* of the device JS where it can live in the server or CLI. Treat the device as a thin LOM-touching shim that delegates everything else.

### 7.2 What lives where (for testability)

| Logic | Lives in | Why |
|-------|----------|-----|
| Curation file schema validation | Pydantic / Python | Testable in isolation. |
| Curation file write (atomic, locked) | Server | Testable with tmp dirs. |
| Forge discovery / scanning | Server | Testable with fixture filesystems. |
| Pad source resolution (forge + clip_id → audio_path) | Server | Pure function over manifest. Highly testable. |
| Template-to-rack mapping | Server | Just a registry lookup; pure. |
| Bounce target spec construction | Server | Returns "render these slots through these templates"; the device just executes. |
| Export pipeline | CLI | Pure file-in / file-out. |
| UDP message envelope construction | Server | Pure function. |
| **LOM walking (COMMIT) and clip creation (LOAD)** | **Device JS** | **Cannot be lifted out**. But: the device JS should be a thin walker that emits a structured snapshot to the server, which then validates and writes. |

The result: the device JS becomes much simpler than it is today (it's currently doing schema work, file I/O, and orchestration). It becomes "given this UDP intent, walk this part of LOM and report back" or "given this curation snapshot from the server, create these clips on these tracks." The decisions live in the server, which is testable.

### 7.3 Test pyramid

**Unit tests** (vitest + pytest):

- Curation schema parsing (Pydantic) — happy path + every malformed field.
- Server endpoint handlers with mocked filesystem (`pyfakefs`) and mocked UDP out (capture sent bytes).
- Frontend hooks and components with msw-mocked server.
- CLI commands with `click.testing.CliRunner` over tmpdirs.

**Integration tests** (pytest, no Live):

- End-to-end via the server: create curation → mock device commit (server-side fixture function that simulates what device would send) → assert curation file contents.
- Forge scan against a fixture `~/stemforge/processed/` tree.
- Stale-reference detection: load a curation referencing forge X, mutate X's manifest_hash, assert popup state shows stale.
- Switch active curation: verify UDP message envelope sent by server, verify `.stemforge_state.json` updates.

**Device-JS unit tests** (Node + Max stubs):

- Mock `LiveAPI` and `Dict` objects.
- Test the COMMIT walker: given a stubbed `STG-*` track with clips at specific slots, produce the snapshot object the server expects.
- Test the LOAD curation: given a curation snapshot, produce the sequence of LOM calls (assert the call log).
- Test the picker sniffer: given various file paths, return the correct routed type.

**Live-in-the-loop tests** (manual or semi-automated):

- A small suite of "smoke tests" that require Live open with a fixture `.als`. Run once per release.
- Each test is scripted via `sf-remote`: load fixture forge → COMMIT → assert curation file. Or: load curation → assert STG-* track count + clip slot contents (via a `sf-remote dump` of LOM state).
- These tests fire from a CI runner that has Live installed (a dedicated mac mini, ideally). The runner triggers Live to open a fixture `.als` via AppleScript, then runs the sf-remote sequence, then asserts.

### 7.4 Fixture infrastructure

Build a fixture library under `tests/fixtures/`:

- `tests/fixtures/forges/` — pre-baked forge directories (small synthetic audio, complete manifests).
- `tests/fixtures/curations/` — sample curation files at various states (empty, partial, bounced, exported, stale).
- `tests/fixtures/als/` — minimal Live project files with known track configurations.
- `tests/fixtures/lom_snapshots/` — captured JSON snapshots of LOM state at specific moments (what `sf-remote dump` would return after a specific setup). Tests use these instead of live LOM.

The LOM snapshot library is the key new piece. Today the only way to know what LOM looks like in a given state is to ask Live. By capturing snapshots once and replaying them, the device JS becomes testable without Live running.

### 7.5 Mocking Max JS environment for tests

Stand up a `max-stub.js` module under `tools/test-harness/` that exposes the same API as Max's JS environment: `Dict`, `LiveAPI`, `outlet`, `messnamed`, etc. Each implemented as a programmable mock that test code can configure ("when `LiveAPI.get_path('live_set tracks 0 clip_slots 5 clip')` is called, return this captured clip object").

Then the device JS imports unchanged in Node, and tests drive it directly:

```js
// tests/device-js/commit.test.js
import { stubMax } from '../tools/test-harness/max-stub.js';
import lomSnapshot from '../fixtures/lom_snapshots/four-pads-on-stg-a.json' assert { type: 'json' };
import { commitOffsets } from '../../v0/src/m4l-js/stemforge_loader.v0.js';

test('COMMIT produces expected pad snapshot for 4-pad STG-A state', () => {
  stubMax(lomSnapshot);
  const sentMessages = [];
  stubMax.captureOutletMessages(sentMessages);
  commitOffsets();
  expect(sentMessages).toContainEqual({
    udpTo: 'server', verb: 'commit',
    payload: expect.objectContaining({
      groups: { A: { pads: expect.arrayContaining([
        { pad_id: 'A01', source: { /* ... */ } }
      ])}}
    })
  });
});
```

This is the breakthrough for the historical Live-in-the-loop pain. Once `max-stub.js` covers the LOM API surface the device JS actually uses, device JS development moves entirely into the test loop.

### 7.6 What still requires Live

A short, well-defined list:

- **BOUNCE rendering** — actual audio comes out of Live; this is the whole point. Cannot be mocked. But: the *control* of the bounce (which slots to render, what template each gets) is server-side and testable. The unmockable part is Live's audio engine.
- **Template-rack loading on tracks** — Max API `loadbang` style operations that depend on Live actually parsing the `.adg` file. Stubbable for unit tests; live for integration.
- **The visual M4L UI** — pixel-level rendering of the device. Manual smoke test.

Everything else has a path to headless testing. The current "load + click in Ableton" loop should drop from "every change" to "once per release for the smoke suite."

### 7.7 CI structure

```
.github/workflows/
  ci-server.yml        # pytest, mypy, ruff on Python
  ci-popup.yml         # vitest, tsc, eslint on web/configurator/
  ci-cli.yml           # pytest CliRunner tests
  ci-device-js.yml     # vitest + max-stub on v0/src/m4l-js/
  ci-integration.yml   # pytest covering server ↔ CLI ↔ filesystem
  ci-types.yml         # regenerate TS types from Pydantic, diff against committed
  ci-smoke-live.yml    # gated, manual trigger, runs on the live-equipped runner
```

All of `ci-server` / `ci-popup` / `ci-cli` / `ci-device-js` / `ci-integration` / `ci-types` run on every PR. `ci-smoke-live` runs on release branches or manually.

---

## 8. Migration from current state

Ordered checklist. Each step should leave the system in a working state (the user can still build a `.ppak` after each step).

### Step 1 — Pre-work, no behavior changes

- [ ] Rename `~/stemforge/processed/<slug>/curated/manifest.json` → `auto_curation_manifest.json`. Add a compatibility shim in CLI / device that reads both paths for a release.
- [ ] Add `arrangement_manifest.json` as a separate file (today, arrangement data is embedded in the same file or computed on the fly — extract it).
- [ ] Add `schema_version` and `manifest_hash` fields to both manifests. Backfill hash from existing data.
- [ ] Write a `stemforge migrate` CLI command that does the above for an existing forge.

### Step 2 — Curation file schema and write path

- [ ] Define Pydantic models for `Curation`, `Group`, `Pad`, `Target`, etc.
- [ ] Add server endpoint `POST /curations` (create empty).
- [ ] Add server endpoint `POST /curations/{name}/commit` (receives device snapshot, writes file).
- [ ] Generate TS types from Pydantic.
- [ ] Tests: round-trip parse → write → re-parse for fixture curation files.

### Step 3 — Device's new picker + LOAD-curation behavior

- [ ] Add the unified `Pick source…` button, replacing PRESET and SOURCE dropdowns.
- [ ] Implement file-type sniffer in device JS.
- [ ] Primary button label switches based on picked type.
- [ ] LOAD-curation code path: device receives curation YAML (via UDP or by reading file), creates `STG-*` tracks, populates pads.
- [ ] Tests: `max-stub.js` + lom_snapshots fixture; verify staging track creation for EP-133 target.

### Step 4 — COMMIT writes through server

- [ ] Device COMMIT walks staging tracks (not A/B/C/D as before).
- [ ] Device serializes snapshot, sends UDP `commit` to server.
- [ ] Server validates, writes curation file atomically.
- [ ] Device's old in-memory-only COMMIT path is removed.
- [ ] Tests: stub device → server → fixture-fs → assert file contents.

### Step 5 — Popup as orchestrator

- [ ] Remove the popup's current drag-and-drop curation UI (LeftRail's Commit/Recompute/Export). Replace with the panels in §3.2.
- [ ] Implement curations list with Open/Save-as/Delete.
- [ ] Implement forges list with Load/Unload/Re-anchor.
- [ ] Wire popup → server endpoints from §4.3.
- [ ] Tests: vitest + msw for each panel.

### Step 6 — Templates

- [ ] Define template directory and `.adg` discovery.
- [ ] Add template assignment per group in curation file.
- [ ] Device JS loads `.adg` onto `STG-*` track on template change UDP.
- [ ] Popup template selector wired up.
- [ ] Tests: curation parse with templates; UDP envelope verification.

### Step 7 — BOUNCE refactor

- [ ] BOUNCE reads from active curation's `curated_layout`, not from walking A/B/C/D.
- [ ] Output goes to `~/stemforge/bounced/<curation-name>/`.
- [ ] Updates curation's `last_bounce`.
- [ ] Tests: server-side spec construction; device-side stubbed render call sequence.

### Step 8 — EXPORT via server

- [ ] Popup's Export button calls `POST /curations/{name}/export`.
- [ ] Server runs CLI `stemforge export`.
- [ ] Updates curation's `last_export`.
- [ ] Device's EXPORT button is removed (already absent in the new design, just confirming).

### Step 9 — Delete the strip

- [ ] Remove `v0/src/m4l-devices/configurator-strip/` entirely.
- [ ] Remove `v0/build/ConfiguratorStrip.amxd`.
- [ ] Close PR #99 (or merge minimally if anything in it is salvageable for the main device's footer).
- [ ] Move "Open Editor" button into StemForge.amxd's footer.

### Step 10 — Active curation persistence

- [ ] Implement `.stemforge_state.json` server-side.
- [ ] On Live `.als` open, device pings server with `.als` path; server returns last-known active curation.
- [ ] Tests: state file read/write round-trip; `.als` path keying.

### Step 11 — Stale-reference detection

- [ ] On forge re-anchor / re-curate, server updates the forge's manifest_hash.
- [ ] Popup compares active curation's referenced_forges hashes vs current forge hashes; surfaces stale badges.
- [ ] "Refresh from forge" button re-derives pad refs.

### Step 12 — Smoke test suite

- [ ] Build the `tests/fixtures/lom_snapshots/` library.
- [ ] Build the `max-stub.js` test harness.
- [ ] Set up CI workflows from §7.7.
- [ ] Wire up live-runner CI (longer-term).

---

## 9. Things explicitly deferred to v2

These are mentioned to prevent scope creep in v1 implementation. Each has a "we will not block on this" tag.

- **`type: "arrangement"` curations** — scene-based curations for Flow B (mashup/performance). v1 ships `type: "deck"` only. The schema reserves the field.
- **Per-pad templates** — v1 is per-group only.
- **Targets other than EP-133** — schema supports `target.device` as a string, but only `ep133` is wired through. MPC / OP-1 / etc. require pad-grid spec work that's out of scope.
- **Variable pads-per-group** — schema has `pads_per_group`, v1 hardcodes 12 (EP-133 default).
- **Popup drag-and-drop from clip browser** — explicitly rejected per design conversation. Curation happens in Live.
- **Multi-curation simultaneous editing** — one active curation at a time. Switching is supported; concurrent isn't.
- **Workspace files / project files at a level above curations** — the global workspace is just the filesystem; no project file groups multiple curations together. Could add later.
- **In-Live editing of forge metadata** — re-anchor and re-curate are operations, but the user can't edit forge tags or BPM directly. Forge metadata is CLI-owned.
- **The auto-create-on-startup of staging tracks** — if a Live `.als` opens with no `STG-*` tracks and no active curation, the device does nothing. Staging is created when a curation becomes active. (If this is annoying in practice we can revisit.)
- **Conflict resolution on concurrent writes** — assume one user, one Live, one popup. If the user edits the curation file by hand while Live is running, last-writer-wins. (Realistic for one-human workflow.)

---

## 10. Glossary recap

| Term | Definition |
|------|------------|
| **Forge** | A processed audio source on disk. Slug-identified. Has arrangement and auto-curation manifests. |
| **Curation** | A named, persistable artifact representing one curation pass. `.yaml` file under `~/stemforge/curations/`. |
| **Active curation** | The currently-open curation. There is at most one. Persisted server-side keyed by `.als` path. |
| **Staging** | Live tracks `STG-A`..`STG-N` whose contents mirror the active curation's `curated_layout`. Count determined by target device. |
| **Pad** | A single slot in a curation's `curated_layout`. Has a `pad_id` like `A01`, a `source` (forge + clip_id), and `clip_settings`. |
| **Group** | A row of pads in a curation. Has a label, a template, and pads. EP-133 has 4 groups. |
| **Template** | A Live device rack (`.adg`) applied per-group. Baked into bounced audio. |
| **Target** | The device the curation is being built for. EP-133 in v1. |
| **Global workspace** | Descriptive: everything under `~/stemforge/`. Not a data structure. |
| **Local workspace** | Descriptive: what's currently in Live's `.als`. Not a data structure. |

---

## 11. Build order suggestion

For a fresh Claude Code session, I'd recommend tackling the migration steps in this order:

1. **Steps 1-2** together: get the file shapes right, lock in schemas, generate types. This is foundational and unblocks everything else.
2. **Step 4** (COMMIT writes through server) — the keystone fix. Once this works, the architecture's promise holds.
3. **Step 3** (picker + LOAD-curation) — the device's new entry point.
4. **Step 5** (popup as orchestrator) in parallel — the popup work doesn't depend on Steps 3-4 strictly.
5. **Steps 6-8** (templates, BOUNCE, EXPORT) as features layer on.
6. **Step 9** (delete the strip) — cleanup, do it before Step 10 so there's nothing to keep alive in parallel.
7. **Steps 10-11** (state persistence, stale detection) — polish.
8. **Step 12** (testing infrastructure) — woven in as you go, not at the end. Specifically: don't implement Step 4 without the COMMIT test harness in place first. Don't implement Step 3 without the picker sniffer unit tests. Etc.

The biggest payoff from doing testing first: Step 4 alone has historically been the source of half the dump's pain. With a server-side commit endpoint that's testable with a fixture device snapshot, you can iterate on the COMMIT logic without Live open. That's the change that buys back the most time.

---

*End of spec. Drop into a Claude Code session with `SPEC.md` filename and start at Step 1.*
