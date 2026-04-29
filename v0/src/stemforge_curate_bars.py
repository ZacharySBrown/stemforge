#!/usr/bin/env python3
"""stemforge_curate_bars.py — Bar-slice + diversity-curate stems from a split session.

Takes the output of `stemforge-native split` (4 stem WAVs in a directory)
and runs bar-level slicing + greedy diversity curation to produce N curated
bars per stem. Emits NDJSON events on stdout for M4L device integration.

Usage:
    uv run python v0/src/stemforge_curate_bars.py \
        --stems-dir ~/stemforge/processed/the_champ_30s \
        --n-bars 16 \
        --strategy max-diversity \
        --json-events

Input:  directory with drums.wav, bass.wav, vocals.wav, other.wav
Output: curated/ subdirectory with N bars per stem + updated stems.json
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

# Add repo root to path so we can import stemforge modules
REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from stemforge.slicer import detect_bpm_and_beats, slice_at_bars, group_bars_into_phrases
from stemforge.beat_align import find_best_downbeat_offset, apply_downbeat_offset, filter_ghost_beats
from stemforge.curator import curate, section_stratified_select
from stemforge.config import load_curation_config, CurationConfig
from stemforge.curation_schema import (
    load_curation_schema_config,
    build_curation_block,
    CurationSchemaConfig,
)
from stemforge.oneshot import extract_oneshots, extract_kicks_from_bass, select_diverse_oneshots, extract_drum_oneshots_via_larsnet
from stemforge.drum_classifier import classify_and_assign, arrange_drum_pads
from stemforge.layout import build_stems_layout, layout_to_manifest


STEM_NAMES = ["drums", "bass", "vocals", "other"]


def emit(event: dict) -> None:
    """Emit an NDJSON event to stdout."""
    print(json.dumps(event), flush=True)


def find_stems(stems_dir: Path) -> dict[str, Path]:
    """Find stem WAVs in the directory."""
    stems = {}
    for name in STEM_NAMES:
        p = stems_dir / f"{name}.wav"
        if p.exists():
            stems[name] = p
    return stems


def _reslice_with_padding(
    *,
    source_stem_path: Path,
    dst_path: Path,
    bar_idx: int,
    phrase_bars: int,
    bar_duration_sec: float,
    pad_bars_yaml: float,
) -> dict:
    """Re-slice a padded window from the source stem WAV to dst_path.

    Architectural rationale: curation/analysis runs on exact-bar WAVs so the
    rhythm/diversity/onset signals aren't polluted by neighbouring-bar
    content. Padding is purely for the user's trim adjustment in Ableton —
    applied AFTER selection, only to the chosen bars, by reading the padded
    region straight from the source stem.

    Bar index → time mapping uses uniform bar_duration_sec:
        raw_start_in_stem = (bar_idx - 1) * bar_duration_sec
    Bar filenames are already 1-indexed positions in the bar grid (see
    stemforge.slicer._write_bar_slices), so this holds even when silent bars
    leave gaps in the bar-file sequence.

    Returns dict with resolved values the caller passes to build_curation_block:
        pad_bars_applied   — symmetric min of both sides after edge clamping
        raw_start_sec      — where the exact-bar window begins inside dst file
        bar_duration_sec   — echoed for convenience
        padded_duration    — dst file duration (actual, post-clamp)
    """
    info = sf.info(str(source_stem_path))
    sr = info.samplerate
    stem_duration = float(info.duration)

    raw_start_in_stem = max(0.0, (bar_idx - 1) * bar_duration_sec)
    raw_end_in_stem = min(stem_duration, raw_start_in_stem + phrase_bars * bar_duration_sec)

    pad_sec = float(pad_bars_yaml) * bar_duration_sec

    # Clamp padding at stem edges
    pad_start_actual_sec = min(pad_sec, raw_start_in_stem)
    pad_end_actual_sec = min(pad_sec, max(0.0, stem_duration - raw_end_in_stem))

    # Symmetric pad: use the smaller of the two so the emitted pad_bars is
    # valid on BOTH sides. Asymmetric clamps still trim the file correctly,
    # but we expose the symmetric-safe value in the manifest.
    pad_actual_sec = min(pad_start_actual_sec, pad_end_actual_sec)
    pad_bars_applied = pad_actual_sec / bar_duration_sec if bar_duration_sec > 0 else 0.0

    window_start_sec = raw_start_in_stem - pad_start_actual_sec
    window_end_sec = raw_end_in_stem + pad_end_actual_sec

    # Read the source region by frames
    start_frame = max(0, int(round(window_start_sec * sr)))
    stop_frame = min(info.frames, int(round(window_end_sec * sr)))
    if stop_frame <= start_frame:
        raise ValueError(
            f"Empty slice window for bar {bar_idx} in {source_stem_path.name}"
        )

    data, _ = sf.read(
        str(source_stem_path),
        start=start_frame,
        stop=stop_frame,
        always_2d=True,
    )

    # Match v0 bar WAVs: PCM_24
    dst_path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(dst_path), data, sr, subtype="PCM_24")

    # raw_start_sec inside the padded file is where we inserted the exact bar
    raw_start_in_dst = pad_start_actual_sec

    padded_duration = (stop_frame - start_frame) / float(sr)

    return {
        "pad_bars_applied": pad_bars_applied,
        "raw_start_sec": raw_start_in_dst,
        "bar_duration_sec": bar_duration_sec,
        "padded_duration": padded_duration,
    }


def _detect_reference_onsets(
    reference_wav: Path,
    target_sr: int = 22050,
) -> np.ndarray:
    """Detect onset times (seconds) on the reference stem.

    Returns sorted array of onset times in seconds. Used as the "true beat
    grid" for snapping every other stem's slices into time-alignment with
    the dominant rhythmic content. For tracks with a clean periodic
    reference (e.g. steady bass on quarter notes), this fixes the problem
    where beat-this's detected beats sit a few tens of ms off the real
    musical downbeats.
    """
    import librosa
    y, sr = librosa.load(str(reference_wav), sr=target_sr, mono=True)
    onset_frames = librosa.onset.onset_detect(
        y=y, sr=sr, units="frames", backtrack=True,
    )
    return librosa.frames_to_time(onset_frames, sr=sr)


def _snap_to_nearest_onset(
    t_sec: float,
    onsets_sec: np.ndarray,
    max_offset_sec: float = 0.150,
) -> float:
    """Return the onset time closest to t_sec within ±max_offset_sec.

    Falls back to t_sec unchanged if no onset is within the window — leaves
    that slice un-shifted rather than yanking it across a missing-bass
    section.
    """
    if onsets_sec is None or len(onsets_sec) == 0:
        return t_sec
    diffs = np.abs(onsets_sec - t_sec)
    idx = int(np.argmin(diffs))
    if diffs[idx] <= max_offset_sec:
        return float(onsets_sec[idx])
    return t_sec


def _reextract_slice(
    source_stem_path: Path,
    dst_path: Path,
    start_sec: float,
    duration_sec: float,
) -> bool:
    """Read [start_sec, start_sec + duration_sec] from source_stem_path,
    write to dst_path. Returns False on failure.
    """
    try:
        with sf.SoundFile(str(source_stem_path)) as f:
            sr = f.samplerate
            start_frame = max(0, int(round(start_sec * sr)))
            n_frames = int(round(duration_sec * sr))
            f.seek(start_frame)
            data = f.read(n_frames, always_2d=True)
        if data.shape[0] < n_frames:
            pad = np.zeros((n_frames - data.shape[0], data.shape[1]),
                           dtype=data.dtype)
            data = np.concatenate([data, pad], axis=0)
        sf.write(str(dst_path), data, sr, subtype="PCM_24")
        return True
    except Exception:
        return False


def _trim_wav_to_first_onset(wav_path: Path, threshold_ms: float = 30.0) -> bool:
    """Rotate a WAV so its first detected onset sits at sample 0; pad the
    tail with silence to preserve total duration.

    For EP-133 key/performance mode and similar: pressing the trigger should
    fire the rhythm immediately with zero leading air. Detect first onset
    via librosa.onset_detect; if the leading silence exceeds threshold_ms,
    trim it and zero-pad the tail. Returns True if the file was modified.
    """
    import librosa
    info = sf.info(str(wav_path))
    target_sr = info.samplerate
    y_mono, _ = librosa.load(str(wav_path), sr=target_sr, mono=True)
    onset_frames = librosa.onset.onset_detect(
        y=y_mono, sr=target_sr, units="samples", backtrack=True,
    )
    if len(onset_frames) == 0:
        return False
    first_sample = int(onset_frames[0])
    if first_sample / target_sr * 1000.0 < threshold_ms:
        return False  # leading silence below threshold — leave alone

    data, sr = sf.read(str(wav_path), always_2d=True)
    if first_sample >= data.shape[0]:
        return False  # onset past end — pathological, skip
    trimmed = data[first_sample:]
    pad = np.zeros((first_sample, data.shape[1]), dtype=data.dtype)
    out = np.concatenate([trimmed, pad], axis=0)
    sf.write(str(wav_path), out, sr, subtype="PCM_24")
    return True


def _normalize_wav_duration(wav_path: Path, target_sec: float) -> None:
    """Trim or zero-pad a WAV in place to exactly target_sec long.

    The slicer cuts at beat-this's detected beat positions, which aren't
    perfectly periodic — bar slices end up varying by ±5%. Ableton then
    stretches each clip by a different factor to fit session BPM, making
    every loop sound subtly different. Normalizing to exact bar duration
    removes the stretch so every clip plays at session BPM natively.
    Tails of percussive bars are low-energy so trim/pad at the end is
    typically inaudible.
    """
    info = sf.info(str(wav_path))
    target_frames = int(round(target_sec * info.samplerate))
    if abs(target_frames - info.frames) <= 2:
        return  # already within sub-sample precision
    data, sr = sf.read(str(wav_path), always_2d=True)
    if data.shape[0] > target_frames:
        data = data[:target_frames]
    elif data.shape[0] < target_frames:
        pad = np.zeros((target_frames - data.shape[0], data.shape[1]),
                       dtype=data.dtype)
        data = np.concatenate([data, pad], axis=0)
    sf.write(str(wav_path), data, sr, subtype="PCM_24")


def _parse_bar_index(filename: str) -> int | None:
    """Extract bar grid index N from `{stem}_bar_NNN.wav`."""
    m = re.search(r"_bar_(\d+)\.wav$", filename)
    return int(m.group(1)) if m else None


def _parse_phrase_index(filename: str) -> int | None:
    """Extract phrase index N from `{stem}_phrase_NNN.wav`."""
    m = re.search(r"_phrase_(\d+)\.wav$", filename)
    return int(m.group(1)) if m else None


def _first_bar_idx_for_phrase(
    bar_dir: Path, stem_name: str, phrase_bars: int, phrase_idx: int,
) -> int | None:
    """Resolve phrase idx (1-based) → bar-grid idx of its first underlying bar.

    Mirrors group_bars_into_phrases grouping: phrase pi+1 covers
    bar_files[pi*phrase_bars : (pi+1)*phrase_bars] in sorted order.
    Returns None if the phrase can't be resolved.
    """
    bar_files = sorted(bar_dir.glob(f"{stem_name}_bar_*.wav"))
    pi = phrase_idx - 1
    start = pi * phrase_bars
    if start >= len(bar_files):
        return None
    return _parse_bar_index(bar_files[start].name)


def run(
    stems_dir: Path,
    n_bars: int = 16,
    strategy: str = "max-diversity",
    time_sig: int = 4,
    json_events: bool = True,
    curation_config: CurationConfig | None = None,
    pipeline: Path | None = None,
    schema_config: CurationSchemaConfig | None = None,
) -> Path:
    """Run bar slicing + curation on stems in stems_dir.

    When curation_config is provided, per-stem phrase_bars and distance_weights
    are used. Otherwise falls back to single-bar curation.

    Returns path to the curated manifest.
    """
    stems_dir = Path(stems_dir)
    stems = find_stems(stems_dir)
    if curation_config is None:
        curation_config = CurationConfig()
    if schema_config is None:
        schema_config = CurationSchemaConfig()

    layout_mode = curation_config.layout.mode
    is_loops_only = layout_mode == "loops-only"
    is_production = layout_mode == "production"

    if is_loops_only and json_events:
        emit({"event": "progress", "phase": "config", "pct": 0,
              "message": "loops-only mode: 16 bar loops per stem, no one-shots"})
    if is_production and json_events:
        emit({"event": "progress", "phase": "config", "pct": 0,
              "message": "production mode: 16 loops per stem + drum one-shots"})

    if not stems:
        if json_events:
            emit({"event": "error", "phase": "curate", "message": f"No stems found in {stems_dir}"})
        raise FileNotFoundError(f"No stems found in {stems_dir}")

    if json_events:
        emit({
            "event": "progress",
            "phase": "slicing",
            "pct": 0,
            "message": f"Slicing {len(stems)} stems into bars (time sig: {time_sig}/4)",
        })

    # Step 1: Detect BPM and beats.
    # beat-this (neural downbeat detection) needs the FULL MIX for harmonic
    # context — it hallucinates half/double time on isolated drum stems.
    # Librosa beat_track() works better on drums stems (onset-based).
    bpm_source = stems.get("drums", next(iter(stems.values())))

    # Look for original source audio for beat-this
    source_audio = None
    source_manifest = stems_dir / "stems.json"
    if source_manifest.exists():
        try:
            src_data = json.loads(source_manifest.read_text())
            src_path = Path(src_data.get("source_file", ""))
            if src_path.exists():
                source_audio = src_path
        except (json.JSONDecodeError, KeyError):
            pass

    # Try neural downbeat detection on full mix first.
    # beat-this needs harmonic context — always prefer full mix over drums stem.
    # Only keep neural results if bar CV is better than librosa fallback.
    downbeat_times = None

    # Always get librosa beats as baseline (fast, reliable on drums)
    bpm, beat_times = detect_bpm_and_beats(bpm_source)

    try:
        from stemforge.beat_detect import detect_beats_and_downbeats
        bt_source = source_audio or bpm_source
        bt_bpm, bt_beats, bt_downbeats = detect_beats_and_downbeats(bt_source)

        if len(bt_downbeats) > 2:
            # Compare bar CV: beat-this downbeats vs librosa stride
            lib_bar_durs = np.diff(beat_times[::time_sig])
            lib_cv = lib_bar_durs[:-1].std() / lib_bar_durs[:-1].mean() if len(lib_bar_durs) > 2 else 1
            bt_bar_durs = np.diff(bt_downbeats)
            bt_cv = bt_bar_durs[:-1].std() / bt_bar_durs[:-1].mean() if len(bt_bar_durs) > 2 else 1

            if bt_cv < lib_cv:
                bpm = bt_bpm
                beat_times = bt_beats
                downbeat_times = bt_downbeats
                if json_events:
                    src_label = "full mix" if source_audio else "drums stem"
                    emit({"event": "progress", "phase": "alignment", "pct": 2,
                          "message": f"beat-this ({src_label}): {len(downbeat_times)} downbeats, CV {bt_cv*100:.1f}% (librosa was {lib_cv*100:.1f}%)"})
            elif json_events:
                emit({"event": "progress", "phase": "alignment", "pct": 2,
                      "message": f"beat-this CV {bt_cv*100:.1f}% > librosa {lib_cv*100:.1f}%, using librosa"})
    except ImportError:
        pass

    if downbeat_times is None:
        # Experimental: beat grid corrections (only needed without neural downbeats).
        # Apply ghost filtering + downbeat offset, but only keep if bar CV improves.
        # Some tracks (syncopated, odd-time) get worse with corrections — revert those.
        def _bar_cv(beats, ts):
            bars = np.diff(beats[::ts])
            return bars[:-1].std() / bars[:-1].mean() if len(bars) > 2 else 0

        original_cv = _bar_cv(beat_times, time_sig)
        corrected = beat_times.copy()

        # Step 1a: Ghost beat filtering
        corrected, ghosts_removed = filter_ghost_beats(corrected)

        # Step 1b: Downbeat offset
        downbeat_offset = find_best_downbeat_offset(bpm_source, corrected, time_sig)
        if downbeat_offset > 0:
            corrected = apply_downbeat_offset(corrected, downbeat_offset)

        # Only keep corrections if they improved bar regularity
        corrected_cv = _bar_cv(corrected, time_sig)
        if corrected_cv < original_cv and (ghosts_removed > 0 or downbeat_offset > 0):
            beat_times = corrected
            corrections = []
            if ghosts_removed > 0:
                corrections.append(f"removed {ghosts_removed} ghost beats")
            if downbeat_offset > 0:
                corrections.append(f"shifted {downbeat_offset} beat(s)")
            if json_events:
                emit({"event": "progress", "phase": "alignment", "pct": 2,
                      "message": f"beat grid corrected: {', '.join(corrections)} (CV {original_cv*100:.1f}%→{corrected_cv*100:.1f}%)"})

    if json_events:
        emit({"event": "bpm", "bpm": bpm, "beat_count": len(beat_times)})

    # Step 2: Slice each stem into bars
    # Clean existing bar dirs first to avoid stale files from previous runs
    stem_bar_dirs: dict[str, Path] = {}
    for stem_name in stems:
        bar_dir = stems_dir / f"{stem_name}_bars"
        if bar_dir.exists():
            shutil.rmtree(bar_dir)

    for i, (stem_name, stem_path) in enumerate(stems.items()):
        bar_paths = slice_at_bars(
            stem_path=stem_path,
            output_dir=stems_dir,
            stem_name=stem_name,
            time_sig_numerator=time_sig,
            beat_times=beat_times,
            bar_start_times=downbeat_times,
        )
        # slice_at_bars creates {stem_name}_bars/ inside output_dir
        bar_dir = stems_dir / f"{stem_name}_bars"
        stem_bar_dirs[stem_name] = bar_dir

        pct = int(((i + 1) / len(stems)) * 50)  # slicing = 0-50%
        if json_events:
            emit({
                "event": "progress",
                "phase": "slicing",
                "pct": pct,
                "message": f"{stem_name}: {len(bar_paths)} bars",
            })

    # Step 3: Per-stem phrase grouping + curation
    # Each stem gets its own phrase_bars and strategy from the config.
    # When all stems use phrase_bars=1 and the same strategy, we mirror
    # bar indices (v0 behavior). Otherwise, each stem is curated independently.
    curated_root = stems_dir / "curated"
    if curated_root.exists():
        shutil.rmtree(curated_root)
    curated_root.mkdir()

    # Check if all stems share the same phrase_bars — enables mirroring
    stem_configs = {s: curation_config.for_stem(s) for s in stems}

    # In loops-only and production modes, override loop/oneshot counts.
    # Use dataclasses.replace so we keep all OTHER per-stem yaml settings
    # (alts_per_section, max_sections, content_density_min, bottom_mode, etc.)
    # — earlier code rebuilt from scratch and silently dropped any field
    # not explicitly forwarded.
    if is_loops_only or is_production:
        import dataclasses as _dc
        for s in stem_configs:
            sc = stem_configs[s]
            os_count = 8 if (is_production and s == "drums") else 0
            os_mode = "classify" if s == "drums" else "diverse"
            stem_configs[s] = _dc.replace(
                sc,
                loop_count=16,
                oneshot_count=os_count,
                oneshot_mode=os_mode,
                chromatic=False,
                midi_extract=False,
            )
    phrase_bars_set = {sc.phrase_bars for sc in stem_configs.values()}
    # In loops-only mode, always use per-stem curation — mirroring from drums
    # causes silent bars in non-drum stems (e.g. vocal bars from instrumental sections).
    all_same_phrase = (
        len(phrase_bars_set) == 1
        and next(iter(phrase_bars_set)) == 1
        and not is_loops_only
    )

    curated_manifest = {
        "version": 2,
        "track": stems_dir.name,
        "source_dir": str(stems_dir),
        "strategy": strategy,
        "n_bars": n_bars,
        "bpm": bpm,
        "beat_count": len(beat_times),
        "time_signature_numerator": time_sig,
        "layout_mode": curation_config.layout.mode,
        "stems": {},
    }

    if all_same_phrase:
        # ── Mirror mode (v0 behavior): curate from drums, mirror indices ──
        per_stem_indices: dict[str, set[int]] = {}
        for stem_name, bar_dir in stem_bar_dirs.items():
            indices = set()
            for bf in bar_dir.glob(f"{stem_name}_bar_*.wav"):
                m = re.search(r"_bar_(\d+)\.wav$", bf.name)
                if m:
                    indices.add(int(m.group(1)))
            per_stem_indices[stem_name] = indices

        common_indices = set.intersection(*per_stem_indices.values()) if per_stem_indices else set()
        curation_source = "drums" if "drums" in stem_bar_dirs else next(iter(stem_bar_dirs))
        curation_bar_dir = stem_bar_dirs[curation_source]
        sc = stem_configs[curation_source]

        # Build temp pool with only common-range bars
        import tempfile
        curation_pool = Path(tempfile.mkdtemp(prefix="sf_curate_"))
        common_bar_paths = []
        for bf in sorted(curation_bar_dir.glob(f"{curation_source}_bar_*.wav")):
            m = re.search(r"_bar_(\d+)\.wav$", bf.name)
            if m and int(m.group(1)) in common_indices:
                dst = curation_pool / bf.name
                shutil.copy2(bf, dst)
                common_bar_paths.append(dst)

        if json_events:
            emit({
                "event": "progress",
                "phase": "curating",
                "pct": 55,
                "message": f"Selecting {n_bars} from {curation_source} ({len(common_bar_paths)} mirrorable)",
            })

        selected_paths = curate(
            curation_pool, n_bars=n_bars, strategy=sc.strategy,
            rms_floor=sc.rms_floor, crest_min=sc.crest_min,
            content_density_min=sc.content_density_min,
            distance_weights=sc.distance_weights,
        )
        shutil.rmtree(curation_pool, ignore_errors=True)

        if not selected_paths:
            if json_events:
                emit({"event": "error", "phase": "curate", "message": "Curation returned no bars"})
            raise RuntimeError("Curation returned no bars")

        selected_indices = []
        for p in selected_paths:
            m = re.search(r"_bar_(\d+)\.wav$", p.name)
            if m:
                selected_indices.append(int(m.group(1)))

        if json_events:
            emit({
                "event": "progress", "phase": "curating", "pct": 70,
                "message": f"Selected {len(selected_indices)} bars, mirroring across stems",
            })

        # Mirror across all stems — v1: padded re-slice from source stem
        # per selected bar. Analysis ran on exact-bar WAVs; padding is
        # applied here only to the chosen bars so Ableton gets pre-roll
        # context for user trim without polluting curation signals.
        bar_duration_sec = (60.0 / bpm) * time_sig if bpm > 0 else 0.0

        for stem_name, bar_dir in stem_bar_dirs.items():
            stem_curated_dir = curated_root / stem_name
            stem_curated_dir.mkdir()

            bar_files = sorted(bar_dir.glob(f"{stem_name}_bar_*.wav"))
            bar_index = {}
            for bf in bar_files:
                idx = _parse_bar_index(bf.name)
                if idx is not None:
                    bar_index[idx] = bf

            stem_schema = schema_config.for_stem(stem_name)
            source_stem_path = stems.get(stem_name)

            stem_bars = []
            for position, bar_idx in enumerate(selected_indices):
                src = bar_index.get(bar_idx)
                if not (src and src.exists()):
                    continue
                dst = stem_curated_dir / f"bar_{position + 1:03d}.wav"

                pad_bars_yaml = float(stem_schema.pad_bars or 0.0)
                use_padded = (
                    pad_bars_yaml > 0.0
                    and source_stem_path is not None
                    and source_stem_path.exists()
                    and bar_duration_sec > 0
                )

                if use_padded:
                    reslice = _reslice_with_padding(
                        source_stem_path=source_stem_path,
                        dst_path=dst,
                        bar_idx=bar_idx,
                        phrase_bars=1,
                        bar_duration_sec=bar_duration_sec,
                        pad_bars_yaml=pad_bars_yaml,
                    )
                    entry = {
                        "position": position + 1,
                        "source_bar_index": bar_idx,
                        "phrase_bars": 1,
                        "file": str(dst),
                    }
                    entry.update(build_curation_block(
                        dst, phrase_bars=1,
                        time_sig_numerator=time_sig,
                        stem_schema=stem_schema,
                        bpm=bpm,
                        pad_bars_applied=reslice["pad_bars_applied"],
                        bar_duration_sec=bar_duration_sec,
                        ts_num=time_sig,
                        raw_start_sec=reslice["raw_start_sec"],
                    ))
                else:
                    # Fallback: copy exact-bar WAV (v0 behaviour)
                    shutil.copy2(src, dst)
                    entry = {
                        "position": position + 1,
                        "source_bar_index": bar_idx,
                        "phrase_bars": 1,
                        "file": str(dst),
                    }
                    entry.update(build_curation_block(
                        dst, phrase_bars=1,
                        time_sig_numerator=time_sig,
                        stem_schema=stem_schema,
                        bpm=bpm,
                    ))
                stem_bars.append(entry)
            curated_manifest["stems"][stem_name] = stem_bars

    else:
        # ── Reference-stem onset grid (alignment) ──────────────────────────
        # When `alignment.reference_stem` is set in the curation yaml (or
        # defaults to "bass" if available), detect onsets on that stem ONCE
        # and re-extract every selected bar from each source stem at the
        # nearest onset position. Fixes the case where beat-this's detected
        # downbeats are systematically off by tens of ms — slices then play
        # off-grid with the metronome regardless of duration normalization.
        # Default reference: bass (typically the steadiest periodic stem
        # for electronic / hip-hop / rock material). Future: opt-in via
        # yaml `alignment.reference_stem`.
        ref_stem_name = "bass" if "bass" in stems else None
        ref_onsets = None
        if ref_stem_name and ref_stem_name in stems:
            ref_path = stems[ref_stem_name]
            try:
                ref_onsets = _detect_reference_onsets(ref_path)
                if json_events:
                    emit({"event": "progress", "phase": "curating", "pct": 88,
                          "message": f"alignment: detected {len(ref_onsets)} onsets on {ref_stem_name} stem"})
            except Exception as e:
                if json_events:
                    emit({"event": "progress", "phase": "curating", "pct": 88,
                          "message": f"alignment: ref-onset detection failed: {e}"})
                ref_onsets = None

        # ── Per-stem mode: each stem curated independently with its own phrase_bars ──
        for si, (stem_name, bar_dir) in enumerate(stem_bar_dirs.items()):
            sc = stem_configs[stem_name]
            stem_curated_dir = curated_root / stem_name
            stem_curated_dir.mkdir()

            # Group bars into phrases if phrase_bars > 1
            if sc.phrase_bars > 1:
                phrase_dir = stems_dir / f"{stem_name}_phrases"
                if phrase_dir.exists():
                    shutil.rmtree(phrase_dir)
                phrase_paths = group_bars_into_phrases(
                    bar_dir, stem_name, sc.phrase_bars, output_dir=stems_dir,
                )
                curation_dir = phrase_dir
                file_pattern = f"{stem_name}_phrase_*.wav"
                item_label = f"{sc.phrase_bars}-bar phrase"
            else:
                curation_dir = bar_dir
                file_pattern = f"{stem_name}_bar_*.wav"
                item_label = "bar"

            n_available = len(list(curation_dir.glob(file_pattern)))

            if json_events:
                emit({
                    "event": "progress",
                    "phase": "curating",
                    "pct": 55 + int((si / len(stem_bar_dirs)) * 35),
                    "message": f"{stem_name}: selecting {sc.loop_count} {item_label}s from {n_available}",
                })

            # Detect song structure if any selection path needs it: melodic
            # mode (section-stratified) OR section-main-alt strategy.
            song_structure = None
            needs_structure = (
                (sc.bottom_mode == "melodic" and sc.midi_extract)
                or sc.strategy == "section-main-alt"
            )
            if needs_structure:
                try:
                    from stemforge.segmenter import detect_song_structure
                    song_structure = detect_song_structure(
                        stems.get(stem_name, next(iter(stems.values()))),
                        beat_times=beat_times, bpm=bpm, time_sig=time_sig,
                    )
                    if json_events and song_structure.boundaries_bars:
                        emit({
                            "event": "progress",
                            "phase": "curating",
                            "pct": 55 + int((si / len(stem_bar_dirs)) * 35),
                            "message": f"{stem_name}: form={song_structure.form}, selecting across sections",
                        })
                except Exception:
                    pass  # fall back to regular curation

            if (song_structure and song_structure.boundaries_bars
                and sc.bottom_mode == "melodic" and sc.midi_extract):
                selected = section_stratified_select(
                    curation_dir,
                    n_bars=sc.loop_count,
                    song_structure=song_structure,
                    rms_floor=sc.rms_floor,
                    crest_min=sc.crest_min,
                    content_density_min=sc.content_density_min,
                    distance_weights=sc.distance_weights,
                )
            else:
                selected = curate(
                    curation_dir,
                    n_bars=sc.loop_count,
                    strategy=sc.strategy,
                    rms_floor=sc.rms_floor,
                    crest_min=sc.crest_min,
                    content_density_min=sc.content_density_min,
                    distance_weights=sc.distance_weights,
                    song_structure=song_structure,
                    alts_per_section=int(getattr(sc, "alts_per_section", 2) or 2),
                    max_sections=int(getattr(sc, "max_sections", 4) or 4),
                    phrase_bars=int(sc.phrase_bars or 1),
                )

            # Drop selections whose duration deviates wildly from the expected
            # phrase length. The slicer dumps post-last-beat audio into the
            # final bar file, leaving an outlier that can be 10-20× longer
            # than the rest. Diversity selectors love that outlier; we don't.
            _bar_dur_for_filter = (60.0 / bpm) * time_sig if bpm > 0 else 0.0
            expected_dur = _bar_dur_for_filter * float(sc.phrase_bars or 1)
            if expected_dur > 0:
                kept = []
                for s in selected:
                    try:
                        with sf.SoundFile(str(s)) as f:
                            d = f.frames / float(f.samplerate)
                    except Exception:
                        continue
                    if 0.5 * expected_dur <= d <= 1.5 * expected_dur:
                        kept.append(s)
                    elif json_events:
                        emit({
                            "event": "progress", "phase": "curating", "pct": 90,
                            "message": f"{stem_name}: dropped {s.name} "
                                       f"(duration {d:.2f}s vs expected {expected_dur:.2f}s)"
                        })
                selected = kept

            stem_bars = []
            stem_schema = schema_config.for_stem(stem_name)
            source_stem_path = stems.get(stem_name)
            bar_duration_sec = (60.0 / bpm) * time_sig if bpm > 0 else 0.0
            pad_bars_yaml = float(stem_schema.pad_bars or 0.0)

            for position, src in enumerate(selected):
                dst = stem_curated_dir / f"bar_{position + 1:03d}.wav"

                # Resolve source bar-grid index from the selected filename.
                # - exact-bar file:   {stem}_bar_N.wav        → bar idx = N
                # - phrase file:      {stem}_phrase_P.wav     → bar idx = first
                #                     underlying bar in group_bars_into_phrases
                #                     ordering.
                first_bar_idx = None
                phrase_idx = _parse_phrase_index(src.name)
                if phrase_idx is not None:
                    first_bar_idx = _first_bar_idx_for_phrase(
                        bar_dir, stem_name, sc.phrase_bars, phrase_idx,
                    )
                else:
                    first_bar_idx = _parse_bar_index(src.name)

                use_padded = (
                    pad_bars_yaml > 0.0
                    and source_stem_path is not None
                    and source_stem_path.exists()
                    and bar_duration_sec > 0
                    and first_bar_idx is not None
                )

                if use_padded:
                    reslice = _reslice_with_padding(
                        source_stem_path=source_stem_path,
                        dst_path=dst,
                        bar_idx=first_bar_idx,
                        phrase_bars=int(sc.phrase_bars),
                        bar_duration_sec=bar_duration_sec,
                        pad_bars_yaml=pad_bars_yaml,
                    )
                    entry = {
                        "position": position + 1,
                        "source_bar_index": first_bar_idx,
                        "phrase_bars": sc.phrase_bars,
                        "file": str(dst),
                    }
                    entry.update(build_curation_block(
                        dst, phrase_bars=sc.phrase_bars,
                        time_sig_numerator=time_sig,
                        stem_schema=stem_schema,
                        bpm=bpm,
                        pad_bars_applied=reslice["pad_bars_applied"],
                        bar_duration_sec=bar_duration_sec,
                        ts_num=time_sig,
                        raw_start_sec=reslice["raw_start_sec"],
                    ))
                else:
                    target_dur = _bar_dur_for_filter * float(sc.phrase_bars or 1)
                    used_alignment = False

                    # Reference-stem alignment: if we have onsets and a
                    # source stem, re-extract this bar from the source at
                    # the snapped onset position rather than copying the
                    # already-cut slice. Pulls the slice's start onto a
                    # real musical onset so loops play in time with the
                    # session metronome.
                    if (
                        ref_onsets is not None
                        and source_stem_path is not None
                        and source_stem_path.exists()
                        and first_bar_idx is not None
                        and bar_duration_sec > 0
                        and target_dur > 0
                    ):
                        nominal_start = float(first_bar_idx - 1) * bar_duration_sec
                        snapped_start = _snap_to_nearest_onset(
                            nominal_start, ref_onsets, max_offset_sec=0.150,
                        )
                        if _reextract_slice(
                            source_stem_path, dst, snapped_start, target_dur,
                        ):
                            used_alignment = True

                    if not used_alignment:
                        shutil.copy2(src, dst)

                    # Normalize the curated copy to exactly phrase_bars long
                    # so every clip's natural BPM == session BPM and Ableton
                    # doesn't stretch unevenly between bars. Re-extract above
                    # already produces an exact-duration slice, so this is a
                    # no-op in that path; still belt-and-suspenders for the
                    # shutil.copy2 fallback.
                    if target_dur > 0:
                        try:
                            _normalize_wav_duration(dst, target_dur)
                        except Exception as e:
                            if json_events:
                                emit({"event": "progress", "phase": "curating", "pct": 92,
                                      "message": f"normalize {dst.name} failed: {e}"})

                    # Optional: trim to first onset for performance/key mode
                    # (rotate audio so first transient sits at sample 0; pad
                    # tail with silence to preserve duration).
                    if getattr(sc, "trim_to_first_onset", False):
                        try:
                            _trim_wav_to_first_onset(
                                dst,
                                threshold_ms=float(getattr(sc, "trim_onset_threshold_ms", 30.0)),
                            )
                        except Exception as e:
                            if json_events:
                                emit({"event": "progress", "phase": "curating", "pct": 93,
                                      "message": f"trim-to-onset {dst.name} failed: {e}"})

                    entry = {
                        "position": position + 1,
                        "source_bar_index": first_bar_idx,
                        "phrase_bars": sc.phrase_bars,
                        "file": str(dst),
                    }
                    entry.update(build_curation_block(
                        dst, phrase_bars=sc.phrase_bars,
                        time_sig_numerator=time_sig,
                        stem_schema=stem_schema,
                        bpm=bpm,
                    ))
                stem_bars.append(entry)

            curated_manifest["stems"][stem_name] = stem_bars

    # Step 5: Extract one-shots per stem (if configured)
    # loops-only: skip all one-shots
    # production: only extract drum one-shots
    if is_loops_only and json_events:
        emit({"event": "progress", "phase": "oneshots", "pct": 80,
              "message": "loops-only mode: skipping one-shot extraction"})

    for stem_name, stem_path in stems.items():
        if is_loops_only:
            continue
        if is_production and stem_name != "drums":
            continue  # production mode: only drum one-shots
        sc = stem_configs[stem_name]
        if sc.oneshot_count <= 0:
            continue

        if json_events:
            emit({
                "event": "progress",
                "phase": "oneshots",
                "pct": 80,
                "message": f"{stem_name}: extracting one-shots",
            })

        # Extract one-shots — try LarsNet first for drums (clean sub-stem separation)
        os_profiles = []
        if stem_name == "drums":
            from stemforge.drum_separator import is_available as _larsnet_ok
            if _larsnet_ok():
                if json_events:
                    emit({"event": "progress", "phase": "oneshots", "pct": 81,
                          "message": "drums: using LarsNet sub-stem separation (kick/snare/hihat/toms/cymbals)"})
                os_profiles = extract_drum_oneshots_via_larsnet(
                    stem_path, curated_root, config=sc)

        if not os_profiles:
            # Fallback: spectral heuristic extraction
            os_profiles = extract_oneshots(stem_path, curated_root, stem_name, config=sc)

            # For drums: also extract kicks from bass stem (htdemucs bleed)
            if stem_name == "drums" and "bass" in stems:
                kicks = extract_kicks_from_bass(stems["bass"], curated_root, config=sc)
                os_profiles.extend(kicks)

            # Classify drum hits via spectral heuristics
            if stem_name == "drums" and sc.oneshot_mode == "classify":
                classify_and_assign(os_profiles)

        # Select diverse subset
        selected_os = select_diverse_oneshots(os_profiles, n=sc.oneshot_count)

        # For drums, reclassify after diversity selection and arrange into pad layout
        if stem_name == "drums" and sc.oneshot_mode == "classify":
            classify_and_assign(selected_os)
            pads = arrange_drum_pads(selected_os, n_pads=sc.oneshot_count)
            selected_os = [p for p in pads if p is not None]

        # Copy selected one-shots to curated dir
        stem_os_dir = curated_root / stem_name / "oneshots"
        stem_os_dir.mkdir(parents=True, exist_ok=True)

        oneshot_entries = []
        stem_schema = schema_config.for_stem(stem_name)
        for oi, profile in enumerate(selected_os):
            if profile is None or profile.path is None:
                continue
            dst = stem_os_dir / f"os_{oi + 1:03d}.wav"
            shutil.copy2(profile.path, dst)
            entry = {
                "position": oi + 1,
                "file": str(dst),
                "classification": profile.classification,
                "spectral": {
                    "centroid_hz": round(profile.spectral_centroid, 1),
                    "brightness": round(min(profile.spectral_centroid / 10000, 1.0), 3),
                },
                "duration_ms": round(profile.duration * 1000, 1),
                "rms": round(profile.rms, 4),
                "crest_factor": round(profile.crest_factor, 2),
            }
            # Oneshots have no fixed phrase_bars — pass None so beat_pos_end is
            # derived from BPM + duration.
            entry.update(build_curation_block(
                dst, phrase_bars=None,
                time_sig_numerator=time_sig,
                stem_schema=stem_schema,
                bpm=bpm,
            ))
            oneshot_entries.append(entry)

        # Upgrade manifest stem entry to v2 format (loops + oneshots)
        existing = curated_manifest["stems"].get(stem_name, [])
        if isinstance(existing, list):
            curated_manifest["stems"][stem_name] = {
                "loops": existing,
                "oneshots": oneshot_entries,
            }
        elif isinstance(existing, dict):
            existing["oneshots"] = oneshot_entries

        if json_events:
            emit({
                "event": "progress",
                "phase": "oneshots",
                "pct": 85,
                "message": f"{stem_name}: {len(oneshot_entries)} one-shots selected",
            })

    # Normalize all stems to {loops, oneshots} shape — stems that skipped
    # oneshot extraction (loops-only mode, or non-drum stems in production
    # mode) are still bare lists at this point.
    for stem_name, stem_entry in list(curated_manifest["stems"].items()):
        if isinstance(stem_entry, list):
            curated_manifest["stems"][stem_name] = {
                "loops": stem_entry,
                "oneshots": [],
            }

    # Embed processing config (pipeline targets) into manifest for M4L loader
    if pipeline and pipeline.exists():
        import yaml
        pipeline_data = yaml.safe_load(pipeline.read_text())
        if "stems" in pipeline_data:
            curated_manifest["processing_config"] = pipeline_data["stems"]
    elif pipeline and not pipeline.exists():
        # Try JSON variant (compiled from YAML)
        json_pipeline = pipeline.with_suffix(".json")
        if json_pipeline.exists():
            pipeline_data = json.loads(json_pipeline.read_text())
            if "stems" in pipeline_data:
                curated_manifest["processing_config"] = pipeline_data["stems"]

    # Write curated manifest
    manifest_path = curated_root / "manifest.json"
    manifest_path.write_text(json.dumps(curated_manifest, indent=2))

    # Also update the main stems.json if it exists
    main_manifest = stems_dir / "stems.json"
    if main_manifest.exists():
        main_data = json.loads(main_manifest.read_text())
        # Count items per stem from the manifest we just built
        bars_per_stem = max(
            (len(v) for v in curated_manifest["stems"].values()), default=0
        )
        main_data["curated"] = {
            "manifest": str(manifest_path),
            "n_bars": n_bars,
            "strategy": strategy,
            "bars_per_stem": bars_per_stem,
        }
        main_manifest.write_text(json.dumps(main_data, indent=2))

    # Summary counts from manifest (handles both v1 list and v2 dict formats)
    def _count_items(v):
        if isinstance(v, list):
            return len(v)
        if isinstance(v, dict):
            return len(v.get("loops", [])) + len(v.get("oneshots", []))
        return 0

    total_items = sum(_count_items(v) for v in curated_manifest["stems"].values())
    items_per_stem = {k: _count_items(v) for k, v in curated_manifest["stems"].items()}

    if json_events:
        emit({
            "event": "progress",
            "phase": "curating",
            "pct": 95,
            "message": f"Curated {total_items} items across {len(stems)} stems",
        })
        emit({
            "event": "curated",
            "manifest": str(manifest_path),
            "items_per_stem": items_per_stem,
            "stems": list(stems.keys()),
            "bpm": bpm,
        })

    return manifest_path


def main():
    ap = argparse.ArgumentParser(description="Bar-slice + curate stems from a split session")
    ap.add_argument("--stems-dir", required=True, type=Path,
                    help="Directory containing drums.wav, bass.wav, etc.")
    ap.add_argument("--n-bars", type=int, default=16,
                    help="Number of bars to select per stem (default: 16)")
    ap.add_argument("--strategy", default="max-diversity",
                    choices=["max-diversity", "rhythm-taxonomy", "sectional"])
    ap.add_argument("--time-sig", type=int, default=4,
                    help="Time signature numerator (default: 4)")
    ap.add_argument("--json-events", action="store_true",
                    help="Emit NDJSON events on stdout")
    ap.add_argument("--curation", type=Path, default=None,
                    help="Curation config YAML (default: pipelines/curation.yaml)")
    ap.add_argument("--pipeline", type=Path, default=None,
                    help="Processing pipeline YAML to embed in manifest (e.g. pipelines/production_idm.yaml)")
    args = ap.parse_args()

    curation_cfg = load_curation_config(args.curation) if args.curation else None
    schema_cfg = load_curation_schema_config(args.curation) if args.curation else None

    try:
        manifest = run(
            stems_dir=args.stems_dir,
            n_bars=args.n_bars,
            strategy=args.strategy,
            time_sig=args.time_sig,
            json_events=args.json_events,
            curation_config=curation_cfg,
            pipeline=args.pipeline,
            schema_config=schema_cfg,
        )
        if not args.json_events:
            print(f"Curated manifest: {manifest}")
    except Exception as e:
        if args.json_events:
            emit({"event": "error", "phase": "curate", "message": str(e)})
        raise


if __name__ == "__main__":
    main()
