"""Tests for `stemforge.forge.manifest_io` — Phase 1A compat shim.

Covers:
- `load_forge` auto-detection of new vs legacy shape.
- Atomic write helpers + manifest_hash recomputation invariant.
- Pydantic-validated reads with clean error surfacing.
- Legacy → new conversion via `migrate_legacy`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from stemforge.configurator.schemas import (
    ArrangementManifest,
    ForgeClip,
    ForgeManifest,
    compute_manifest_hash,
)
from stemforge.forge import (
    ForgeManifestError,
    build_arrangement_from_prechop,
    build_empty_arrangement,
    build_from_curated_dict,
    legacy_manifest_exists,
    load_arrangement,
    load_forge,
    migrate_legacy,
    new_manifest_exists,
    write_arrangement,
    write_auto_curation,
)
from stemforge.forge.manifest_io import (
    ARRANGEMENT_FILENAME,
    AUTO_CURATION_FILENAME,
)


FIXTURES = Path(__file__).resolve().parent / "fixtures" / "forges"


# ── Helpers ──────────────────────────────────────────────────────────────────


def _legacy_manifest_from_new(new_path: Path, source_audio: str = "/tmp/test.wav") -> dict:
    """Build a legacy v1 single-file `curated/manifest.json` dict equivalent
    to a Phase 0 new-shape `auto_curation_manifest.json`.

    Maps the new shape's per-clip entries into the legacy `stems` dict so we
    can round-trip migrate → new and assert byte-for-byte equality on the
    invariants.
    """
    new_data = json.loads(new_path.read_text())
    stems: dict[str, list] = {}
    # We need to map new clip stem labels (drum/bass/vocal/other) back to the
    # legacy plural form (drums/bass/vocals/other) so _stem_label round-trips.
    LABEL_TO_LEGACY = {"drum": "drums", "bass": "bass", "vocal": "vocals", "other": "other"}
    for clip in new_data["clips"]:
        legacy_stem = LABEL_TO_LEGACY[clip["stem"]]
        stems.setdefault(legacy_stem, []).append(
            {
                "position": stems.get(legacy_stem, [{}])[-1].get("position", 0) + 1
                if stems.get(legacy_stem)
                else 1,
                "clip_id": clip["clip_id"],
                "file": clip["audio_path"],
                "duration_bars": clip["duration_bars"],
                "tags": clip["tags"],
            }
        )
    return {
        "track": new_data["forge_slug"],
        "source_audio": new_data.get("source_audio") or source_audio,
        "strategy": "max-diversity",
        "n_bars": new_data["clips"][0]["duration_bars"] if new_data["clips"] else 4,
        "bpm": new_data["bpm"],
        "first_downbeat_sec": new_data["first_downbeat_sec"],
        "time_signature_numerator": 4,
        "stems": stems,
    }


# ── Helper round-trips ───────────────────────────────────────────────────────


def test_compute_manifest_hash_canonical_independent_of_key_order():
    """Two dicts with the same content but different insertion order hash
    to the same value — keys are canonicalized before hashing."""
    a = [{"clip_id": "x", "stem": "drum"}]
    b = [{"stem": "drum", "clip_id": "x"}]
    assert compute_manifest_hash(a) == compute_manifest_hash(b)


def test_compute_manifest_hash_matches_phase0_fixtures():
    """The Phase 0 fixtures' stored manifest_hash equals what
    compute_manifest_hash returns on their clips/chunks arrays."""
    for forge in ("sample-forge", "breaks-n-beats-deck"):
        ac = json.loads((FIXTURES / forge / "auto_curation_manifest.json").read_text())
        ar = json.loads((FIXTURES / forge / "arrangement_manifest.json").read_text())
        assert ac["manifest_hash"] == compute_manifest_hash(ac["clips"]), forge
        assert ar["manifest_hash"] == compute_manifest_hash(ar["chunks"]), forge


# ── Atomic writers ──────────────────────────────────────────────────────────


def test_write_auto_curation_atomic_recomputes_hash(tmp_path: Path):
    """Writer recomputes manifest_hash from the canonical clips array,
    overwriting whatever the caller put on the model."""
    fm = ForgeManifest(
        schema_version=1,
        forge_slug="test",
        source_audio="/tmp/t.wav",
        bpm=120.0,
        first_downbeat_sec=0.0,
        manifest_hash="0" * 64,  # bogus — writer must overwrite
        clips=[
            ForgeClip(
                clip_id="drum-bar0-4",
                audio_path="curated_audio/drum-bar0-4.wav",
                stem="drum",
                source_bar_range=(0, 4),
                duration_bars=4,
            )
        ],
    )
    out = write_auto_curation(tmp_path, fm)
    assert out.name == AUTO_CURATION_FILENAME
    on_disk = json.loads(out.read_text())
    expected = compute_manifest_hash([c.model_dump(mode="json") for c in fm.clips])
    assert on_disk["manifest_hash"] == expected
    assert on_disk["manifest_hash"] != "0" * 64
    # No leftover temp file
    assert not list(tmp_path.glob("*.tmp"))


def test_write_arrangement_atomic_recomputes_hash(tmp_path: Path):
    am = build_empty_arrangement(
        slug="test", source_audio="/tmp/t.wav", bpm=120.0, first_downbeat_sec=0.0
    )
    out = write_arrangement(tmp_path, am)
    assert out.name == ARRANGEMENT_FILENAME
    on_disk = json.loads(out.read_text())
    assert on_disk["manifest_hash"] == compute_manifest_hash([])
    assert on_disk["chunks"] == []


# ── load_forge auto-detection ────────────────────────────────────────────────


def test_load_forge_new_shape(tmp_path: Path):
    """load_forge returns a ForgeManifest from the new-shape file."""
    fixture = FIXTURES / "sample-forge"
    for f in ("auto_curation_manifest.json", "arrangement_manifest.json"):
        (tmp_path / f).write_text((fixture / f).read_text())
    assert new_manifest_exists(tmp_path)
    fm = load_forge("sample-forge", forge_dir=tmp_path)
    assert isinstance(fm, ForgeManifest)
    assert fm.forge_slug == "sample-forge"
    assert len(fm.clips) == 4
    am = load_arrangement("sample-forge", forge_dir=tmp_path)
    assert isinstance(am, ArrangementManifest)
    assert len(am.chunks) == 2


def test_load_forge_legacy_shape_only(tmp_path: Path):
    """When only legacy curated/manifest.json exists, load_forge converts on read."""
    legacy = _legacy_manifest_from_new(FIXTURES / "sample-forge" / "auto_curation_manifest.json")
    legacy_path = tmp_path / "curated" / "manifest.json"
    legacy_path.parent.mkdir()
    legacy_path.write_text(json.dumps(legacy))
    assert legacy_manifest_exists(tmp_path)
    assert not new_manifest_exists(tmp_path)
    fm = load_forge("sample-forge", forge_dir=tmp_path)
    assert isinstance(fm, ForgeManifest)
    assert fm.bpm == 120.0
    assert len(fm.clips) == 4
    # arrangement should be None (no inline arrangement in legacy)
    assert load_arrangement("sample-forge", forge_dir=tmp_path) is None


def test_load_forge_missing_both_raises_clean_error(tmp_path: Path):
    with pytest.raises(ForgeManifestError) as exc:
        load_forge("ghost", forge_dir=tmp_path)
    assert "ghost" in str(exc.value)
    assert "no manifest" in str(exc.value).lower()


def test_load_forge_corrupt_json_clean_error(tmp_path: Path):
    (tmp_path / AUTO_CURATION_FILENAME).write_text("{not valid json")
    with pytest.raises(ForgeManifestError) as exc:
        load_forge("broken", forge_dir=tmp_path)
    msg = str(exc.value)
    assert "broken" in msg
    assert "malformed" in msg.lower() or "invalid" in msg.lower()


def test_load_forge_malformed_pydantic_clean_error(tmp_path: Path):
    """Schema-valid JSON but Pydantic-invalid (negative bpm) → clean ClickException."""
    (tmp_path / AUTO_CURATION_FILENAME).write_text(
        json.dumps(
            {
                "schema_version": 1,
                "forge_slug": "bad",
                "source_audio": "/tmp/x.wav",
                "bpm": -1.0,  # forbidden
                "first_downbeat_sec": 0.0,
                "manifest_hash": "0" * 64,
                "clips": [],
            }
        )
    )
    with pytest.raises(ForgeManifestError) as exc:
        load_forge("bad", forge_dir=tmp_path)
    assert "bad" in str(exc.value)
    assert "bpm" in str(exc.value).lower()


# ── migrate_legacy ───────────────────────────────────────────────────────────


def test_migrate_legacy_round_trip_against_phase0_fixture(tmp_path: Path):
    """Round-trip: build legacy from Phase 0 fixture → migrate → assert
    the produced new-shape manifest matches the fixture on key invariants
    (bpm, first_downbeat_sec, clip count, manifest_hash via canonical).
    """
    fixture_new = json.loads(
        (FIXTURES / "breaks-n-beats-deck" / "auto_curation_manifest.json").read_text()
    )
    legacy_dict = _legacy_manifest_from_new(
        FIXTURES / "breaks-n-beats-deck" / "auto_curation_manifest.json"
    )
    (tmp_path / "curated").mkdir()
    (tmp_path / "curated" / "manifest.json").write_text(json.dumps(legacy_dict))

    fm_path, am_path = migrate_legacy("breaks-n-beats-deck", tmp_path)

    # Both files exist and validate.
    assert fm_path.exists()
    assert am_path.exists()
    on_disk_fm = json.loads(fm_path.read_text())
    assert on_disk_fm["forge_slug"] == "breaks-n-beats-deck"
    assert on_disk_fm["bpm"] == fixture_new["bpm"]
    assert on_disk_fm["first_downbeat_sec"] == fixture_new["first_downbeat_sec"]
    assert on_disk_fm["schema_version"] == 1
    # Same number of clips — content fidelity through the round-trip.
    assert len(on_disk_fm["clips"]) == len(fixture_new["clips"])
    # manifest_hash recomputed against on-disk clips.
    assert on_disk_fm["manifest_hash"] == compute_manifest_hash(on_disk_fm["clips"])
    # Legacy file is preserved (one-release compat window).
    assert (tmp_path / "curated" / "manifest.json").exists()


def test_migrate_legacy_missing_legacy_raises(tmp_path: Path):
    with pytest.raises(ForgeManifestError) as exc:
        migrate_legacy("ghost", tmp_path)
    assert "no legacy manifest" in str(exc.value).lower()


def test_migrate_legacy_malformed_legacy_raises(tmp_path: Path):
    (tmp_path / "curated").mkdir()
    (tmp_path / "curated" / "manifest.json").write_text("{ not json")
    with pytest.raises(ForgeManifestError) as exc:
        migrate_legacy("broken", tmp_path)
    msg = str(exc.value).lower()
    assert "malformed" in msg and "broken" in msg


# ── build_from_curated_dict ─────────────────────────────────────────────────


def test_build_from_curated_dict_synthesizes_bpm_when_missing(tmp_path: Path):
    """Legacy v0 forge dicts sometimes lack bpm — build_from_curated_dict
    synthesizes a placeholder (120.0) so the schema-required positive bpm
    doesn't reject the migration. Callers can override via the bpm kwarg.
    """
    curated = {
        "track": "x",
        "source_audio": "/tmp/x.wav",
        "stems": {"drums": [{"position": 1, "file": "curated/drums/bar_01.wav"}]},
        "n_bars": 1,
    }
    fm = build_from_curated_dict(slug="x", forge_dir=tmp_path, curated=curated)
    assert fm.bpm == 120.0
    assert len(fm.clips) == 1
    # Override path
    fm2 = build_from_curated_dict(slug="x", forge_dir=tmp_path, curated=curated, bpm=88.5)
    assert fm2.bpm == 88.5


def test_build_from_curated_dict_handles_v2_production_loops_block(tmp_path: Path):
    """v0 production curator nests entries under stems[X].loops — our
    extractor handles both list and dict-with-loops shapes."""
    curated = {
        "track": "prod",
        "source_audio": "/tmp/prod.wav",
        "bpm": 138.0,
        "n_bars": 4,
        "stems": {
            "drums": {
                "loops": [
                    {"position": 1, "file": "curated/drums/bar_01.wav", "duration_bars": 4},
                    {"position": 2, "file": "curated/drums/bar_02.wav", "duration_bars": 4},
                ],
                "oneshots": [],
            },
            "bass": [
                {"position": 1, "file": "curated/bass/bar_01.wav", "duration_bars": 4},
            ],
        },
    }
    fm = build_from_curated_dict(slug="prod", forge_dir=tmp_path, curated=curated)
    drum_clips = [c for c in fm.clips if c.stem == "drum"]
    bass_clips = [c for c in fm.clips if c.stem == "bass"]
    assert len(drum_clips) == 2
    assert len(bass_clips) == 1


# ── build_arrangement_from_prechop ───────────────────────────────────────────


def _write_prechop(tmp_path: Path, *, beats_per_bar: int = 4) -> None:
    """Drop a minimal prechop_manifest.json under tmp_path."""
    data = {
        "bpm": 120.0,
        "bars": 4,
        "beats_per_bar": beats_per_bar,
        "first_downbeat_sec": 2.0,
        "musical_bar_1_chunk_index": 1,
        "stems": {
            "drums": {
                "dir": "drums_prechop",
                "chunks": [
                    {
                        "file": "drums_prechop/drums_chunk_001.wav",
                        "stem": "drums",
                        "chunk_index": 1,
                        "bars": 4,
                        "total_sec": 8.0,
                    },
                    {
                        "file": "drums_prechop/drums_chunk_002.wav",
                        "stem": "drums",
                        "chunk_index": 2,
                        "bars": 4,
                        "total_sec": 8.0,
                    },
                ],
            },
            "vocals": {
                "dir": "vocals_prechop",
                "chunks": [
                    {
                        "file": "vocals_prechop/vocals_chunk_001.wav",
                        "stem": "vocals",
                        "chunk_index": 1,
                        "bars": 4,
                        "total_sec": 8.0,
                    },
                ],
            },
        },
    }
    (tmp_path / "prechop_manifest.json").write_text(json.dumps(data))


def test_build_arrangement_from_prechop_flattens_nested_chunks(tmp_path: Path):
    """Each prechop chunk becomes one ArrangementChunk with renamed stem."""
    _write_prechop(tmp_path)
    am = build_arrangement_from_prechop(
        slug="def",
        forge_dir=tmp_path,
        source_audio="/path/to/src.wav",
        bpm=120.0,
        first_downbeat_sec=2.0,
    )
    assert len(am.chunks) == 3  # 2 drum + 1 vocal
    drums = [c for c in am.chunks if c.stem == "drum"]
    vocals = [c for c in am.chunks if c.stem == "vocal"]
    assert len(drums) == 2
    assert len(vocals) == 1
    # Schema literals are singular, prechop uses plural — rename verified.
    assert all(c.stem in {"drum", "bass", "vocal", "other"} for c in am.chunks)
    # Audio path is preserved as a relative path under the forge dir.
    assert drums[0].audio_path == "drums_prechop/drums_chunk_001.wav"


def test_build_arrangement_from_prechop_bar_position_math(tmp_path: Path):
    """bar_position derives from (chunk_index - musical_bar_1) * bars; the
    source_position_sec then projects onto first_downbeat_sec + bar grid."""
    _write_prechop(tmp_path)  # bpm=120, beats_per_bar=4 → bar_period_sec = 2.0
    am = build_arrangement_from_prechop(
        slug="def",
        forge_dir=tmp_path,
        source_audio="/x.wav",
        bpm=120.0,
        first_downbeat_sec=2.0,
    )
    drums = sorted([c for c in am.chunks if c.stem == "drum"], key=lambda c: c.bar_position)
    # Chunk 1 → bar_position 0, source_position_sec = first_downbeat_sec.
    assert drums[0].bar_position == 0
    assert drums[0].source_position_sec == pytest.approx(2.0)
    # Chunk 2 → bar_position 4 (one chunk-of-4-bars later),
    # source_position_sec = first_downbeat + 4 * 2.0 = 10.0.
    assert drums[1].bar_position == 4
    assert drums[1].source_position_sec == pytest.approx(10.0)


def test_build_arrangement_from_prechop_missing_file_returns_empty(tmp_path: Path):
    """No prechop on disk → fall back to empty arrangement (no crash)."""
    am = build_arrangement_from_prechop(
        slug="def",
        forge_dir=tmp_path,
        source_audio="/x.wav",
        bpm=120.0,
        first_downbeat_sec=0.0,
    )
    assert am.chunks == []
    # Hash should still match the empty-chunks canonical form.
    assert am.manifest_hash == compute_manifest_hash([])


def test_build_arrangement_from_prechop_corrupt_json_returns_empty(tmp_path: Path):
    """Malformed prechop JSON → fall back to empty arrangement (no crash)."""
    (tmp_path / "prechop_manifest.json").write_text("{not-json")
    am = build_arrangement_from_prechop(
        slug="def",
        forge_dir=tmp_path,
        source_audio="/x.wav",
        bpm=120.0,
        first_downbeat_sec=0.0,
    )
    assert am.chunks == []


def test_build_arrangement_from_prechop_chunks_sort_deterministically(tmp_path: Path):
    """Two independent runs of the converter on identical input produce the
    same manifest_hash. Hash depends on chunk ordering, so the function
    must sort deterministically."""
    _write_prechop(tmp_path)
    am1 = build_arrangement_from_prechop(
        slug="def",
        forge_dir=tmp_path,
        source_audio="/x.wav",
        bpm=120.0,
        first_downbeat_sec=2.0,
    )
    am2 = build_arrangement_from_prechop(
        slug="def",
        forge_dir=tmp_path,
        source_audio="/x.wav",
        bpm=120.0,
        first_downbeat_sec=2.0,
    )
    assert am1.manifest_hash == am2.manifest_hash
