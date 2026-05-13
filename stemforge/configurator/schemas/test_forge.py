"""Round-trip + manifest_hash recomputation tests for forge schemas."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from stemforge.configurator.schemas import (
    ArrangementManifest,
    ForgeClip,
    ForgeManifest,
)

FORGE_DIR = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "forges"


def _canon_hash(items: list[dict]) -> str:
    canon = json.dumps(items, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


@pytest.mark.parametrize(
    "forge_name",
    sorted(d.name for d in FORGE_DIR.iterdir() if d.is_dir()),
)
def test_fixture_auto_curation_round_trips(forge_name: str) -> None:
    path = FORGE_DIR / forge_name / "auto_curation_manifest.json"
    data = json.loads(path.read_text())
    fm = ForgeManifest(**data)
    assert fm.forge_slug == forge_name
    redumped = fm.model_dump(mode="json")
    assert ForgeManifest(**redumped) == fm


@pytest.mark.parametrize(
    "forge_name",
    sorted(d.name for d in FORGE_DIR.iterdir() if d.is_dir()),
)
def test_fixture_arrangement_round_trips(forge_name: str) -> None:
    path = FORGE_DIR / forge_name / "arrangement_manifest.json"
    data = json.loads(path.read_text())
    am = ArrangementManifest(**data)
    assert am.forge_slug == forge_name
    redumped = am.model_dump(mode="json")
    assert ArrangementManifest(**redumped) == am


@pytest.mark.parametrize(
    "forge_name",
    sorted(d.name for d in FORGE_DIR.iterdir() if d.is_dir()),
)
def test_manifest_hash_recomputes_correctly(forge_name: str) -> None:
    """The committed manifest_hash equals SHA-256 of the canonical clips array."""
    path = FORGE_DIR / forge_name / "auto_curation_manifest.json"
    data = json.loads(path.read_text())
    expected = _canon_hash(data["clips"])
    assert data["manifest_hash"] == expected, (
        f"{path} has stale manifest_hash; expected {expected}, got {data['manifest_hash']}"
    )


def test_forge_clip_extra_rejected() -> None:
    with pytest.raises(ValidationError):
        ForgeClip(
            clip_id="x",
            audio_path="curated_audio/x.wav",
            stem="drum",
            source_bar_range=(0, 4),
            duration_bars=4,
            tags=[],
            bogus=1,
        )


def test_forge_manifest_requires_positive_bpm() -> None:
    with pytest.raises(ValidationError):
        ForgeManifest(
            forge_slug="x",
            source_audio="/tmp/x.wav",
            bpm=0.0,
            first_downbeat_sec=0.0,
            manifest_hash="0" * 64,
            clips=[],
        )


def test_forge_clip_stem_literal_enforced() -> None:
    with pytest.raises(ValidationError):
        ForgeClip(
            clip_id="x",
            audio_path="curated_audio/x.wav",
            stem="kick",  # not in the literal set
            source_bar_range=(0, 4),
            duration_bars=4,
        )
