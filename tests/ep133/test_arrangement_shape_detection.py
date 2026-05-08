"""Phase-2 contract: Python consumers of the arrangement dict accept both
the legacy flat shape AND the new ``{schema_version: 2, songs: [{...}]}``
wrapped shape that the M4L JS reader now emits.

The wrap is unwrapped to ``songs[0]`` at the top of ``resolve_scenes`` (and
in ``cli.export_song`` before constructing kwargs). Existing fixtures stay
flat so the byte-identity bar (`test_song_export_parity.py`) is unmoved.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from stemforge.exporters.ep133.song_resolver import (
    _unwrap_song,
    resolve_scenes,
)

FIXTURES = Path(__file__).parent / "fixtures"
SAMPLE_ARRANGEMENT = FIXTURES / "sample_arrangement.json"
SAMPLE_MANIFEST = FIXTURES / "sample_manifest.json"


@pytest.fixture
def flat_arrangement() -> dict:
    if not SAMPLE_ARRANGEMENT.exists():
        pytest.skip("sample_arrangement.json missing")
    return json.loads(SAMPLE_ARRANGEMENT.read_text())


@pytest.fixture
def manifest() -> dict:
    if not SAMPLE_MANIFEST.exists():
        pytest.skip("sample_manifest.json missing")
    return json.loads(SAMPLE_MANIFEST.read_text())


def _wrap(flat: dict) -> dict:
    """Wrap a flat arrangement in the Phase-2 schema-v2 envelope."""
    return {"schema_version": 2, "songs": [flat]}


def test_unwrap_song_returns_flat_unchanged(flat_arrangement: dict) -> None:
    assert _unwrap_song(flat_arrangement) is flat_arrangement


def test_unwrap_song_unwraps_v2_shape(flat_arrangement: dict) -> None:
    wrapped = _wrap(flat_arrangement)
    unwrapped = _unwrap_song(wrapped)
    assert unwrapped == flat_arrangement


def test_unwrap_song_handles_empty_songs() -> None:
    # Pathological: schema_version=2 but no songs[]. Treat as legacy flat
    # (since songs[] is empty, there's nothing to unwrap to).
    arrangement: dict = {"schema_version": 2, "songs": []}
    assert _unwrap_song(arrangement) is arrangement


def test_unwrap_song_handles_missing_songs_key() -> None:
    # Pure flat shape with no songs key.
    arrangement = {"tempo": 120.0, "tracks": {}, "locators": []}
    assert _unwrap_song(arrangement) is arrangement


def test_resolve_scenes_accepts_flat_arrangement(flat_arrangement: dict, manifest: dict) -> None:
    snapshots = resolve_scenes(flat_arrangement, manifest)
    assert len(snapshots) == 3


def test_resolve_scenes_accepts_wrapped_arrangement(flat_arrangement: dict, manifest: dict) -> None:
    snapshots = resolve_scenes(_wrap(flat_arrangement), manifest)
    assert len(snapshots) == 3


def test_resolve_scenes_flat_and_wrapped_match(flat_arrangement: dict, manifest: dict) -> None:
    """Flat arrangement and the same payload wrapped in songs[0] must produce
    byte-equivalent Snapshot lists at the field level the synthesizer reads."""
    flat_snaps = resolve_scenes(flat_arrangement, manifest)
    wrapped_snaps = resolve_scenes(_wrap(flat_arrangement), manifest)

    assert len(flat_snaps) == len(wrapped_snaps)
    for f, w in zip(flat_snaps, wrapped_snaps):
        assert f.locator_time_sec == w.locator_time_sec
        assert f.locator_name == w.locator_name
        for group in ("A", "B", "C", "D"):
            f_clip = f.clip_for(group)
            w_clip = w.clip_for(group)
            if f_clip is None:
                assert w_clip is None
            else:
                assert w_clip is not None
                assert f_clip.file_path == w_clip.file_path
                assert f_clip.length_sec == w_clip.length_sec
