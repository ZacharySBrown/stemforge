#!/usr/bin/env bash
# Rerun the 3 grooves tracks that had bad BPM detection, with manual overrides.
# Sequential — same pattern as batch_grooves.sh.

set -u
cd /Users/zak/zacharysbrown/stemforge
LOG=/tmp/batch_grooves_overrides.log
: > "$LOG"

# Format: <basename-stem-of-wav>|<slug>|<extra-split-args>
TRACKS=(
    "05 - Braun-Blek-Blu|braun_blek_blu|--bpm 141.27"
    "07 - Tombo In 7_4|tombo_in_7_4|--bpm 138 --time-sig 7/4"
    "06 - Heather|heather|--bpm 132.24"
)

count=0
for row in "${TRACKS[@]}"; do
    count=$((count + 1))
    IFS='|' read -r stem slug extra_args <<< "$row"
    f="grooves/${stem}.wav"
    out_dir=/Users/zak/stemforge/processed/$slug

    echo "==== [$count/3] $stem (slug=$slug, override: $extra_args) ====" | tee -a "$LOG"

    echo "  [1/2] split (arrangement) $extra_args" | tee -a "$LOG"
    # Word-split is intentional here — extra_args contains pre-shaped CLI flags.
    # shellcheck disable=SC2086
    if ! uv run stemforge split "$f" --pipeline arrangement $extra_args >> "$LOG" 2>&1; then
        echo "  SPLIT FAILED — see $LOG" | tee -a "$LOG"
        continue
    fi

    echo "  [2/2] curate" | tee -a "$LOG"
    # Pass time-sig numerator through to curate-bars for tombo.
    curate_args=""
    if [[ "$slug" == "tombo_in_7_4" ]]; then
        curate_args="--time-sig 7"
    fi
    # shellcheck disable=SC2086
    if ! uv run python v0/src/stemforge_curate_bars.py \
            --stems-dir "$out_dir" \
            --curation pipelines/curation.yaml $curate_args >> "$LOG" 2>&1; then
        echo "  CURATE FAILED — see $LOG" | tee -a "$LOG"
        continue
    fi

    echo "  DONE" | tee -a "$LOG"
done

echo "==== overrides batch complete ====" | tee -a "$LOG"
