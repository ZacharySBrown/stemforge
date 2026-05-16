---
name: forge-default
description: Run the StemForge `forge` pipeline end-to-end with the standard defaults, producing BOTH the auto-curation and the arrangement manifests in one pass. Use when the user asks to forge/process a track the normal way ("forge this track", "run the full forge on ~/Music/loop.wav", "forge it — curation and arrangement"). The everyday forge. Wraps `uv run stemforge forge`, plan-then-confirm, streams NDJSON, reports both manifests.
allowed-tools: Bash(uv run stemforge forge:*), Bash(uv run --directory:*), Bash(stemforge forge:*), Bash(ls:*), Bash(cat:*), Bash(jq:*), Read
---

# forge-default — the everyday forge (auto-curation + arrangement)

`stemforge forge` is the integrated pipeline: split → slice → **auto-curate**
→ prechop → **build arrangement**. One invocation produces *both* deliverables:

- **auto-curation** — `auto_curation_manifest.json` (the curated bar grid)
- **arrangement** — `arrangement_manifest.json` (real chunks for Live's
  arrangement view, built from `prechop_manifest.json`)

This skill runs it with the standard defaults so the user can just say
*"forge ~/Music/track.wav"* and get the full result.

## How to invoke

```bash
uv run --directory /Users/zak/zacharysbrown/stemforge stemforge forge <audio> [options]
```

(If `stemforge` is already on PATH from an editable install, the bare
`stemforge forge ...` works too — try it, fall back to `uv run --directory`.)

## Required from the user

- **Audio path** — a `.wav` (or any format `ensure_wav` converts) on disk.

## Defaults you supply

| Option | Default | Note |
|--------|---------|------|
| backend | `demucs` (local) | only backend |
| `--strategy` | `max-diversity` | curation strategy |
| `--n-bars` | `14` | curated bar count |
| `--time-sig` | `4/4` | used only without `--analysis` |
| `--output` | (repo `processed/`) | omit the flag |

Auto-curation **and** arrangement are produced unconditionally — no flag
needed; the current `forge` command always runs both. Override any default
only if the user says so (see forge-run's override table — same flags).

## Plan-then-confirm

Forge is **expensive** — Demucs runs locally, 30 s–several minutes. Show the
plan and ask *"run forge?"* unless the user already said *"go"* / *"do it"*.

```
  Plan: forge (auto-curation + arrangement)
    audio:    ~/Music/track.wav
    backend:  demucs (htdemucs)
    strategy: max-diversity
    n_bars:   14
    output:   <repo>/processed/track/
```

## Run + stream

`forge` emits newline-delimited JSON. Pipe through `jq` for readable progress:

```bash
uv run --directory /Users/zak/zacharysbrown/stemforge stemforge forge "$AUDIO" \
  --strategy max-diversity --n-bars 14 \
  | jq -rc 'if .event=="progress" then "  [\(.phase)] \(.pct)%"
            elif .event=="complete" then "  ✓ \(.manifest)"
            elif .event=="error" then "  ✗ ERROR (\(.phase)): \(.message)"
            else .event end'
```

If `jq` is missing, run without the pipe — raw NDJSON is still readable.

Phases to expect: `splitting` → `slicing` → `curating` → `prechop` →
`tempo`. The `prechop` phase is what gives the arrangement real chunks; if
it emits `prechop skipped …`, the arrangement falls back to empty — surface
that warning, it usually means the `arrangement` pipeline config is missing.

## Report — name BOTH manifests

After completion, list the output dir and surface both deliverables:

```bash
ls <repo>/processed/<track>/
```

Report, e.g.:

> Forged `track` — 14 bars curated. Auto-curation:
> `processed/track/auto_curation_manifest.json`; arrangement:
> `processed/track/arrangement_manifest.json`. Load it on the device, or
> `/ep133-load-curation` it once it's a curation + deck plan.

If `arrangement_manifest.json` is absent or empty, say so — prechop didn't
run; the curation half is still usable.

## Failure modes

- **Audio not found** — surface the path + a directory listing.
- **Demucs missing** — installed without the `native`/`all` extra. Forge
  prints an install hint; surface it and stop. Fix: `./scripts/setup.sh`.
- **`selected: 0`** — too few bars for `--n-bars`; suggest a smaller value.
- **`prechop skipped`** — arrangement pipeline config missing; the
  auto-curation still completed.
