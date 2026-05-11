"""Federated ClipIndex resolver tests."""

from __future__ import annotations

import json
import wave
from pathlib import Path

import pytest

from stemforge.exporters.ep133.clip_index import ClipIndex


def _write_wav(path: Path, *, duration_sec: float = 0.5) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    n = int(duration_sec * 22050)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(22050)
        wf.writeframes(b"\x00\x00" * n)


def _write_manifest(
    path: Path,
    *,
    entries_by_group: dict[str, list[dict]],
    bpm: float | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict = {"session_tracks": entries_by_group}
    if bpm is not None:
        payload["bpm"] = bpm
    path.write_text(json.dumps(payload))


def test_resolve_path_returns_resolved_clip(tmp_path: Path) -> None:
    wav = tmp_path / "raw.wav"
    _write_wav(wav)
    idx = ClipIndex()
    resolved = idx.resolve_path(wav)
    assert resolved.path == wav.resolve()
    assert len(resolved.audio_hash) == 16  # default HASH_LENGTH
    assert resolved.bpm is None
    assert resolved.name is None


def test_resolve_path_missing_file_raises(tmp_path: Path) -> None:
    idx = ClipIndex()
    with pytest.raises(FileNotFoundError):
        idx.resolve_path(tmp_path / "nope.wav")


def test_resolve_manifest_clip_by_slot(tmp_path: Path) -> None:
    wav = tmp_path / "song1" / "vocals_v1.wav"
    _write_wav(wav)
    manifest = tmp_path / "song1" / "manifest.json"
    _write_manifest(
        manifest,
        entries_by_group={
            "A": [{"slot": 0, "file": str(wav), "clip_length_sec": 0.5, "bpm": 92.0}]
        },
        bpm=92.0,
    )
    idx = ClipIndex.from_manifests([manifest])
    resolved = idx.resolve_manifest_clip(manifest, "slot:0", group="A")
    assert resolved.path == wav.resolve()
    assert resolved.bpm == 92.0
    assert resolved.duration_sec == 0.5


def test_resolve_manifest_clip_by_name(tmp_path: Path) -> None:
    wav = tmp_path / "song1" / "v.wav"
    _write_wav(wav)
    manifest = tmp_path / "song1" / "manifest.json"
    _write_manifest(
        manifest,
        entries_by_group={
            "A": [
                {
                    "slot": 0,
                    "file": str(wav),
                    "name": "vocals_verse_1",
                    "clip_length_sec": 0.5,
                }
            ]
        },
    )
    idx = ClipIndex.from_manifests([manifest])
    resolved = idx.resolve_manifest_clip(manifest, "name:vocals_verse_1")
    assert resolved.path == wav.resolve()
    assert resolved.name == "vocals_verse_1"


def test_bare_selector_matches_name_first(tmp_path: Path) -> None:
    wav = tmp_path / "song1" / "v.wav"
    _write_wav(wav)
    manifest = tmp_path / "song1" / "manifest.json"
    _write_manifest(
        manifest,
        entries_by_group={
            "A": [{"slot": 0, "file": str(wav), "name": "v1", "clip_length_sec": 0.5}]
        },
    )
    idx = ClipIndex.from_manifests([manifest])
    resolved = idx.resolve_manifest_clip(manifest, "v1")
    assert resolved.name == "v1"


def test_bare_selector_falls_back_to_basename(tmp_path: Path) -> None:
    wav = tmp_path / "song1" / "verse_2.wav"
    _write_wav(wav)
    manifest = tmp_path / "song1" / "manifest.json"
    _write_manifest(
        manifest,
        entries_by_group={"A": [{"slot": 0, "file": str(wav), "clip_length_sec": 0.5}]},
    )
    idx = ClipIndex.from_manifests([manifest])
    resolved = idx.resolve_manifest_clip(manifest, "verse_2")
    assert resolved.path == wav.resolve()


def test_unknown_selector_raises(tmp_path: Path) -> None:
    wav = tmp_path / "song1" / "v.wav"
    _write_wav(wav)
    manifest = tmp_path / "song1" / "manifest.json"
    _write_manifest(manifest, entries_by_group={"A": [{"slot": 0, "file": str(wav)}]})
    idx = ClipIndex.from_manifests([manifest])
    with pytest.raises(KeyError):
        idx.resolve_manifest_clip(manifest, "name:nope")


def test_relative_path_resolved_against_manifest_dir(tmp_path: Path) -> None:
    """Manifests can carry relative file paths; index resolves them
    against the manifest's parent directory."""
    wav = tmp_path / "song1" / "v.wav"
    _write_wav(wav)
    manifest = tmp_path / "song1" / "manifest.json"
    _write_manifest(
        manifest,
        entries_by_group={"A": [{"slot": 0, "file": "v.wav", "clip_length_sec": 0.5}]},
    )
    idx = ClipIndex.from_manifests([manifest])
    resolved = idx.resolve_manifest_clip(manifest, "slot:0", group="A")
    assert resolved.path == wav.resolve()


def test_audio_hash_computed_when_missing(tmp_path: Path) -> None:
    wav = tmp_path / "song1" / "v.wav"
    _write_wav(wav)
    manifest = tmp_path / "song1" / "manifest.json"
    _write_manifest(manifest, entries_by_group={"A": [{"slot": 0, "file": str(wav)}]})
    idx = ClipIndex.from_manifests([manifest])
    resolved = idx.resolve_manifest_clip(manifest, "slot:0", group="A")
    assert len(resolved.audio_hash) == 16


def test_audio_hash_from_manifest_used_when_present(tmp_path: Path) -> None:
    wav = tmp_path / "song1" / "v.wav"
    _write_wav(wav)
    manifest = tmp_path / "song1" / "manifest.json"
    _write_manifest(
        manifest,
        entries_by_group={"A": [{"slot": 0, "file": str(wav), "audio_hash": "deadbeefcafebabe"}]},
    )
    idx = ClipIndex.from_manifests([manifest])
    resolved = idx.resolve_manifest_clip(manifest, "slot:0", group="A")
    assert resolved.audio_hash == "deadbeefcafebabe"


def test_two_manifests_searchable_by_name_through_separate_calls(tmp_path: Path) -> None:
    wav1 = tmp_path / "s1" / "v.wav"
    wav2 = tmp_path / "s2" / "v.wav"
    _write_wav(wav1)
    _write_wav(wav2)
    m1 = tmp_path / "s1" / "manifest.json"
    m2 = tmp_path / "s2" / "manifest.json"
    _write_manifest(
        m1,
        entries_by_group={"A": [{"slot": 0, "file": str(wav1), "name": "verse_1"}]},
    )
    _write_manifest(
        m2,
        entries_by_group={"A": [{"slot": 0, "file": str(wav2), "name": "verse_1"}]},
    )
    idx = ClipIndex.from_manifests([m1, m2])
    a = idx.resolve_manifest_clip(m1, "name:verse_1")
    b = idx.resolve_manifest_clip(m2, "name:verse_1")
    assert a.path != b.path
    assert a.path == wav1.resolve()
    assert b.path == wav2.resolve()
