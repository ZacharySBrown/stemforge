---
name: forge-run
description: Run the StemForge `forge` pipeline (split → slice → curate) on an audio file and report the manifest path. Use when the user asks to forge/process/run a track (e.g. "forge ~/Music/loop.wav", "run forge with rhythm-taxonomy on this", "split this with lalal and curate 8 bars"). Wraps `uv run stemforge forge`, streams NDJSON progress events, plan-then-confirm.
allowed-tools: Bash(uv run stemforge forge:*), Bash(uv run --directory*:*), Bash(stemforge forge:*), Bash(ls:*), Bash(cat:*), Bash(jq:*), Read
---

# forge-run — split → slice → curate one track

Wraps `stemforge forge` with sensible defaults so the user can say:

- *"forge ~/Music/setting_sun.wav"*
- *"run forge with lalal and 16 bars"*
- *"forge this with rhythm-taxonomy strategy"*
- *"forge it with the curation v2 config"*

…and you just do it.

## How to invoke

The CLI is `stemforge forge`. Always run via `uv` against the StemForge repo:

```bash
uv run --directory /Users/zak/zacharysbrown/stemforge stemforge forge <audio> [options]
```

(If the user's shell already has `stemforge` on PATH from an editable install, the bare form `stemforge forge ...` also works — try that first; fall back to `uv run --directory` on command-not-found.)

## Required from the user

- **Audio path** — absolute or relative path to a `.wav` (or any format `ensure_wav` can convert) on disk.

## Defaults you supply

- `--backend demucs` (local, no API credits)
- `--strategy max-diversity`
- `--n-bars 14`
- `--time-sig 4/4` (only used if no Ableton analysis JSON is supplied)
- No `--output` — defaults to `PROCESSED_DIR` inside the repo
- No `--analysis` — uses librosa beat detection
- No `--curation` — uses the legacy v1 curation path

If the user mentions any of these explicitly, override.

## Override etiquette

| User says | Pass to CLI |
|-----------|-------------|
| "with lalal" / "use lalal" | `--backend lalal` |
| "with musicai" | `--backend musicai` |
| "use the htdemucs_ft model" | `--model htdemucs_ft` |
| "rhythm taxonomy" / "by rhythm" | `--strategy rhythm-taxonomy` |
| "sectional" / "by section" | `--strategy sectional` |
| "16 bars" / "n=8" | `--n-bars 16` / `--n-bars 8` |
| "in 3/4" / "waltz time" | `--time-sig 3/4` |
| "output to ~/forged" | `--output ~/forged` |
| "use the v2 curation" / "use pipelines/curation.yaml" | `--curation pipelines/curation.yaml` |
| "use my Ableton analysis at X" | `--analysis X` |

## Plan-then-confirm

Forge is **expensive** — Demucs runs locally and takes 30s–several minutes per stem; LALAL/MusicAI burn API credits. **Always show the plan first** and ask *"run forge?"* unless the user already said something definitive like *"go ahead and forge it"* / *"do it"* / *"--just do it"*.

Plan to show:

```
  Plan:
    audio:    ~/Music/setting_sun.wav
    backend:  demucs (model=default)
    strategy: max-diversity
    n_bars:   14
    output:   <repo>/processed/setting_sun/
```

After the user confirms, run for real and stream the NDJSON output so they can see progress.

## Streaming the output

`stemforge forge` emits newline-delimited JSON events on stdout:

```json
{"event": "started", "track": "...", "audio": "...", "backend": "demucs", "n_bars": 14, "output_dir": "..."}
{"event": "progress", "phase": "splitting", "pct": 0}
{"event": "progress", "phase": "splitting", "pct": 100, "stems": ["..."]}
{"event": "progress", "phase": "slicing", "pct": 100, "bars": 32}
{"event": "progress", "phase": "curating", "pct": 100, "selected": 14}
{"event": "complete", "output_dir": "...", "manifest": "...", "bars": 14}
{"event": "error", "phase": "splitting", "message": "..."}
```

Pipe through `jq` for readable streaming, e.g.:

```bash
uv run --directory /Users/zak/zacharysbrown/stemforge stemforge forge "$AUDIO" \
  --backend demucs --strategy max-diversity --n-bars 14 \
  | jq -rc 'if .event == "progress" then "  [\(.phase)] \(.pct)%\(if .bars then " — \(.bars) bars" else "" end)\(if .selected then " — selected \(.selected)" else "" end)"
            elif .event == "complete" then "\n  ✓ Done. manifest: \(.manifest)"
            elif .event == "error"    then "\n  ✗ ERROR (\(.phase)): \(.message)"
            elif .event == "started"  then "  Forging \(.track) — backend=\(.backend), n_bars=\(.n_bars)"
            else .event end'
```

If `jq` is missing, just run the command without the pipe — the raw NDJSON is still readable.

## What forge produces

- **Curated WAVs** — `<output_dir>/<track>/curated/<stem>/bar_NN.wav`
- **Pipeline manifest** — `<output_dir>/<track>/curated/manifest.json` (this is the **legacy stems-grouped** schema with `track`/`stems`/`loops`, NOT yet the new `BatchManifest` from `specs/manifest-spec.md`).

When forge finishes, surface the **manifest path** in your reply — the user almost always wants to do something with it next (export to EP-133, load to Ableton, etc.).

> **Note (manifest gap):** Sidecar `.manifest_<hash>.json` and `.manifest.json` (per `specs/manifest-spec.md`) are **not yet emitted by forge directly**. Today they're written by the downstream `stemforge export -t ep133` path and consumed by `ppak-load-from-manifest`. If the user asks for sidecars off a fresh forge, suggest piping forge's output through export, or open it as a follow-up.

## Failure modes to watch for

- **Audio not found** — surface the path and the directory listing.
- **Backend not configured** — `lalal` / `musicai` need API keys; if forge errors with credentials, surface the error and suggest `--backend demucs` as the local fallback.
- **No drums stem** — curation defaults to drums; if the audio has no clear drum content, forge falls back to whatever stem comes first. Mention this in the report if relevant.
- **Empty curation** — if `selected: 0`, the source likely has too few bars for the requested `--n-bars`. Suggest a smaller `n_bars` or a different strategy.
- **`--curation` config not found** — error happens late (after splitting). If the user references a curation YAML, validate the path exists *before* the plan-then-confirm.

## Example end-to-end

User: *"forge ~/Music/setting_sun.wav with rhythm-taxonomy and 16 bars"*

You show the plan:

```
  Plan:
    audio:    ~/Music/setting_sun.wav
    backend:  demucs (model=default)
    strategy: rhythm-taxonomy
    n_bars:   16
    time_sig: 4/4
    output:   <repo>/processed/setting_sun/
```

User says *"go"*. You run:

```bash
uv run --directory /Users/zak/zacharysbrown/stemforge stemforge forge \
  ~/Music/setting_sun.wav \
  --backend demucs \
  --strategy rhythm-taxonomy \
  --n-bars 16 \
  | jq -rc '...'  # see streaming snippet above
```

Report success in one or two sentences:

> *Forged `setting_sun` — 16 bars curated. Manifest at `processed/setting_sun/curated/manifest.json`. Want me to /forge-launch Ableton and pull this in, or `stemforge export -t ep133` it?*
