"""Round-trip tests for stemforge.manifest_schema.

Covers: hashing, sidecar/batch I/O, resolution chain, pad-rotation, and the
producer/consumer contract (what we write, the consumer reads back identical).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from stemforge.manifest_schema import (
    BAR_INDEX_TO_LABEL,
    BATCH_FILENAME,
    BatchManifest,
    SampleMeta,
    assign_pad_rotation,
    compute_audio_hash,
    display_name,
    find_batch,
    find_sidecar,
    load_batch,
    load_sidecar,
    lookup_in_batch,
    merge_batch_default_bpm,
    resolve_meta,
    sidecar_path_for,
    write_batch,
    write_sidecar,
)


@pytest.fixture
def wav(tmp_path: Path) -> Path:
    p = tmp_path / "loop.wav"
    p.write_bytes(b"RIFF\x00\x00\x00\x00WAVEdata-deterministic-bytes")
    return p


def test_compute_audio_hash_matches_sha256_first_16(wav: Path) -> None:
    expected = hashlib.sha256(wav.read_bytes()).hexdigest()[:16]
    assert compute_audio_hash(wav) == expected
    assert len(compute_audio_hash(wav)) == 16


def test_sidecar_path_uses_hash_filename(wav: Path) -> None:
    h = compute_audio_hash(wav)
    p = sidecar_path_for(wav)
    assert p.parent == wav.parent
    assert p.name == f".manifest_{h}.json"


def test_write_sidecar_round_trips(wav: Path) -> None:
    meta = SampleMeta(
        name="kick",
        bpm=120.0,
        playmode="oneshot",
        stem="drums",
        suggested_group="A",
        suggested_pad="7",
    )
    out = write_sidecar(wav, meta)
    assert out.exists()
    assert out == sidecar_path_for(wav)

    loaded = load_sidecar(wav)
    assert loaded is not None
    # Producer auto-fills file + audio_hash by default
    assert loaded.file == "loop.wav"
    assert loaded.audio_hash == compute_audio_hash(wav)
    # User-supplied fields preserved
    assert loaded.name == "kick"
    assert loaded.bpm == 120.0
    assert loaded.playmode == "oneshot"
    assert loaded.suggested_group == "A"
    assert loaded.suggested_pad == "7"


def test_write_sidecar_preserves_existing_hash_and_file(wav: Path) -> None:
    meta = SampleMeta(file="explicit.wav", audio_hash="deadbeefcafebabe")
    write_sidecar(wav, meta)
    # The on-disk filename uses the *real* hash (not the user's stub),
    # because that's the lookup key. But the meta's audio_hash field is preserved.
    real_hash = compute_audio_hash(wav)
    assert (wav.parent / f".manifest_{real_hash}.json").exists()
    loaded = load_sidecar(wav)
    assert loaded is not None
    assert loaded.file == "explicit.wav"
    assert loaded.audio_hash == "deadbeefcafebabe"


def test_write_batch_and_lookup_by_hash(tmp_path: Path) -> None:
    a = tmp_path / "a.wav"
    a.write_bytes(b"alpha")
    b = tmp_path / "b.wav"
    b.write_bytes(b"beta")

    batch = BatchManifest(
        track="demo",
        bpm=128.0,
        samples=[
            SampleMeta(file="a.wav", audio_hash=compute_audio_hash(a),
                       stem="drums", playmode="oneshot"),
            SampleMeta(file="b.wav", audio_hash=compute_audio_hash(b),
                       stem="bass", playmode="key"),
        ],
    )
    out = write_batch(tmp_path, batch)
    assert out == tmp_path / BATCH_FILENAME

    reloaded = load_batch(out)
    assert reloaded.bpm == 128.0
    assert len(reloaded.samples) == 2

    found_a = lookup_in_batch(reloaded, a)
    assert found_a is not None
    assert found_a.stem == "drums"


def test_lookup_in_batch_falls_back_to_filename(tmp_path: Path) -> None:
    """Batch entry with no audio_hash should still match by filename."""
    a = tmp_path / "loop.wav"
    a.write_bytes(b"x")
    batch = BatchManifest(samples=[SampleMeta(file="loop.wav", stem="drums")])
    found = lookup_in_batch(batch, a)
    assert found is not None
    assert found.stem == "drums"


def test_resolve_meta_chain_prefers_sidecar(tmp_path: Path) -> None:
    """Sidecar wins over batch when both exist."""
    wav = tmp_path / "loop.wav"
    wav.write_bytes(b"x")

    # Batch says bpm=100
    batch = BatchManifest(samples=[SampleMeta(file="loop.wav", bpm=100.0)])
    write_batch(tmp_path, batch)

    # Sidecar says bpm=140
    write_sidecar(wav, SampleMeta(bpm=140.0))

    resolved = resolve_meta(wav)
    assert resolved is not None
    assert resolved.bpm == 140.0


def test_resolve_meta_falls_through_to_batch(tmp_path: Path) -> None:
    wav = tmp_path / "loop.wav"
    wav.write_bytes(b"x")
    write_batch(tmp_path, BatchManifest(
        samples=[SampleMeta(file="loop.wav", bpm=99.0)]
    ))
    resolved = resolve_meta(wav)
    assert resolved is not None
    assert resolved.bpm == 99.0


def test_resolve_meta_returns_none_when_nothing_matches(tmp_path: Path) -> None:
    wav = tmp_path / "loop.wav"
    wav.write_bytes(b"x")
    assert resolve_meta(wav) is None


def test_explicit_manifest_override_handles_both_shapes(tmp_path: Path) -> None:
    wav = tmp_path / "loop.wav"
    wav.write_bytes(b"x")

    # Sidecar shape (single object)
    side = tmp_path / "explicit.json"
    side.write_text(json.dumps({"bpm": 77.0, "name": "explicit"}))
    r1 = resolve_meta(wav, manifest_override=side)
    assert r1 is not None
    assert r1.bpm == 77.0
    assert r1.name == "explicit"

    # Batch shape
    batch_p = tmp_path / "batch.json"
    batch_p.write_text(json.dumps({
        "samples": [{"file": "loop.wav", "bpm": 88.0}]
    }))
    r2 = resolve_meta(wav, manifest_override=batch_p)
    assert r2 is not None
    assert r2.bpm == 88.0


def test_assign_pad_rotation_bottom_up_layout() -> None:
    metas = [SampleMeta(name=f"bar_{i:02d}") for i in range(5)]
    out = assign_pad_rotation(metas, group="A")
    assert [m.suggested_pad for m in out] == [".", "0", "ENTER", "1", "2"]
    assert all(m.suggested_group == "A" for m in out)


def test_assign_pad_rotation_caps_at_12() -> None:
    metas = [SampleMeta() for _ in range(15)]
    out = assign_pad_rotation(metas)
    # First 12 get pads, overflow stays None
    pads = [m.suggested_pad for m in out]
    assert pads[:12] == list(BAR_INDEX_TO_LABEL)
    assert pads[12:] == [None, None, None]


def test_assign_pad_rotation_does_not_overwrite_existing_group() -> None:
    metas = [SampleMeta(suggested_group="C")]
    out = assign_pad_rotation(metas, group="A")
    assert out[0].suggested_group == "C"  # caller's value stands


def test_merge_batch_default_bpm_only_fills_when_absent() -> None:
    batch = BatchManifest(bpm=120.0)
    m1 = SampleMeta()
    assert merge_batch_default_bpm(m1, batch).bpm == 120.0
    m2 = SampleMeta(bpm=140.0)
    assert merge_batch_default_bpm(m2, batch).bpm == 140.0  # caller's wins


def test_display_name_truncates_and_cleans() -> None:
    assert display_name("kick_acoustic_001.wav") == "kick acoustic 00"
    assert display_name("short.wav") == "short"
    assert display_name("a_very_long_filename_that_overflows.wav", max_len=10) == "a very lon"


def test_find_helpers_return_none_when_absent(tmp_path: Path) -> None:
    wav = tmp_path / "loop.wav"
    wav.write_bytes(b"x")
    assert find_sidecar(wav) is None
    assert find_batch(wav) is None


def test_extra_fields_are_ignored_for_forward_compat(tmp_path: Path) -> None:
    """Loader must not crash if a producer adds new fields the consumer
    doesn't know about yet."""
    wav = tmp_path / "loop.wav"
    wav.write_bytes(b"x")
    side = sidecar_path_for(wav)
    side.write_text(json.dumps({"bpm": 100.0, "future_field": "ignore_me"}))
    loaded = load_sidecar(wav)
    assert loaded is not None
    assert loaded.bpm == 100.0
