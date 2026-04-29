---
name: forge-all
description: End-to-end forge: launch Ableton with the StemForge template AND run the forge pipeline on a track. Composes /forge-launch + /forge-run. Use when the user says "do the whole thing" / "launch and forge" / "open StemForge and forge X". Pick + commit (the in-Live device steps) are still manual today — see notes.
allowed-tools: Bash(open:*), Bash(pgrep:*), Bash(ls:*), Bash(uv run --directory*:*), Bash(uv run stemforge forge:*), Bash(stemforge forge:*), Bash(jq:*), Read
---

# forge-all — launch + forge in one go

Composed skill that runs `/forge-launch` and `/forge-run` back-to-back. Use when the user says:

- *"open StemForge and forge ~/Music/loop.wav"*
- *"do the whole thing on this track"*
- *"launch Ableton and forge it with rhythm-taxonomy"*
- *"forge end-to-end"*

## Sequence

1. **Launch Ableton with the StemForge template** — follow `/forge-launch` behavior. If Ableton is already running, just open the template (or skip if user said "no template"). Don't block on it — Live takes a few seconds to fully boot but forge can start in parallel.

2. **Run forge on the audio file** — follow `/forge-run` behavior. Plan-then-confirm (combined with the launch plan), backend/strategy/n_bars defaults the same.

3. **Report what's next** — the in-Live "pick patch & source" and "COMMIT" steps still have to be done by the user inside the device UI today (see "Manual steps" below).

## Combined plan-then-confirm

Show **one** plan covering both phases:

```
  Plan (forge-all):
    1. Launch Ableton with v0/build/StemForge.als   (skip if already running)
    2. Forge ~/Music/setting_sun.wav
        backend:  demucs (model=default)
        strategy: max-diversity
        n_bars:   14
        output:   <repo>/processed/setting_sun/

    Then (manual in Live): pick patch + source on the device, hit COMMIT.
```

Ask once: *"go?"* — if the user already said *"do the whole thing"* / *"--just do it"*, skip the prompt.

## Parallelism

Ableton boot is slow (5–10s). Forge with Demucs takes 30s–several minutes. **Start Ableton first**, but do **not** wait for it before kicking off forge — the forge process is CPU-heavy on the same machine and Ableton boot is mostly I/O, so they overlap cleanly. Use bash backgrounding:

```bash
# Launch Live in the background
( open "/Users/zak/zacharysbrown/stemforge/v0/build/StemForge.als" ) &

# Forge in the foreground (so the user sees streaming progress)
uv run --directory /Users/zak/zacharysbrown/stemforge stemforge forge "$AUDIO" \
  --backend "$BACKEND" --strategy "$STRATEGY" --n-bars "$N_BARS" \
  | jq -rc '...'  # see /forge-run for the streaming snippet
```

If the user wants forge to **wait** for Live (e.g. "boot Live first, then forge"), run sequentially.

## Manual steps still required

Once forge finishes and Live is up, the user has to:

1. **Drop the curated audio into the device's source slot** — drag the manifest's reported folder onto the StemForge device, OR use the device's source picker.
2. **Pick a patch** on the device UI.
3. **Hit COMMIT** to write the track templates / pad assignments.

These steps need an external control surface on the M4L device that **does not exist yet** — see [docs/feature-backlog.md](../../../docs/feature-backlog.md) item 2 for the gap. When the fswatcher lands, this skill will gain `/forge-pick` + `/forge-commit` chained at the end.

## Override etiquette

Inherits everything from `/forge-launch` and `/forge-run`. Common combinations:

| User says | Action |
|-----------|--------|
| "open StemForge and forge X" | template + audio |
| "launch and forge X with lalal" | template + `--backend lalal` |
| "no template, just forge X" | bare Live launch + forge |
| "forge X, don't open Live" | skip launch, just `/forge-run` |

## Failure modes

- **Either step fails independently.** If Ableton fails to launch, forge may still succeed (and vice versa). Report both outcomes — don't pretend the whole composition failed because one half did.
- **User changes mind mid-stream.** If forge errors and Ableton just opened, ask before quitting Live — they may want to do the rest by hand.

## Example end-to-end

User: *"do the whole thing on ~/Music/setting_sun.wav with rhythm-taxonomy and 16 bars"*

You show the combined plan, get a *"go"*, then:

```bash
TPL="/Users/zak/zacharysbrown/stemforge/v0/build/StemForge.als"
AUDIO="$HOME/Music/setting_sun.wav"

# Launch (background, non-blocking)
if pgrep -x "Live" >/dev/null; then
  open "$TPL"   # tell the running Live to open the template
else
  ( open "$TPL" ) &
fi

# Forge (foreground, streaming)
uv run --directory /Users/zak/zacharysbrown/stemforge stemforge forge "$AUDIO" \
  --backend demucs --strategy rhythm-taxonomy --n-bars 16 \
  | jq -rc 'if .event == "progress" then "  [\(.phase)] \(.pct)%"
            elif .event == "complete" then "\n  ✓ Done. manifest: \(.manifest)"
            elif .event == "error"    then "\n  ✗ ERROR (\(.phase)): \(.message)"
            else .event end'
```

Report:

> *Forged `setting_sun` (16 bars, manifest at `.../curated/manifest.json`) and opened `v0/build/StemForge.als` in Ableton. Inside the device: pick a patch, drop the curated folder on the source slot, hit COMMIT.*
