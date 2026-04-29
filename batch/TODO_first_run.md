# First Run: Download + Split

## What
Download all tracks from `first_run_tracklist.md` (~200 tracks) and run them through Modal batch stem splitting.

## Download
1. Get all tracks as audio files (.wav, .mp3, .flac — any format works)
2. Drop them into a single folder, e.g. `~/stemforge-input/`
3. Filenames don't need to be perfect — the script uses the filename stem as the output folder name

## Run
```bash
# Preview what will be processed:
modal run batch/run_batch.py --input-dir ~/stemforge-input --dry-run

# Run it (batches of 20, A10G GPU):
modal run batch/run_batch.py --input-dir ~/stemforge-input

# Output lands in ~/stemforge-input/stems/ by default
# Or specify: --output-dir ~/stemforge-output
```

## Tips
- You can run partial batches as you download — the script skips already-processed tracks
- Start with `--batch-size 5` to sanity-check the first few before sending all 200
- Stems output: `<output>/<track_name>/drums.wav`, `bass.wav`, `vocals.wav`, `other.wav`
- Combined `manifest.json` at the output root for downstream tooling

## Tracklist
See `first_run_tracklist.md` in this directory for the full list.
