# Setforge Ecosystem

Three repos, three modes, one pipeline: curate stems, perform live, arrange in the DAW.

| Repo | Role |
|------|------|
| `taste/` | Curation, recommendation, forge-set pipeline |
| `stemforge/` | Stem separation (demucs), beat detection, prechop |
| `m4l-devices/` | Max for Live devices for Ableton |

---

## Mode 1: Curation (`taste forge-set`)

Build a self-contained performance set from a list of songs.

**Pipeline steps:**

1. **register** — fetch Spotify metadata (key, energy, danceability)
2. **analyze** — detect tempo, key, groove via stemforge
3. **stem** — separate into drums / bass / other / vocals via demucs
4. **structure** — compute bar grid, curate chops
5. **materialize** — crop WAV files for each chop
6. **export** — write portable set directory with relative paths

**Output:** a directory containing `{name}.set.json`, `{name}.manifest.json` (schema 2.1), and chop WAVs. All paths are relative so the set is portable across machines.

**CLI:**

```bash
# Full pipeline
python3 -m taste forge-set my_set.yaml

# On the Mini (uses alias pointing to stemforge venv Python 3.11)
taste forge-set my_set.yaml

# Prep only (register + analyze + stem)
taste forge-set my_set.yaml --steps prep

# Curate only (structure + materialize + export)
taste forge-set my_set.yaml --steps curate
```

**Claude skill:** `/forge-set` -- tell Claude the song names, it finds the files and builds the YAML automatically.

---

## Mode 2: Live Performance (setforge-live + Launchpad)

Load a set from Mode 1 into Ableton for Launchpad-driven performance.

**Devices:**

- **setforge-loader.amxd** — audio effect on a stem bus; reads set.json + manifest.json, populates clips
- **setforge-grid.amxd** — MIDI effect on a separate MIDI track; routes Launchpad I/O to the loader

**Features:**

- 4-stem rows (drums / bass / other / vocals) x 8 chop columns
- Dual-song mode: two songs loaded simultaneously for blending
- Scene memory: recall stem + chop states per scene
- Modifier layer: HOLD / MUTE / SOLO / REV / STUT / HALF / DBL / KILL
- Curation persistence: edits saved back to manifest

**Setup requirement:** the MIDI track with setforge-grid must be armed with Monitor set to In for the Launchpad to work.

---

## Mode 3: Arrangement (stemforge + setforge-arranger)

Load stems into Ableton's arrangement view as N-bar padded clips.

- Loop regions show the content window; padding is hidden
- Re-anchor: drop locators in Live, the device recomputes the grid
- **Status:** working in stemforge v0, being ported to m4l-devices as setforge-arranger.amxd

---

## Interface Contracts

### taste outputs (consumed by m4l-devices)

| File | Purpose |
|------|---------|
| `{name}.set.json` | Set metadata, song list, chop references |
| `{name}.manifest.json` | Schema 2.1 manifest with tempo, key, chop boundaries |
| `chops/*.wav` | Cropped WAV files, one per chop |

All paths are relative. Resolved at load time by the M4L device.

### stemforge outputs (consumed by taste and m4l-devices)

| File | Purpose |
|------|---------|
| `stems/{drums,bass,other,vocals}.wav` | Demucs-separated stems |
| `prechop_manifest.json` | Beat grid + chop boundaries |
| `arrangement_manifest.json` | Bar-aligned arrangement data |

### m4l-devices consumes

- **setforge-loader** reads set.json + manifest.json (session view, Mode 2)
- **setforge-arranger** reads prechop_manifest / arrangement_manifest (arrangement view, Mode 3)

---

## Cross-Machine Setup

Two machines:

| Machine | User | SSH alias |
|---------|------|-----------|
| M2 MacBook | `zak` | `localhost` |
| Intel Mini | `zacharybrown` | `zak@mini` |

**Sync and install:**

```bash
# Sync cache + DB between machines
taste/tools/sync-machines.sh          # push to Mini
taste/tools/sync-machines.sh --pull   # pull from Mini

# Convert manifests to relative paths for portability
python3 taste/tools/make_portable.py

# Build and install all M4L devices
m4l-devices/install.sh
```

On the Mini, use the `taste` alias which points to the stemforge venv's Python 3.11.

---

## CLI Quick Reference

| Command | What it does |
|---------|--------------|
| `taste forge-set <yaml>` | Build a set from YAML (full pipeline) |
| `taste forge-set <yaml> --steps prep` | Register + analyze + stem only |
| `taste forge-set <yaml> --steps curate` | Structure + materialize + export |
| `taste forge-set <yaml> --mode arrangement` | Produce arrangement manifest too (future) |
| `python3 -m taste recommend --seed "Artist - Title"` | Get recommendations |
| `python3 -m taste taste --seed "Artist - Title"` | Taste-graph recommendations |
| `m4l-devices/install.sh` | Build + install all M4L devices |
| `taste/tools/sync-machines.sh [--pull]` | Sync between machines |
