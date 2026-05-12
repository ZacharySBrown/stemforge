# StemForge

**StemForge is a stem-split + bar-curate + EP-133 K.O. II kit-builder for Ableton workflows.** Drop in a track, get loop-bank-ready stems and a hardware-ready `.ppak` in one pipeline.

Two surfaces share one core:

- A Python CLI (`stemforge`) that separates stems via Demucs, slices at beat or bar boundaries, curates diverse loops, and synthesizes EP-133 `.ppak` kits.
- A Max for Live device that watches Core's manifests and auto-loads clips onto template tracks in Ableton.

## Architecture

```
              ┌─────────────────────────────────────────────────┐
   audio →    │  Core (stemforge/)                              │
              │    backend.separate → slice → curate → manifest │
              └────────────────┬────────────────────┬───────────┘
                               │                    │
                  stems.json   │                    │  deck.yaml
                               ▼                    ▼
              ┌──────────────────────────┐  ┌──────────────────┐
              │ M4L (m4l/)               │  │ Tools (tools/)   │
              │ Ableton clip auto-load   │  │ sf-remote, batch │
              │ + bounce + COMMIT        │  │ scripts, exports │
              └──────────────────────────┘  └──────────────────┘
                               │                    │
                               ▼                    ▼
                         Ableton session       EP-133 .ppak
```

Three zones, one contract:

- **Core** (`stemforge/`) — CLI, backends, slicer, analyzer, curator, manifest. Zero M4L dependencies.
- **M4L** (`m4l/`, `v0/`) — Max for Live devices + JS bridge. Reads `stems.json` manifests; never imports Core code.
- **Tools** (`tools/`) — Standalone utilities and `sf-remote` (a UDP client for the M4L device). May call Core CLI; doesn't import M4L code.

`stems.json` is the contract between zones. See [`CLAUDE.md`](CLAUDE.md) for the full conventions + agent-role write scopes.

## TLDR Install

```bash
git clone git@github.com:ZacharySBrown/stemforge.git
cd stemforge
chmod +x install.sh
./install.sh
```

The installer will:
- Install Homebrew, pyenv, Python 3.11, uv (if missing)
- Create a venv with all dependencies (including PyTorch + Demucs)
- Ask for your Ableton directories and install the M4L device
- Create `~/stemforge/inbox/`, `processed/`, `logs/`
- Verify everything works

### Install Variants

StemForge ships with a lightweight core and opt-in extras for heavy ML deps.

| Command                                         | Includes                              | Use when |
|-------------------------------------------------|---------------------------------------|----------|
| `pip install 'stemforge[native]'`               | Core + torch + demucs                 | Standard install — local Demucs stem separation. |
| `pip install 'stemforge[analyzer]'`             | Core + transformers + CLAP            | You want `stemforge analyze` (genre/instrument detection). |
| `pip install 'stemforge[native,analyzer]'`      | Core + native + analyzer              | Local Demucs and analyzer. |
| `pip install 'stemforge[native,analyzer,dev]'`  | Everything + test/lint/build tooling  | Developing on StemForge. |

Running `stemforge split` without the `native` extra will print a friendly
error pointing you at the right install command. Same for `stemforge analyze`
without the `analyzer` extra.

## TLDR Usage

```bash
cd stemforge && source .venv/bin/activate

# Drop a file in the inbox, then:
stemforge split ~/stemforge/inbox/track.wav

# Pick a specific Demucs model:
stemforge split track.wav --model 6stem        # 6-stem htdemucs_6s
stemforge split track.wav --model fine         # better quality, 4x slower

# Use a pipeline preset:
stemforge split track.wav --pipeline idm_crushed
stemforge split track.wav --pipeline glitch
stemforge split track.wav --pipeline ambient

# Full stems only (no beat slicing):
stemforge split track.wav --no-slice

# See all options:
stemforge list
```

## What Happens

1. **You run** `stemforge split track.wav`
2. **Stems** are separated via Demucs (local, free)
3. **BPM** is auto-detected from the drum stem
4. **Beat slices** are cut at every beat boundary → individual WAVs
5. **`stems.json`** manifest is written with all paths + metadata
6. **Ableton** — the M4L device sees the new manifest, duplicates template tracks, loads clips, sets tempo, dials in effects from your pipeline config

## Pipelines

Pipelines live in `pipelines/` as YAML, compiled to JSON for the M4L device. Two kinds:

**Processing pipelines** (`pipelines/default.yaml`) — how stems get mixed/effected on auto-load. Four presets:

| Pipeline | Vibe |
|----------|------|
| `default` | Clean stems, warped and looped |
| `idm_crushed` | Bitcrushed, saturated — Aphex/Squarepusher |
| `glitch` | Granular reverse textures — Four Tet / BoC |
| `ambient` | Long reverbs, slow modulation — textural IDM |

**Canonical pipelines** — top-level YAMLs that drive the major workflows:

| Pipeline | Use this when... |
|----------|------------------|
| `arrangement.yaml` | You're stem-splitting a full song for Ableton arrangement view (drag-in N-bar chunks with padding bars for crossfading). |
| `curation.yaml` / `curation_nopad*.yaml` | You want exact-bar loop banks (e.g. for EP-133, Launchpad, Push). `_nopad` variants are required for EP-133 export. |
| `production_idm.yaml` | You want clips auto-loaded onto the 7 StemForge IDM template tracks (drums raw/crushed, bass, textures, vocals, beat-chop). |

After editing any YAML, regenerate JSON for the M4L device:
```bash
stemforge generate-pipeline-json
```

## Ableton Setup

See [setup.md](setup.md) for template track recipes. You build 7 tracks once:
- SF | Drums Raw
- SF | Drums Crushed
- SF | Bass
- SF | Texture Verb
- SF | Texture Crystallized
- SF | Vocals
- SF | Beat Chop Simpler

The M4L device duplicates these per stem and loads audio automatically.

## EP-133 K.O. II Workflow

You can ship a curated multi-source kit straight to an EP-133 K.O. II. The headline flow:

```bash
# 1. Forge each source track (split + curate bar loops).
stemforge forge ~/Music/track_01.wav --curation pipelines/curation.yaml

# 2. In Ableton, arrange clips on session tracks A/B/C/D, then hit COMMIT
#    in the M4L device (or sf-remote fire forge bounceTracks <manifest>).
#    This bounces + writes curated/manifest.json with a session_tracks block.

# 3. Generate the deck plan from the manifest.
stemforge deck-from-manifest ~/stemforge/decks/my_kit/curated/manifest.json \
  --project my_kit --project-slot 8

# 4. (Optional) Override format profile — useful for single-source decks.
stemforge deck-from-manifest ... --all-drum    # everything as drum pads
stemforge deck-from-manifest ... --profile vocal   # everything as vocal

# 5. Build the .ppak and drag into K.O. II Sample Tool → import as project.
stemforge build-deck deck.yaml --out ~/Desktop/my_kit.ppak
```

End-to-end: ~12 seconds for a 46-clip deck. See [`docs/guides/ep133-workflow.md`](docs/guides/ep133-workflow.md) for the full walkthrough (caveats, format profiles, the 20s per-sample cap, warp-BPM capture).

## Contributing

If you're working on the codebase (not just running it), arm the
pre-commit hooks once after cloning:

```bash
# One-time per clone — hooks live in .git/hooks/ (untracked).
uv pip install pre-commit
pre-commit install

# Sanity: run all hooks across the whole tree.
pre-commit run --all-files
```

What that enforces on every commit:

- `ruff check --fix` (lint + autofix) on `stemforge/` and `tests/`
- `ruff format` (autoformat) on `stemforge/` and `tests/`
- `ruff format --check` (hard gate, mirrors CI — catches drift the
  autoformat can't reach)
- whitespace / EOL hygiene; YAML / JSON / TOML well-formedness

CI runs the same `ruff format --check` and a `ruff check` so installing
the hook saves a round-trip when local + CI fall out of sync.

For full pre-commit configuration see [`.pre-commit-config.yaml`](.pre-commit-config.yaml).

## Known Limitations

1. **M4L track positioning** — duplicated tracks appear at source+1, not grouped. Group manually after loading.
2. **Simpler sample loading** — `load_device` may not work in all Live 12 versions. Fallback: drag from browser.
3. **VST param indices** — pipeline YAML uses descriptive names but M4L sets by index. Verify with the Inspect workflow in setup.md.
4. **Beat slicing is grid-quantized** — uses musical beat positions, not transient onsets. Adjust silence threshold for complex polyrhythms.
5. **Demucs first run** — downloads ~80MB model to `~/.cache/torch/hub/`. Cached after that.
6. **EP-133 per-sample 20s cap** — clips longer than 20s are skipped (with warning) by the kit synthesizer. Force a shorter loop region in Ableton before COMMIT.

## Pointers

- **CLI reference** — every `stemforge` and `sf-remote` flag with examples: [`docs/guides/cli-reference.md`](docs/guides/cli-reference.md).
- **EP-133 workflow guide** — full walkthrough from forge to `.ppak`: [`docs/guides/ep133-workflow.md`](docs/guides/ep133-workflow.md).
- **M4L device development** — battle-tested pitfalls, container format, deploy pipeline: `memory/m4l_device_development_guide.md` (in your Claude project memory).
- **EP-133 protocol findings** — `memory/project_ep133_*` entries cover SysEx, coupled fields, binary pad records.
- **Conventions + agent roles** (for contributors) — [`CLAUDE.md`](CLAUDE.md).
- **Latest session debrief** — what shipped and why: [`docs/sessions/2026-05-12_breaks_n_beats_complete.md`](docs/sessions/2026-05-12_breaks_n_beats_complete.md).
