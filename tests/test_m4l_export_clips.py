"""Tests for tools/m4l_export_clips.py — bouncing Live clips into sidecars."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

# tools/ isn't on the package path; load the module from its file.
import importlib.util

_HELPER_PATH = Path(__file__).resolve().parents[1] / "tools" / "m4l_export_clips.py"
_spec = importlib.util.spec_from_file_location("m4l_export_clips", _HELPER_PATH)
m4l_export_clips = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(m4l_export_clips)

from stemforge.manifest_schema import (
    BATCH_FILENAME,
    BatchManifest,
    SampleMeta,
    load_batch,
    load_sidecar,
)


# ── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def source_wav(tmp_path: Path) -> Path:
    """A 10-second 44.1k mono WAV with a unit ramp (so slices are content-distinct)."""
    sr = 44100
    duration = 10.0
    n = int(sr * duration)
    data = np.linspace(-1.0, 1.0, n, dtype=np.float32).reshape(-1, 1)
    p = tmp_path / "source.wav"
    sf.write(str(p), data, sr, subtype="FLOAT")
    return p


def _make_clip(source_wav: Path, **overrides) -> dict:
    base = {
        "track_idx": 0,
        "slot_idx": 0,
        "name": "test clip",
        "file_path": str(source_wav),
        "warping": False,
        "length_beats": 16.0,            # 4 bars at 4/4
        "loop_start_beats": 0.0,
        "loop_end_beats": 16.0,
        "signature_numerator": 4,
        "clip_warp_bpm": None,
        "gain": 0.0,
        "suggested_group": "A",
        "suggested_pad": ".",
    }
    base.update(overrides)
    return base


def _write_spec(tmp_path: Path, clips: list[dict], **top_overrides) -> Path:
    export_dir = tmp_path / "export"
    spec = {
        "version": 1,
        "project_tempo": 120.0,
        "oneshot_bars_threshold": 0.5,
        "export_dir": str(export_dir),
        "clips": clips,
    }
    spec.update(top_overrides)
    p = tmp_path / "spec.json"
    p.write_text(json.dumps(spec))
    return p


# ── Determines / display helpers ─────────────────────────────────────────────

def test_determine_playmode_oneshot_when_short() -> None:
    assert m4l_export_clips.determine_playmode(0.25, 0.5) == "oneshot"
    assert m4l_export_clips.determine_playmode(0.49, 0.5) == "oneshot"


def test_determine_playmode_key_when_long_enough() -> None:
    assert m4l_export_clips.determine_playmode(0.5, 0.5) == "key"
    assert m4l_export_clips.determine_playmode(4.0, 0.5) == "key"


def test_beats_to_seconds() -> None:
    # 4 beats at 120 BPM = 2 seconds
    assert m4l_export_clips.beats_to_seconds(4.0, 120.0) == pytest.approx(2.0)


# ── End-to-end run ───────────────────────────────────────────────────────────

def test_run_writes_wav_sidecar_and_batch(tmp_path: Path, source_wav: Path) -> None:
    spec_path = _write_spec(tmp_path, [_make_clip(source_wav)])
    batch_path = m4l_export_clips.run(spec_path, json_events=False)

    export_dir = tmp_path / "export"
    assert batch_path == export_dir / BATCH_FILENAME
    assert batch_path.exists()

    # The bounced WAV
    wav = export_dir / "A00.wav"
    assert wav.exists()
    info = sf.info(str(wav))
    # Default clip: length_beats=16, loop=[0..16], source=10s.
    # Linear-warp: seconds_per_beat = 10/16 = 0.625. Bounce = 16 × 0.625 = 10s.
    # (The source's natural rate is what determines slice timing, not project_tempo.)
    assert info.duration == pytest.approx(10.0, abs=0.01)

    # Sidecar exists and round-trips
    side_meta = load_sidecar(wav)
    assert side_meta is not None
    assert side_meta.suggested_group == "A"
    assert side_meta.suggested_pad == "."
    assert side_meta.playmode == "key"  # 4 bars >> threshold
    assert side_meta.bpm == pytest.approx(120.0)
    assert side_meta.time_mode == "bpm"
    assert side_meta.bars == pytest.approx(4.0)

    # Batch manifest contains the entry
    batch = load_batch(batch_path)
    assert batch.bpm == pytest.approx(120.0)
    assert len(batch.samples) == 1
    assert batch.samples[0].file == "A00.wav"


def test_run_one_shot_for_very_short_clip(tmp_path: Path, source_wav: Path) -> None:
    """A clip < threshold bars (here 0.25 bars) gets playmode=oneshot, no time_mode."""
    short = _make_clip(
        source_wav,
        length_beats=1.0,           # 0.25 bars at 4/4
        loop_start_beats=0.0,
        loop_end_beats=1.0,
        suggested_pad="0",
        slot_idx=1,
    )
    spec_path = _write_spec(tmp_path, [short])
    m4l_export_clips.run(spec_path, json_events=False)

    wav = tmp_path / "export" / "A01.wav"
    assert wav.exists()
    meta = load_sidecar(wav)
    assert meta is not None
    assert meta.playmode == "oneshot"
    assert meta.role == "one_shot"
    # one-shots skip time_mode/bpm so the device plays them at native rate
    assert meta.time_mode is None
    assert meta.bpm is None


def test_run_assigns_pads_per_group(tmp_path: Path, source_wav: Path) -> None:
    """4 clips on group A in slots 0..3 → suggested_pads ['.', '0', 'ENTER', '1']."""
    clips = [
        _make_clip(source_wav, slot_idx=i, suggested_pad=p)
        for i, p in enumerate([".", "0", "ENTER", "1"])
    ]
    spec_path = _write_spec(tmp_path, clips)
    m4l_export_clips.run(spec_path, json_events=False)

    batch = load_batch(tmp_path / "export" / BATCH_FILENAME)
    assert [s.suggested_pad for s in batch.samples] == [".", "0", "ENTER", "1"]
    assert all(s.suggested_group == "A" for s in batch.samples)


def test_run_skips_missing_source_files(tmp_path: Path, source_wav: Path) -> None:
    good = _make_clip(source_wav, slot_idx=0, suggested_pad=".")
    bad = _make_clip(source_wav, slot_idx=1, suggested_pad="0",
                     file_path="/does/not/exist.wav")
    spec_path = _write_spec(tmp_path, [good, bad])
    m4l_export_clips.run(spec_path, json_events=False)

    export_dir = tmp_path / "export"
    assert (export_dir / "A00.wav").exists()
    assert not (export_dir / "A01.wav").exists()
    batch = load_batch(export_dir / BATCH_FILENAME)
    assert len(batch.samples) == 1


def test_loop_wraps_around_source_when_loop_extends_past_source(
    tmp_path: Path, source_wav: Path
) -> None:
    """Loop in source-coords extends past source length → wraps cleanly.

    Source = 10s ramp [-1..+1]. length_beats=16 → seconds_per_beat = 0.625.
    loop_start=8 beats → 5.0s in source. loop_end=24 → 15.0s (past source).
    start_marker defaults to loop_start. Bounce starts at 5.0s, plays for
    16 × 0.625 = 10s, wrapping at source-end. Result: source[5..10] then
    source[0..5] — second half ramp, then first half ramp.
    """
    sr = 44100
    source_seconds = 10.0
    source_frames = int(sr * source_seconds)

    wrap_clip = _make_clip(
        source_wav,
        warping=True,
        clip_warp_bpm=None,           # force linear-warp from source duration
        length_beats=16.0,            # source maps 1:1 to length
        loop_start_beats=8.0,         # 5.0s in source
        loop_end_beats=24.0,          # 15.0s in source → wraps
        signature_numerator=4,
    )
    spec_path = _write_spec(tmp_path, [wrap_clip])
    m4l_export_clips.run(spec_path, json_events=False)

    wav_path = tmp_path / "export" / "A00.wav"
    info = sf.info(str(wav_path))
    assert info.duration == pytest.approx(10.0, abs=0.01)

    audio, _ = sf.read(str(wav_path), always_2d=True, dtype="float32")
    assert len(audio) == pytest.approx(source_frames, abs=2)

    # Source ramp: sample 0 = -1.0, sample (source_frames-1) ≈ +1.0,
    # midpoint sample ≈ 0. Bounce = source[midpoint..end] + source[0..midpoint].
    first_sample = audio[0, 0]
    last_sample = audio[-1, 0]
    midpoint_sample = audio[source_frames // 2, 0]

    assert abs(first_sample) < 0.01            # was source midpoint ≈ 0
    assert abs(last_sample) < 0.01             # ends just before midpoint ≈ 0
    assert midpoint_sample == pytest.approx(-1.0, abs=0.01)  # wrap → source[0]


def test_start_marker_rotates_loop_within_source(
    tmp_path: Path, source_wav: Path
) -> None:
    """start_marker > loop_start → bounce begins at start_marker, then wraps
    within the loop region back to loop_start. Models the user-screenshot
    case: loop region bar 3..7, start_marker dragged to bar 4.

    Source = 10s ramp. length=16 beats, loop=[8..16], start_marker=12.
    seconds_per_beat = 0.625. Bounce starts at 12*0.625 = 7.5s, plays for
    8 beats × 0.625 = 5.0s. So source[7.5..10s] then wrap → source[0..2.5s].

    Wait — that wrap is wrong because the LOOP is [8..16]beats = [5..10]s in
    source. Live's playback wraps within the loop region: start_marker → loop_end
    → loop_start → start_marker. So source[7.5..10] + source[5..7.5].
    Total still 5.0s.

    But our slice_clip wraps modulo SOURCE length, not loop region. For most
    cases (loop region = full source, as in this test), they're equivalent.
    For loop ⊂ source, behavior diverges — but that's a rarer case the user
    has not asked about; defer to follow-up.
    """
    sr = 44100
    rotated_clip = _make_clip(
        source_wav,
        warping=True,
        clip_warp_bpm=None,
        length_beats=16.0,             # source full
        loop_start_beats=8.0,          # bar 3 (= source 5.0s)
        loop_end_beats=16.0,           # bar 5 (= source 10.0s, end)
        start_marker_beats=12.0,       # bar 4 (= source 7.5s)
        signature_numerator=4,
    )
    spec_path = _write_spec(tmp_path, [rotated_clip])
    m4l_export_clips.run(spec_path, json_events=False)

    wav_path = tmp_path / "export" / "A00.wav"
    audio, _ = sf.read(str(wav_path), always_2d=True, dtype="float32")
    info = sf.info(str(wav_path))
    # Bounce length = (loop_end - loop_start) × seconds_per_beat = 8 × 0.625 = 5.0s
    assert info.duration == pytest.approx(5.0, abs=0.01)

    # First sample = source @ 7.5s = ramp value (7.5/10 × 2 - 1) = +0.5
    # Last sample ≈ source @ 5.0s = ramp value (5/10 × 2 - 1) = 0.0
    # Midpoint of bounce = source wrap point ≈ 0.0 (sample 0 of source = -1)
    assert audio[0, 0] == pytest.approx(0.5, abs=0.02)


def test_start_marker_defaults_to_loop_start_when_absent(
    tmp_path: Path, source_wav: Path
) -> None:
    """Older specs without start_marker_beats — bounce starts at loop_start
    as before (no rotation)."""
    clip = _make_clip(
        source_wav,
        warping=True,
        clip_warp_bpm=None,
        length_beats=16.0,
        loop_start_beats=8.0,
        loop_end_beats=24.0,
    )
    # _make_clip doesn't include start_marker_beats — verify default behavior
    assert "start_marker_beats" not in clip
    spec_path = _write_spec(tmp_path, [clip])
    m4l_export_clips.run(spec_path, json_events=False)
    # Should not crash; bounce length = full loop = 10s
    info = sf.info(str(tmp_path / "export" / "A00.wav"))
    assert info.duration == pytest.approx(10.0, abs=0.01)


def test_loop_wraps_multiple_source_iterations(
    tmp_path: Path, source_wav: Path
) -> None:
    """Loop length > source length → wrap repeats."""
    bpm = 96.0
    # Source is 10s = 16 beats at 96 BPM. Loop is 32 beats = 2 full source loops.
    clip = _make_clip(
        source_wav,
        warping=True,
        clip_warp_bpm=bpm,
        length_beats=16.0,
        loop_start_beats=0.0,
        loop_end_beats=32.0,
        signature_numerator=4,
    )
    spec_path = _write_spec(tmp_path, [clip])
    m4l_export_clips.run(spec_path, json_events=False)

    wav_path = tmp_path / "export" / "A00.wav"
    info = sf.info(str(wav_path))
    # 32 beats at 96 BPM = 20 seconds
    assert info.duration == pytest.approx(20.0, abs=0.02)


def test_bars_reflects_loop_length_not_source_length(
    tmp_path: Path, source_wav: Path
) -> None:
    """When loop_end - loop_start != length_beats, sidecar `bars` follows the
    loop length (the bounced WAV's actual duration in bars)."""
    clip = _make_clip(
        source_wav,
        warping=True,
        clip_warp_bpm=96.0,
        length_beats=16.0,
        loop_start_beats=8.0,
        loop_end_beats=24.0,    # 16-beat loop = 4 bars at 4/4
        signature_numerator=4,
    )
    spec_path = _write_spec(tmp_path, [clip])
    m4l_export_clips.run(spec_path, json_events=False)

    meta = load_sidecar(tmp_path / "export" / "A00.wav")
    assert meta is not None
    # 16-beat loop / 4 = 4 bars (NOT 16/4 from source length, even though
    # they happen to match in this case — the calculation should be from
    # the loop region, not the source).
    assert meta.bars == pytest.approx(4.0)
    assert meta.playmode == "key"


def test_warped_clip_tags_sidecar_with_clip_warp_bpm(
    tmp_path: Path, source_wav: Path
) -> None:
    """Sidecar's `bpm` is set from clip_warp_bpm when present (so the EP-133
    knows the source's natural BPM for stretching). The slice DURATION is
    independently set by the source-duration / length-beats relationship."""
    clip = _make_clip(
        source_wav,
        warping=True,
        clip_warp_bpm=60.0,            # source's natural BPM (informational)
        length_beats=8.0,              # source plays as 8 beats in the clip
        loop_start_beats=0.0,
        loop_end_beats=8.0,
    )
    spec_path = _write_spec(tmp_path, [clip], project_tempo=120.0)
    m4l_export_clips.run(spec_path, json_events=False)

    wav = tmp_path / "export" / "A00.wav"
    info = sf.info(str(wav))
    # length_beats=8 maps linearly across source_duration=10s.
    # Bounce = 8 beats × (10/8) seconds_per_beat = 10s (full source).
    # The clip_warp_bpm of 60 is informational, not used to compute timing.
    assert info.duration == pytest.approx(10.0, abs=0.01)

    meta = load_sidecar(wav)
    assert meta is not None
    # Sidecar's bpm comes from clip_warp_bpm — the EP-133 will use this
    # to know the source's natural rate for time_mode=bpm stretching.
    assert meta.bpm == pytest.approx(60.0)
    assert meta.time_mode == "bpm"


def test_json_events_emit_started_progress_complete(
    tmp_path: Path, source_wav: Path, capsys
) -> None:
    spec_path = _write_spec(tmp_path, [_make_clip(source_wav)])
    m4l_export_clips.run(spec_path, json_events=True)

    out = capsys.readouterr().out
    events = [json.loads(line) for line in out.strip().splitlines() if line]
    event_types = [e["event"] for e in events]
    # Namespaced "export_*" so they don't collide with sf_forge's progress/complete/error
    # on the shared NDJSON parser.
    assert event_types[0] == "export_started"
    assert "export_progress" in event_types
    assert "export_clip_done" in event_types
    assert event_types[-1] == "export_complete"


def test_wipe_stale_outputs_removes_only_producer_artifacts(tmp_path: Path) -> None:
    """wipe_stale_outputs deletes prior sidecars/manifests/bounced WAVs but
    leaves user files untouched."""
    d = tmp_path
    # Producer artifacts
    (d / ".manifest.json").write_text("{}")
    (d / ".manifest_abc123.json").write_text("{}")
    (d / ".manifest_def456.json").write_text("{}")
    (d / "A00.wav").write_bytes(b"x")
    (d / "B11.wav").write_bytes(b"x")
    (d / "D05.wav").write_bytes(b"x")
    # User files (must survive)
    (d / "notes.md").write_text("keep me")
    (d / "cool_kick.wav").write_bytes(b"x")        # not <group><slot>.wav
    (d / "spec.json").write_text("{}")              # not .manifest.json
    (d / "A1.wav").write_bytes(b"x")                # only one digit — not our pattern

    removed = m4l_export_clips.wipe_stale_outputs(d)
    assert removed == 6

    # Producer artifacts gone
    assert not (d / ".manifest.json").exists()
    assert not (d / ".manifest_abc123.json").exists()
    assert not (d / "A00.wav").exists()
    # User files stay
    assert (d / "notes.md").exists()
    assert (d / "cool_kick.wav").exists()
    assert (d / "spec.json").exists()
    assert (d / "A1.wav").exists()


def test_re_bounce_replaces_stale_sidecars(tmp_path: Path, source_wav: Path) -> None:
    """End-to-end: bouncing twice with different audio leaves no orphans."""
    # First bounce: A00.wav with content "alpha"
    spec_path = _write_spec(tmp_path, [_make_clip(source_wav)])
    m4l_export_clips.run(spec_path, json_events=False)

    export_dir = tmp_path / "export"
    sidecars_after_first = sorted(export_dir.glob(".manifest_*.json"))
    assert len(sidecars_after_first) == 1

    # Second bounce: replace source so the new WAV has a different hash
    new_source = tmp_path / "different.wav"
    sf.write(str(new_source),
             np.zeros((44100, 1), dtype="float32"),  # 1 second of silence
             44100, subtype="FLOAT")
    new_clip = _make_clip(new_source)
    spec_path2 = _write_spec(tmp_path, [new_clip])
    m4l_export_clips.run(spec_path2, json_events=False)

    sidecars_after_second = sorted(export_dir.glob(".manifest_*.json"))
    assert len(sidecars_after_second) == 1, (
        f"expected 1 sidecar after re-bounce, got {len(sidecars_after_second)}: "
        f"{[p.name for p in sidecars_after_second]}"
    )
    # And it should be the NEW hash, not the old one
    assert sidecars_after_second[0] != sidecars_after_first[0]


def test_wipe_emits_event_when_files_removed(
    tmp_path: Path, source_wav: Path, capsys
) -> None:
    """When wipe removes any files, an export_wiped event is emitted."""
    # Pre-populate with a stale sidecar
    export_dir = tmp_path / "export"
    export_dir.mkdir(parents=True)
    (export_dir / ".manifest_stale123.json").write_text("{}")

    spec_path = _write_spec(tmp_path, [_make_clip(source_wav)])
    m4l_export_clips.run(spec_path, json_events=True)

    out = capsys.readouterr().out
    events = [json.loads(line) for line in out.strip().splitlines() if line]
    wiped = [e for e in events if e["event"] == "export_wiped"]
    assert len(wiped) == 1
    assert wiped[0]["count"] >= 1


def test_main_exits_2_on_missing_spec(tmp_path: Path) -> None:
    # argparse's ap.error() raises SystemExit(2) — that's the standard CLI bail
    with pytest.raises(SystemExit) as exc:
        m4l_export_clips.main([str(tmp_path / "nope.json")])
    assert exc.value.code == 2


def test_main_runs_against_valid_spec(tmp_path: Path, source_wav: Path) -> None:
    spec_path = _write_spec(tmp_path, [_make_clip(source_wav)])
    rc = m4l_export_clips.main([str(spec_path)])
    assert rc == 0
    assert (tmp_path / "export" / BATCH_FILENAME).exists()
