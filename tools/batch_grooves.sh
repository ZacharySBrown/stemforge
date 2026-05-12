#!/usr/bin/env bash
# Sequential split + curate for everything in ./grooves.
# One track at a time — no parallelism. Skips tracks already complete.
# Logs to /tmp/batch_grooves.log.

set -u
cd /Users/zak/zacharysbrown/stemforge
LOG=/tmp/batch_grooves.log
: > "$LOG"   # truncate

slug_of() {
    # Mirror stemforge.cli.to_snake_case: strip leading numeric prefix,
    # non-alnum→_, collapse + strip + lowercase.
    python3 -c '
import re, sys
n = sys.argv[1]
n = re.sub(r"^\d+[\s_\-\.]*", "", n)
n = re.sub(r"[^a-zA-Z0-9]+", "_", n)
n = re.sub(r"_+", "_", n).strip("_")
print(n.lower())
' "$1"
}

count=0
for f in grooves/*.wav; do
    count=$((count + 1))
    stem=$(basename "$f" .wav)
    slug=$(slug_of "$stem")
    out_dir=/Users/zak/stemforge/processed/$slug
    cur_manifest=$out_dir/curated/manifest.json

    echo "==== [$count/14] $stem (slug=$slug) ====" | tee -a "$LOG"

    if [ -f "$cur_manifest" ]; then
        echo "  SKIP — curated/manifest.json already exists" | tee -a "$LOG"
        continue
    fi

    # If a partial dir exists (stems but no manifest), remove + redo.
    if [ -d "$out_dir" ] && [ ! -f "$out_dir/stems.json" ]; then
        echo "  partial dir detected, removing" | tee -a "$LOG"
        python3 -c "import shutil; shutil.rmtree('$out_dir', ignore_errors=True)"
    fi

    echo "  [1/2] split (arrangement)" | tee -a "$LOG"
    if ! uv run stemforge split "$f" --pipeline arrangement >> "$LOG" 2>&1; then
        echo "  SPLIT FAILED — see $LOG" | tee -a "$LOG"
        continue
    fi

    echo "  [2/2] curate" | tee -a "$LOG"
    if ! uv run python v0/src/stemforge_curate_bars.py \
            --stems-dir "$out_dir" \
            --curation pipelines/curation.yaml >> "$LOG" 2>&1; then
        echo "  CURATE FAILED — see $LOG" | tee -a "$LOG"
        continue
    fi

    echo "  DONE" | tee -a "$LOG"
done

echo "==== batch complete ====" | tee -a "$LOG"
