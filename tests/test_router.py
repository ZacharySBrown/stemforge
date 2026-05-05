"""Tests for stemforge.router — distributing bounce outputs into the library."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from stemforge.manifest_schema import (
    BatchManifest,
    SampleMeta,
    write_batch,
    write_sidecar,
)
from stemforge.router import (
    INCOMING,
    LOOP_BY_STEM,
    build_filename,
    classify,
    derive_song_slug,
    next_index,
    route_export_dir,
    to_slug,
)


def _write_wav(path: Path, *, seconds: float = 0.1, sr: int = 44100, freq: float = 440.0):
    t = np.linspace(0.0, seconds, int(sr * seconds), endpoint=False, dtype=np.float32)
    audio = 0.1 * np.sin(2 * np.pi * freq * t)
    sf.write(str(path), audio, sr, subtype="FLOAT")


def _make_export_dir(tmp_path: Path, samples: list[tuple[str, SampleMeta, float]]) -> Path:
    """Create a fake bounce dir with WAVs + sidecars + batch manifest.

    Each `samples` entry: (filename, meta, freq_hz_for_distinct_audio).
    """
    export_dir = tmp_path / "bounce_xyz"
    export_dir.mkdir()
    batch_entries: list[SampleMeta] = []
    for fname, meta, freq in samples:
        wav = export_dir / fname
        _write_wav(wav, freq=freq)
        write_sidecar(wav, meta)
        batch_entries.append(meta.model_copy(update={"file": fname}))
    write_batch(export_dir, BatchManifest(version=1, track="Test Song 01", bpm=120.0,
                                          samples=batch_entries))
    return export_dir


# ── classify ───────────────────────────────────────────────────────────────

def test_classify_oneshot_kick_by_role():
    meta = SampleMeta(name="Some Hit", playmode="oneshot", role="kick")
    assert classify(meta).subpath == "Oneshots/Kicks"


def test_classify_oneshot_snare_by_name():
    meta = SampleMeta(name="Tight Snare", playmode="oneshot", role="one_shot")
    assert classify(meta).subpath == "Oneshots/Snares"


def test_classify_oneshot_unknown_falls_to_perc():
    meta = SampleMeta(name="weird hit", playmode="oneshot")
    assert classify(meta).subpath == "Oneshots/Percussion"


def test_classify_loop_by_stem():
    meta = SampleMeta(name="anything", playmode="key", stem="bass")
    assert classify(meta) is LOOP_BY_STEM["bass"]


def test_classify_loop_by_name_when_stem_missing():
    meta = SampleMeta(name="Big Bass Loop", playmode="key")
    assert classify(meta).subpath == "Loops/Bass"


def test_classify_unknown_loop_to_incoming():
    meta = SampleMeta(name="zzz_unmatchable_blob", playmode="key")
    assert classify(meta) is INCOMING


def test_classify_vocal_oneshot_routes_to_vocals():
    meta = SampleMeta(name="vox stab", playmode="oneshot")
    assert classify(meta).subpath == "Vocals"


# ── slug + filename ────────────────────────────────────────────────────────

def test_to_slug_strips_track_numbers():
    assert to_slug("01 Hey Mami") == "hey_mami"
    assert to_slug("04 - Can I Kick It_") == "can_i_kick_it"


def test_to_slug_handles_empty():
    assert to_slug("") == "untitled"
    assert to_slug("!!!") == "untitled"


def test_build_filename_appends_bars_for_loops():
    bucket = LOOP_BY_STEM["drums"]
    assert build_filename("oohlala", bucket, 1, bars=4) == "oohlala_drumloop_4bar_001.wav"


def test_build_filename_oneshots_skip_bars():
    from stemforge.router import Bucket
    bucket = Bucket("Oneshots/Kicks", "kick")
    assert build_filename("oohlala", bucket, 1, bars=0.25) == "oohlala_kick_001.wav"


def test_build_filename_skips_fractional_bars():
    bucket = LOOP_BY_STEM["bass"]
    # 1.7 bars isn't a clean musical length — skip the bar tag
    name = build_filename("oohlala", bucket, 1, bars=1.7)
    assert "bar" not in name
    assert name == "oohlala_bassloop_001.wav"


def test_next_index_starts_at_one_in_empty_dir(tmp_path):
    bucket = LOOP_BY_STEM["drums"]
    assert next_index(tmp_path / "missing", "x", bucket) == 1


def test_next_index_skips_used(tmp_path):
    bucket = LOOP_BY_STEM["drums"]
    (tmp_path / "x_drumloop_4bar_001.wav").touch()
    (tmp_path / "x_drumloop_4bar_002.wav").touch()
    (tmp_path / "x_drumloop_8bar_005.wav").touch()
    assert next_index(tmp_path, "x", bucket) == 3


# ── derive_song_slug ───────────────────────────────────────────────────────

def test_derive_song_slug_explicit_wins(tmp_path):
    batch = BatchManifest(track="Track Name")
    assert derive_song_slug(explicit="Override Me",
                            batch=batch, export_dir=tmp_path / "any") == "override_me"


def test_derive_song_slug_falls_back_to_track(tmp_path):
    batch = BatchManifest(track="01 Hey Mami")
    assert derive_song_slug(explicit=None, batch=batch,
                            export_dir=tmp_path / "any") == "hey_mami"


def test_derive_song_slug_falls_back_to_dir(tmp_path):
    assert derive_song_slug(explicit=None, batch=None,
                            export_dir=tmp_path / "Some_Bounce_dir") == "some_bounce_dir"


# ── end-to-end route ───────────────────────────────────────────────────────

def test_route_full_flow(tmp_path):
    library = tmp_path / "mus"
    export = _make_export_dir(tmp_path, [
        ("A00.wav", SampleMeta(name="Punchy Kick", playmode="oneshot", role="kick", bars=0.25), 100.0),
        ("A01.wav", SampleMeta(name="Snare Crack", playmode="oneshot", role="snare", bars=0.25), 200.0),
        ("B00.wav", SampleMeta(name="Drums Loop", playmode="key", stem="drums", bars=4.0, bpm=120.0), 300.0),
        ("C00.wav", SampleMeta(name="Bass Line", playmode="key", stem="bass", bars=4.0, bpm=120.0), 400.0),
    ])

    result = route_export_dir(export, library_root=library, song_slug="ooh la la")

    assert result.song_slug == "ooh_la_la"
    assert len(result.records) == 4
    assert not result.skipped

    # Files at their destinations with expected names
    by_bucket = {r.bucket: r.dest_wav.name for r in result.records}
    assert by_bucket["Oneshots/Kicks"] == "ooh_la_la_kick_001.wav"
    assert by_bucket["Oneshots/Snares"] == "ooh_la_la_snare_001.wav"
    assert by_bucket["Loops/Drums"] == "ooh_la_la_drumloop_4bar_001.wav"
    assert by_bucket["Loops/Bass"] == "ooh_la_la_bassloop_4bar_001.wav"

    # Sidecars travelled along (hash-named — same hash as source)
    for rec in result.records:
        sidecar = rec.dest_wav.parent / f".manifest_{rec.audio_hash}.json"
        assert sidecar.exists(), f"missing sidecar at {sidecar}"

    # Run manifest exists and lists all 4
    run_manifest = library / "Projects" / "Stems" / "ooh_la_la" / "stemforge_curation.json"
    assert run_manifest.exists()
    payload = json.loads(run_manifest.read_text())
    assert payload["song_slug"] == "ooh_la_la"
    assert len(payload["records"]) == 4
    assert payload["project_bpm"] == 120.0


def test_route_idempotent_skips_already_routed(tmp_path):
    library = tmp_path / "mus"
    export = _make_export_dir(tmp_path, [
        ("A00.wav", SampleMeta(name="Punchy Kick", playmode="oneshot", role="kick"), 100.0),
    ])

    first = route_export_dir(export, library_root=library, song_slug="x")
    second = route_export_dir(export, library_root=library, song_slug="x")

    assert len(first.records) == 1
    assert not second.records
    assert second.skipped and second.skipped[0][1] == "already_routed"


def test_route_increments_index_when_different_hash(tmp_path):
    library = tmp_path / "mus"
    # Two kicks with different audio (different freq → different hash)
    export = _make_export_dir(tmp_path, [
        ("A00.wav", SampleMeta(name="Kick A", playmode="oneshot", role="kick"), 100.0),
        ("A01.wav", SampleMeta(name="Kick B", playmode="oneshot", role="kick"), 110.0),
    ])

    result = route_export_dir(export, library_root=library, song_slug="x")
    names = sorted(r.dest_wav.name for r in result.records)
    assert names == ["x_kick_001.wav", "x_kick_002.wav"]


def test_route_unknown_lands_in_incoming(tmp_path):
    library = tmp_path / "mus"
    export = _make_export_dir(tmp_path, [
        ("A00.wav", SampleMeta(name="zzz_mystery", playmode="key"), 100.0),
    ])
    result = route_export_dir(export, library_root=library, song_slug="x")
    assert len(result.records) == 1
    assert result.records[0].bucket == "_Incoming"


def test_route_missing_batch_manifest_raises(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(FileNotFoundError):
        route_export_dir(empty, library_root=tmp_path / "mus")


def test_route_symlink_mode(tmp_path):
    library = tmp_path / "mus"
    export = _make_export_dir(tmp_path, [
        ("A00.wav", SampleMeta(name="Kick", playmode="oneshot", role="kick"), 100.0),
    ])
    result = route_export_dir(export, library_root=library, song_slug="x", copy=False)
    dest = result.records[0].dest_wav
    assert dest.is_symlink()
