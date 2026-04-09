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

## TLDR Usage

```bash
cd stemforge && source .venv/bin/activate

# Drop a file in the inbox, then:
stemforge split ~/stemforge/inbox/track.wav

# Force a specific backend:
stemforge split track.wav --backend demucs
stemforge split track.wav --backend lalal

# Use a pipeline preset:
stemforge split track.wav --pipeline idm_crushed
stemforge split track.wav --pipeline glitch
stemforge split track.wav --pipeline ambient

# Full stems only (no beat slicing):
stemforge split track.wav --no-slice

# Check LALAL.AI balance:
stemforge balance

# See all options:
stemforge list
```

## What Happens

1. **You run** `stemforge split track.wav`
2. **Stems** are separated via Demucs (local, free) or LALAL.AI (API, paid)
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

## LALAL.AI (Optional)

For cloud-based splitting with more stem types (9 stems vs Demucs' 4-6):
```bash
export LALAL_LICENSE_KEY=your_key_here
stemforge split track.wav --backend lalal --stems idm
```

## Known Limitations

1. **M4L track positioning** — duplicated tracks appear at source+1, not grouped. Group manually after loading.
2. **Simpler sample loading** — `load_device` may not work in all Live 12 versions. Fallback: drag from browser.
3. **VST param indices** — pipeline YAML uses descriptive names but M4L sets by index. Verify with the Inspect workflow in setup.md.
4. **Beat slicing is grid-quantized** — uses musical beat positions, not transient onsets. Adjust silence threshold for complex polyrhythms.
5. **Demucs first run** — downloads ~80MB model to `~/.cache/torch/hub/`. Cached after that.
