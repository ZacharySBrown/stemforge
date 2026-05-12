# CLI Reference

Every command, every flag, with example invocations. Two CLIs:

- **`stemforge`** — the main pipeline (split, curate, build kits, etc.).
- **`sf-remote`** — UDP client for the StemForge M4L device (log tail, fire messages, dump dicts).

Last verified against the working tree on 2026-05-12. To regenerate this
doc against current help output, run each subcommand with `--help`.

---

## `stemforge`

```
Usage: stemforge [OPTIONS] COMMAND [ARGS]...
```

### `stemforge split`

Split an audio file into stems and slice at beat boundaries.

**Synopsis:** `stemforge split [OPTIONS] AUDIO_FILE`

| Flag | Default | What it does |
|------|---------|--------------|
| `-m, --model TEXT` | `default` | Demucs model key. Options: `default`, `fine`, `6stem`. |
| `-p, --pipeline TEXT` | — | Pipeline name from `pipelines/default.yaml` (baked into manifest). |
| `-o, --output PATH` | `~/stemforge/processed` | Output root directory. |
| `--no-slice` | off | Skip beat slicing — full stems only. |
| `--no-normalize` | off | Skip peak normalization of stems before slicing. |
| `-t, --silence-threshold FLOAT` | `0.001` | RMS threshold below which beat slices are discarded. |
| `--bpm FLOAT` | (auto) | Manual BPM override. Bypasses auto-detection. |
| `--first-downbeat FLOAT` | (auto) | Manual first-downbeat-time override (seconds). |
| `--refine-downbeat` | off | Sub-beat refinement via kick-onset cross-correlation. Opt-in (assumes kick is ON the downbeat). |
| `--pre-bars INTEGER` | (auto) | Bars of intro material BEFORE bar 1 to include as additional chunks. Pass `0` to drop intro. |
| `--pad-pre-bars INTEGER` | `1` | Bars of pre-pad inside each chunk WAV (drag-extend headroom backward). |
| `--pad-post-bars INTEGER` | `1` | Bars of post-pad inside each chunk WAV (drag-extend headroom forward). |
| `--emit-partial / --no-emit-partial` | `--emit-partial` | Emit leading partial `chunk_001` capturing sub-chunk-period intro. |

**Examples:**

```bash
stemforge split track.wav                                 # default Demucs
stemforge split track.wav --model 6stem                   # 6-stem htdemucs_6s
stemforge split track.wav --pipeline glitch               # use 'glitch' pipeline
stemforge split track.wav --no-slice                      # full stems only
stemforge split track.wav --bpm 85.11 --first-downbeat 0.1   # known-good manual
```

> **Note:** `stemforge split` is missing `--time-sig`; only `forge` has it.
> See [`docs/issues/split-time-sig-flag.md`](../issues/split-time-sig-flag.md).

---

### `stemforge forge`

Integrated end-to-end forge — split + slice + curate.

**Synopsis:** `stemforge forge [OPTIONS] AUDIO_FILE`

| Flag | Default | What it does |
|------|---------|--------------|
| `--analysis PATH` | — | Ableton analysis JSON. If omitted, uses librosa beat detection. |
| `-m, --model TEXT` | `default` | Demucs model key. |
| `-s, --strategy [max-diversity\|rhythm-taxonomy\|sectional]` | `max-diversity` | Curation strategy. |
| `-n, --n-bars INTEGER` | — | Number of bars to curate. |
| `--time-sig TEXT` | `4/4` | Time signature (librosa fallback only). Format: `numerator/denominator`. |
| `-o, --output PATH` | `~/stemforge/processed` | Output root. |
| `--curation PATH` | — | Curation config YAML. When provided, delegates bar-slicing + curation to `v0/src/stemforge_curate_bars.py` and produces a production-mode manifest. Omit to use forge's built-in v1 curation path. |

**Examples:**

```bash
stemforge forge ~/Music/track.wav --curation pipelines/curation.yaml
stemforge forge ~/Music/track.wav --strategy rhythm-taxonomy -n 16
stemforge forge ~/Music/track.wav --time-sig 7/4 --bpm 138    # odd meter
```

---

### `stemforge re-anchor`

Re-cut the prechop chunks of an already-forged track at user-supplied
BPM + first_downbeat. Skips Demucs re-run.

**Synopsis:** `stemforge re-anchor [OPTIONS] TRACK_DIR`

| Flag | Default | What it does |
|------|---------|--------------|
| `--bpm FLOAT` | **required** | Manual BPM override. |
| `--first-downbeat FLOAT` | **required** | Where bar 1 starts in source audio (seconds). |
| `--pre-bars INTEGER` | (auto) | Bars of intro material BEFORE bar 1 to include. Pass `0` to drop. |
| `--pad-pre-bars INTEGER` | `1` | Bars of pre-pad inside each chunk WAV. |
| `--pad-post-bars INTEGER` | `1` | Bars of post-pad inside each chunk WAV. |
| `--emit-partial / --no-emit-partial` | `--emit-partial` | Emit leading partial `chunk_001`. |
| `--keep-old` | off | Keep previous prechop output as `<stem>_prechop.bak/`. |
| `--then-curate / --no-then-curate` | `--no-then-curate` | After re-anchor, run a fresh curation pass. Replays strategy/n_bars from the existing `curated/manifest.json`. |

**Examples:**

```bash
stemforge re-anchor ~/stemforge/processed/track --bpm 85.11 --first-downbeat 0.1
stemforge re-anchor ~/stemforge/processed/track --bpm 92 --first-downbeat 0.5 --then-curate
```

---

### `stemforge reslice-curated`

Re-cut curated bar loops at the current `stems.json` anchor. Preserves user picks.

**Synopsis:** `stemforge reslice-curated [OPTIONS] TRACK_DIR`

No flags. Use after `stemforge re-anchor` if you skipped auto-reslice
(or pre-PR when re-anchor didn't sync curated/).

For a fresh diversity selection (different picks), run
`stemforge forge --curation ...` instead.

---

### `stemforge analyze`

Analyze an audio file and recommend optimal stem split settings.

**Synopsis:** `stemforge analyze [OPTIONS] AUDIO_FILE`

| Flag | Default | What it does |
|------|---------|--------------|
| `--json-out` | off | Output raw JSON instead of formatted table. |

**Examples:**

```bash
stemforge analyze track.wav
stemforge analyze track.wav --json-out
stemforge analyze track.mp3                  # auto-converts to WAV
```

Requires the `analyzer` extra (`pip install 'stemforge[analyzer]'`).

---

### `stemforge deck-from-manifest`

Generate a starter deck plan from a curated manifest.

**Synopsis:** `stemforge deck-from-manifest [OPTIONS] MANIFEST_PATH`

| Flag | Default | What it does |
|------|---------|--------------|
| `--out PATH` | `deck.yaml` next to manifest | Where to write the deck plan. |
| `--project TEXT` | (derived) | Project name. Default: derived from manifest filename / dir. |
| `--project-slot INTEGER` | `8` | EP-133 project slot (1..9). |
| `--project-bpm FLOAT` | (from manifest) | Project BPM. Default: manifest's `bpm` field, fallback `92`. |
| `--format [yaml\|json]` | `yaml` | Output format. |
| `--edit-after / --no-edit-after` | `--no-edit-after` | Open generated plan in `$EDITOR`. |
| `--profile [vocal\|drum\|texture\|preserve_source]` | (per-group default) | Override format_profile on every group. |
| `--all-drum` | off | Shortcut for `--profile drum`. Mutually exclusive with `--profile`. |
| `--play-mode [oneshot\|key\|loop]` | (per-profile default) | Override play_mode on every pad row. |

**Examples:**

```bash
stemforge deck-from-manifest ~/stemforge/processed/track/curated/manifest.json
stemforge deck-from-manifest <manifest> --project my_kit --project-slot 8
stemforge deck-from-manifest <manifest> --all-drum                    # all drum profile
stemforge deck-from-manifest <manifest> --profile vocal --play-mode key
```

---

### `stemforge build-deck`

Build a multi-source EP-133 kit (`.ppak`) from a deck plan.

**Synopsis:** `stemforge build-deck [OPTIONS] DECK_PLAN`

| Flag | Default | What it does |
|------|---------|--------------|
| `--out PATH` | **required** | Output `.ppak` path. |
| `--reference-template PATH` | — | Captured reference `.ppak` for byte-template fields. |
| `--project INTEGER` | (from plan) | Override project slot (1..9). |
| `--write-spec / --no-write-spec` | `--write-spec` | Also write abstract `ProjectSpec` JSON next to the `.ppak`. |

**Examples:**

```bash
stemforge build-deck deck.yaml --out ~/Desktop/my_kit.ppak
stemforge build-deck deck.json --out kit.ppak \
  --reference-template tests/ep133/fixtures/reference.ppak
```

---

### `stemforge export-song`

Build an EP-133 K.O. II song-mode `.ppak` from an Ableton arrangement snapshot.

**Synopsis:** `stemforge export-song [OPTIONS]`

| Flag | Default | What it does |
|------|---------|--------------|
| `--arrangement PATH` | **required** | `snapshot.json` from M4L arrangement reader. |
| `--manifest PATH` | **required** | `stems.json` with a `session_tracks` block. |
| `--reference-template PATH` | — | Captured reference `.ppak` for byte template. |
| `--project INTEGER` | `1` | EP-133 project slot (1..9). |
| `--out PATH` | **required** | Output `.ppak` path. |
| `--mode [locator]` | `locator` | Scene-derivation mode. v1 only supports `locator`. |
| `--write-spec / --no-write-spec` | `--write-spec` | Also write ProjectSpec JSON sidecar. |

**Example:**

```bash
stemforge export-song \
  --arrangement snapshot.json \
  --manifest stems.json \
  --reference-template tests/ep133/fixtures/reference.ppak \
  --project 1 --out song.ppak
```

---

### `stemforge export`

Export stems/slices for hardware samplers. Supports EP-133 and Chompi targets.

**Synopsis:** `stemforge export [OPTIONS] [INPUT_PATH]`

| Flag | Default | What it does |
|------|---------|--------------|
| `-t, --target [ep133\|chompi\|both]` | **required** | Target device. |
| `-w, --workflow [compose\|perform]` | — | `compose`=single track deep; `perform`=multi-track curated. |
| `-o, --output PATH` | — | Output directory. |
| `--budget` | off | EP-133: render at 22050 Hz to double memory capacity. |
| `--firmware [tempo\|tape]` | — | Chompi firmware variant. |
| `--dry-run` | off | Show plan without writing files. |
| `--upload` | off | EP-133: upload samples via USB-MIDI SysEx after export. |
| `--start-slot INTEGER` | `1` | EP-133: starting sound slot for upload. |
| `--manifest PATH` | — | EP-133 v2: manifest-driven export. Loads a curated `manifest.json` and produces per-loop WAVs + `SETUP.md`. |
| `--config PATH` | — | EP-133 v2: curation config YAML. Reads `ep133_export:` block. Pairs with `--manifest`. |

**Examples:**

```bash
stemforge export track_dir/ --target ep133 --workflow compose
stemforge export processed/ --target chompi --workflow perform
stemforge export --target ep133 --manifest curated/manifest.json \
  --config pipelines/curation.yaml --output export/ep133/
```

> **Note:** for full deck-builder workflows prefer
> `deck-from-manifest` + `build-deck`. `export --target ep133` is the older
> per-slot direct-upload path.

---

### `stemforge export-koala`

Export a curated stemforge project as a Koala Sampler bank set (`.zip`).

**Synopsis:** `stemforge export-koala [OPTIONS] PROJECT_DIR`

| Flag | Default | What it does |
|------|---------|--------------|
| `--loops-per-stem INTEGER` | `4` | Loops per stem in bank 1 (4 stems × N must be ≤ 16). |
| `--oneshots-per-part INTEGER` | (auto-fill) | Cap oneshots per drum part. |
| `--output-dir DIRECTORY` | `koala_exports` | Where to write the `.zip`. |
| `--keep-unzipped` | off | Leave staging folder next to the zip (debugging). |

**Examples:**

```bash
stemforge export-koala ~/stemforge/processed/bel
stemforge export-koala ~/stemforge/processed/bel/curated --loops-per-stem 3
```

---

### `stemforge clean-beats`

Delete silent beat slices from processed folders.

**Synopsis:** `stemforge clean-beats [OPTIONS]`

| Flag | Default | What it does |
|------|---------|--------------|
| `-t, --threshold FLOAT` | `0.001` | RMS threshold. Beats below this are deleted. |
| `-d, --dir PATH` | `~/stemforge/processed` | Directory to clean. |
| `--dry-run` | off | Show what would be deleted without deleting. |

**Examples:**

```bash
stemforge clean-beats --dry-run
stemforge clean-beats --threshold 0.002 --dir ~/stemforge/processed
```

---

### `stemforge create-templates`

Build the 7 StemForge template tracks in Ableton Live.

**Synopsis:** `stemforge create-templates [OPTIONS]`

No flags. If AbletonOSC is running, sends a trigger to the M4L builder
device. Otherwise prints step-by-step instructions.

---

### `stemforge generate-pipeline-json`

Compile YAML → JSON for M4L device. Processes both `pipelines/` and `presets/`.

**Synopsis:** `stemforge generate-pipeline-json [OPTIONS]`

| Flag | Default | What it does |
|------|---------|--------------|
| `--pipeline-dir PATH` | `pipelines/` | Source directory. |

**Example:** run after editing any pipeline YAML.

```bash
stemforge generate-pipeline-json
```

---

### `stemforge list`

Show available Demucs models.

**Synopsis:** `stemforge list`

No flags.

---

## `sf-remote`

Headless remote debug client for the StemForge M4L device. Talks UDP on
port 7420 (device) / 7421 (dump return).

```
Usage: sf-remote [-h] {log, fire, dump, setstate, status} ...
```

### `sf-remote log`

Tail or clear the device's debug log.

**Synopsis:** `sf-remote log [-h] [--follow] [--clear]`

| Flag | Default | What it does |
|------|---------|--------------|
| `--follow, -f` | off | Follow new log lines (like `tail -f`). |
| `--clear` | off | Truncate the log locally AND send `clear` via UDP to `sf_logger`. |

**Examples:**

```bash
sf-remote log -f               # tail
sf-remote log --clear          # truncate locally + remote
```

---

### `sf-remote fire`

Send a UDP message to a module inside the device.

**Synopsis:** `sf-remote fire TARGET MESSAGE...`

Targets: `state`, `forge`, `preset-loader`, `manifest-loader`, `settings`,
`ui`, `logger`.

**Examples:**

```bash
sf-remote fire forge bounceTracks /path/to/curated/manifest.json
sf-remote fire state markStemDone bass
sf-remote fire ui setMode forging
sf-remote fire logger clear
```

---

### `sf-remote dump`

Dump a Max `dict` into the log and print the captured block.

**Synopsis:** `sf-remote dump DICTNAME [--timeout SECONDS]`

Dict names: `sf_state`, `sf_preset`, `sf_manifest`, `sf_settings`.

| Flag | Default | What it does |
|------|---------|--------------|
| `--timeout SECONDS` | `3` | Seconds to wait for `DUMP END` marker. |

**Example:**

```bash
sf-remote dump sf_state
sf-remote dump sf_manifest --timeout 5
```

---

### `sf-remote setstate`

Push `sf_state` JSON into the v8ui.

**Synopsis:** `sf-remote setstate TARGET`

`TARGET` is either a shortcut (`empty`, `idle`, `forging`, `done`, `error`)
or a path to a `.json` file.

**Examples:**

```bash
sf-remote setstate idle
sf-remote setstate ./test-states/forging-with-progress.json
```

---

### `sf-remote status`

Print last N log lines + dump `sf_state`.

**Synopsis:** `sf-remote status [--lines N]`

| Flag | Default | What it does |
|------|---------|--------------|
| `--lines, -n` | `60` | How many log lines to print. |

**Example:**

```bash
sf-remote status -n 100
```

---

## Install variants

| Command | Includes | Use when |
|---------|----------|----------|
| `pip install 'stemforge[native]'` | Core + torch + demucs | Standard install — local Demucs stem separation. |
| `pip install 'stemforge[analyzer]'` | Core + transformers + CLAP | You want `stemforge analyze` (genre / instrument detection). |
| `pip install 'stemforge[native,analyzer]'` | Core + native + analyzer | Local Demucs and analyzer. |
| `pip install 'stemforge[native,analyzer,dev]'` | Everything + test/lint/build tooling | Developing on StemForge. |

Running `stemforge split` without the `native` extra prints a friendly
error pointing you at the right install command. Same for `stemforge
analyze` without the `analyzer` extra.
