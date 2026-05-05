"""Tests for `stemforge.schemas` — Pydantic models for the three undocumented
JSON contracts (stems.json, prechop_manifest.json, snapshot.json).

Hardening Stream A.2. Each schema is round-tripped through a real producer
and validated; deliberate shape-drift cases are also tested to confirm the
models flag missing required fields.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf
from pydantic import ValidationError

from stemforge.manifest import (
    InputAudio,
    StemInfo,
    StemManifest,
    TempoProvenance,
    write_manifest,
)
from stemforge.prechop import frames_per_bar, prechop
from stemforge.schemas import (
    PrechopManifestModel,
    SnapshotModel,
    StemsManifestModel,
    validate_prechop_manifest,
    validate_snapshot,
    validate_stems_manifest,
)


SR = 22050
BPM = 120.0
FPB = frames_per_bar(BPM, SR, beats_per_bar=4)


def _write_silent_stem(path: Path, n_frames: int = FPB * 4) -> None:
    y = np.zeros((n_frames, 2), dtype=np.float32)
    sf.write(str(path), y, SR, subtype="PCM_24")


# ── stems.json ───────────────────────────────────────────────────────────────


def test_stems_manifest_validates_real_writer_output(tmp_path):
    # Write a real `stems.json` via the CLI's writer, validate it back through
    # the Pydantic schema. Round-trip proves producer ↔ schema agreement.
    source = tmp_path / "song.wav"
    _write_silent_stem(source)
    drums = tmp_path / "drums.wav"
    bass = tmp_path / "bass.wav"
    _write_silent_stem(drums)
    _write_silent_stem(bass)

    out_dir = tmp_path / "out"
    out_dir.mkdir()
    write_manifest(
        output_dir=out_dir,
        track_name="test_track",
        source_file=source,
        backend="demucs",
        bpm=BPM,
        beat_count=16,
        stem_paths={"drums": drums, "bass": bass},
        slice_counts={"drums": 16, "bass": 16},
        pipeline="default",
        tempo=TempoProvenance(source="beat-this:mix", confidence="high", n_downbeats=4),
        input_audio=InputAudio(sample_rate=SR, duration_samples=FPB * 4, sha256="0" * 64),
    )

    stems_path = out_dir / "stems.json"
    assert stems_path.exists()
    model = validate_stems_manifest(stems_path)
    assert model.track_name == "test_track"
    assert model.bpm == BPM
    assert len(model.stems) == 2
    assert model.tempo is not None
    assert model.tempo.source == "beat-this:mix"
    assert model.input_audio is not None


def test_stems_manifest_rejects_missing_required_field():
    # A required field absent → ValidationError with a clear locator.
    bad = asdict(
        StemManifest(
            track_name="x",
            source_file="x",
            backend="demucs",
            bpm=120.0,
            beat_count=0,
            stems=[],
            output_dir="x",
            pipeline="default",
            processed_at="2026-05-05T12:00:00",
        )
    )
    bad.pop("track_name")
    with pytest.raises(ValidationError) as exc:
        validate_stems_manifest(bad)
    assert "track_name" in str(exc.value)


def test_stems_manifest_extra_fields_are_ignored():
    # Forward-compat: a producer that adds a new field must not break a
    # consumer running against the old schema.
    payload = asdict(
        StemManifest(
            track_name="x",
            source_file="x",
            backend="demucs",
            bpm=120.0,
            beat_count=0,
            stems=[StemInfo(name="drums", wav_path="x.wav", beats_dir="d", beat_count=0)],
            output_dir="x",
            pipeline="default",
            processed_at="2026-05-05T12:00:00",
        )
    )
    payload["future_field"] = "ignored"
    model = validate_stems_manifest(payload)
    assert model.track_name == "x"


# ── prechop_manifest.json ────────────────────────────────────────────────────


def test_prechop_manifest_validates_real_writer_output(tmp_path):
    drums = tmp_path / "drums.wav"
    _write_silent_stem(drums, FPB * 8)
    out = tmp_path / "out"
    out.mkdir()
    manifest_path = prechop(
        {"drums": drums},
        out,
        bpm=BPM,
        bars=2,
        pad_bars=1,
        pad_last=True,
        write_sidecars=False,
    )
    model = validate_prechop_manifest(manifest_path)
    assert model.bpm == BPM
    assert model.bars == 2
    assert "drums" in model.stems
    assert model.stems["drums"].chunk_count >= 1
    # Stream A.1 field flows through the schema:
    for chunk in model.stems["drums"].chunks:
        assert chunk.audio_hash is not None
        assert len(chunk.audio_hash) == 16


def test_prechop_manifest_rejects_missing_required_field():
    payload = {
        # missing "bpm"
        "bars": 2,
        "pad_bars": 1,
        "pad_pre_bars": 1,
        "pad_post_bars": 1,
        "pad_last": True,
        "beats_per_bar": 4,
        "first_downbeat_sec": 0.0,
        "pre_bars": 0,
        "musical_bar_1_chunk_index": 0,
        "leading_partial_emitted": False,
        "stems": {},
    }
    with pytest.raises(ValidationError) as exc:
        validate_prechop_manifest(payload)
    assert "bpm" in str(exc.value)


# ── snapshot.json ────────────────────────────────────────────────────────────


def _example_snapshot_payload() -> dict:
    """Mirror of the JS source-of-truth shape at
    `v0/src/m4l-js/sf_arrangement_reader.js` header lines 17-34."""
    return {
        "tempo": 120.0,
        "time_sig": [4, 4],
        "arrangement_length_sec": 64.0,
        "locators": [
            {"time_sec": 0.0, "name": "Verse"},
            {"time_sec": 16.0, "name": "Chorus"},
        ],
        "tracks": {
            "A": [
                {
                    "file_path": "/abs/path.wav",
                    "start_time_sec": 0.0,
                    "length_sec": 4.0,
                    "warping": 1,
                }
            ],
            "B": [],
            "C": [],
            "D": [],
        },
    }


def test_snapshot_validates_canonical_shape():
    model = validate_snapshot(_example_snapshot_payload())
    assert model.tempo == 120.0
    assert model.time_sig == (4, 4)
    assert len(model.locators) == 2
    assert model.locators[0].name == "Verse"
    assert len(model.tracks["A"]) == 1
    assert model.tracks["A"][0].warping == 1


def test_snapshot_validates_json_string_input():
    model = validate_snapshot(json.dumps(_example_snapshot_payload()))
    assert model.tempo == 120.0


def test_snapshot_validates_path_input(tmp_path):
    p = tmp_path / "snapshot.json"
    p.write_text(json.dumps(_example_snapshot_payload()))
    model = validate_snapshot(p)
    assert model.tempo == 120.0


def test_snapshot_rejects_missing_tempo():
    payload = _example_snapshot_payload()
    del payload["tempo"]
    with pytest.raises(ValidationError) as exc:
        validate_snapshot(payload)
    assert "tempo" in str(exc.value)


def test_snapshot_extra_fields_ignored():
    payload = _example_snapshot_payload()
    payload["debug_field"] = {"anything": True}
    payload["tracks"]["A"][0]["future_property"] = "ignored"
    model = validate_snapshot(payload)
    # Inner extra is dropped (no future_property attr).
    assert not hasattr(model.tracks["A"][0], "future_property")


def test_snapshot_locator_default_name_empty():
    payload = _example_snapshot_payload()
    payload["locators"][0] = {"time_sec": 0.0}  # no name
    model = validate_snapshot(payload)
    assert model.locators[0].name == ""


# ── Cross-schema sanity ──────────────────────────────────────────────────────


def test_models_export_via_module_all():
    # Re-affirms the public surface advertised by `__all__`.
    from pydantic import BaseModel

    from stemforge import schemas

    for name in (
        "StemsManifestModel",
        "PrechopManifestModel",
        "SnapshotModel",
        "validate_stems_manifest",
        "validate_prechop_manifest",
        "validate_snapshot",
    ):
        assert hasattr(schemas, name), f"{name} missing from schemas module"
    for model_cls in (StemsManifestModel, PrechopManifestModel, SnapshotModel):
        assert issubclass(model_cls, BaseModel)
