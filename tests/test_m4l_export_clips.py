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
    # 16 beats at 120 BPM = 8 seconds
    assert info.duration == pytest.approx(8.0, abs=0.01)

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


def test_warped_clip_uses_clip_warp_bpm_for_seconds(tmp_path: Path, source_wav: Path) -> None:
    """A warped clip's loop bounds are in beats AT THE CLIP's WARP BPM, not project tempo."""
    # Clip is 8 beats long at 60 BPM source → 8 seconds of source audio
    clip = _make_clip(
        source_wav,
        warping=True,
        clip_warp_bpm=60.0,
        length_beats=8.0,
        loop_start_beats=0.0,
        loop_end_beats=8.0,
    )
    spec_path = _write_spec(tmp_path, [clip], project_tempo=120.0)
    m4l_export_clips.run(spec_path, json_events=False)

    wav = tmp_path / "export" / "A00.wav"
    info = sf.info(str(wav))
    # 8 beats / 60 BPM = 8 seconds
    assert info.duration == pytest.approx(8.0, abs=0.01)

    meta = load_sidecar(wav)
    assert meta is not None
    # Source BPM is the clip's warp BPM (60), NOT the project tempo (120)
    assert meta.bpm == pytest.approx(60.0)


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
