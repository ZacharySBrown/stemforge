# StemForge

Stem splitting + beat slicing pipeline for Ableton Live IDM production.

Drop a track in, get stems + beat-sliced WAVs out, auto-loaded into Ableton via Max for Live.

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

Pipelines are in `pipelines/default.yaml` — edit to taste. Four presets included:

| Pipeline | Vibe |
|----------|------|
| `default` | Clean stems, warped and looped |
| `idm_crushed` | Bitcrushed, saturated — Aphex/Squarepusher |
| `glitch` | Granular reverse textures — Four Tet / BoC |
| `ambient` | Long reverbs, slow modulation — textural IDM |

After editing the YAML, regenerate JSON for the M4L device:
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
