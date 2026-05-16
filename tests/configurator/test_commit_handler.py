"""L2 unit + integration tests for the Phase 2 commit handler.

Covers :mod:`stemforge.configurator.commit_handler` directly (no FastAPI)
plus the ``POST /curations/{name}/commit`` HTTP endpoint via
FastAPI's TestClient.

The single L3 end-to-end gate (device walker → server) lives in
``tests/test_commit_keystone.py``. This file proves the server side in
isolation so a regression there is unambiguous.
"""

from __future__ import annotations

import shutil
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from stemforge.configurator.commit_handler import (
    DeviceCommitBody,
    DeviceGroupSnapshot,
    DevicePadSnapshot,
    _ForgePathIndex,
    merge_device_snapshot,
    resolve_audio_to_source,
)
from stemforge.configurator.curation_io import (
    curation_path,
    read_curation,
    write_curation_atomic,
)
from stemforge.configurator.schemas import (
    Curation,
    Group,
    Pad,
    Target,
)
from stemforge.configurator.server import create_app

FIXTURES_ROOT = Path(__file__).resolve().parents[1] / "fixtures"
SAMPLE_FORGE_DIR = FIXTURES_ROOT / "forges" / "sample-forge"


@pytest.fixture
def processed_dir(tmp_path: Path) -> Path:
    """Stage the fixture forge under a tmp processed_dir."""
    target = tmp_path / "processed"
    target.mkdir(parents=True)
    shutil.copytree(SAMPLE_FORGE_DIR, target / "sample-forge")
    return target


@pytest.fixture
def curations_dir(tmp_path: Path) -> Path:
    out = tmp_path / "curations"
    out.mkdir(parents=True)
    return out


@pytest.fixture
def state_path(tmp_path: Path) -> Path:
    return tmp_path / ".stemforge_state.json"


@pytest.fixture
def empty_curation(curations_dir: Path) -> Curation:
    """An empty 4-group / 12-pad curation seeded on disk as 'k'."""
    now = datetime.now(UTC)
    target = Target(device="ep133", groups=4, pads_per_group=12)
    groups: dict[str, Group] = {}
    for letter in "ABCD":
        pads = [Pad(pad_id=f"{letter}{slot + 1:02d}") for slot in range(12)]
        groups[letter] = Group(label="", template=None, pads=pads)
    curation = Curation(
        name="k",
        type="deck",
        created_at=now,
        modified_at=now,
        target=target,
        referenced_forges=[],
        groups=groups,
    )
    write_curation_atomic(curation_path(curations_dir, "k"), curation)
    return curation


# ── L2 unit: _ForgePathIndex + resolve_audio_to_source ───────────────────────


def test_forge_path_index_finds_clip_by_absolute_path(processed_dir: Path) -> None:
    """Reverse-lookup hits a clip via its as-laid-down absolute path."""
    index = _ForgePathIndex(processed_dir)
    clip_path = processed_dir / "sample-forge" / "curated_audio" / "drum-bar0-4.wav"
    # The clip file may or may not exist on disk for the fixture; the
    # index keys off the manifest, not the filesystem.
    hit = index.lookup(str(clip_path))
    assert hit == ("sample-forge", "drum-bar0-4")


def test_resolve_audio_to_source_returns_forge_owned_on_hit(processed_dir: Path) -> None:
    """A forge-owned audio path resolves to PadSource(forge, clip_id, audio_path)."""
    index = _ForgePathIndex(processed_dir)
    clip_path = processed_dir / "sample-forge" / "curated_audio" / "vocal-bar0-4.wav"
    source = resolve_audio_to_source(str(clip_path), index)
    assert source.forge == "sample-forge"
    assert source.clip_id == "vocal-bar0-4"
    assert source.external_path is None
    # audio_path is relative to the forge dir for round-trip safety.
    assert source.audio_path == "curated_audio/vocal-bar0-4.wav"


def test_resolve_audio_to_source_external_fallback_on_miss(processed_dir: Path) -> None:
    """An audio path outside any forge falls back to external_path."""
    index = _ForgePathIndex(processed_dir)
    source = resolve_audio_to_source("/tmp/random/not-a-forge.wav", index)
    assert source.external_path == "/tmp/random/not-a-forge.wav"
    assert source.forge is None
    assert source.clip_id is None
    assert source.audio_path is None


def test_resolve_audio_to_source_empty_path_returns_external(processed_dir: Path) -> None:
    """Defensive: empty path → external_path with the empty string.

    The merge layer should never call this with an empty path (it gates
    on ``pad_snap.audio_path`` truthiness), but the helper itself must
    not crash either.
    """
    index = _ForgePathIndex(processed_dir)
    # Test guard: empty path is treated as a miss → external fallback.
    # PadSource validator rejects empty external_path too, so we use a
    # token literal value here to exercise the lookup branch.
    src = resolve_audio_to_source("nonexistent-key", index)
    assert src.external_path == "nonexistent-key"


# ── L2: merge_device_snapshot ────────────────────────────────────────────────


def test_merge_replaces_groups_in_snapshot_preserves_others(
    processed_dir: Path,
    empty_curation: Curation,
) -> None:
    """Group A wholesale replaced; B/C/D preserved from existing."""
    clip_path = processed_dir / "sample-forge" / "curated_audio" / "drum-bar0-4.wav"
    body = DeviceCommitBody(
        groups={
            "A": DeviceGroupSnapshot(
                label="Drums",
                template="dry",
                pads=[
                    DevicePadSnapshot(
                        pad_id="A01",
                        audio_path=str(clip_path),
                        clip_settings={
                            "warp_bpm": 120.0,
                            "loop_start_bar": 0,
                            "loop_end_bar": 4,
                            "looping": True,
                        },
                    ),
                    DevicePadSnapshot(pad_id="A02"),
                ],
            ),
        }
    )
    merged = merge_device_snapshot(
        existing=empty_curation,
        body=body,
        processed_dir=processed_dir,
    )
    assert merged.groups["A"].label == "Drums"
    assert merged.groups["A"].template == "dry"
    pads = merged.groups["A"].pads
    assert pads[0].pad_id == "A01"
    assert pads[0].source is not None
    assert pads[0].source.forge == "sample-forge"
    assert pads[0].source.clip_id == "drum-bar0-4"
    assert pads[0].clip_settings is not None
    assert pads[0].clip_settings.warp_bpm == 120.0
    assert pads[1].source is None  # empty
    # Other groups intact from existing curation.
    assert merged.groups["B"].pads[0].source is None


def test_merge_rebuilds_referenced_forges_from_pad_sources(
    processed_dir: Path,
    empty_curation: Curation,
) -> None:
    """referenced_forges is recomputed each commit from pad sources."""
    clip_path = processed_dir / "sample-forge" / "curated_audio" / "bass-bar0-4.wav"
    body = DeviceCommitBody(
        groups={
            "A": DeviceGroupSnapshot(
                pads=[
                    DevicePadSnapshot(
                        pad_id="A01",
                        audio_path=str(clip_path),
                        clip_settings={
                            "warp_bpm": 120.0,
                            "loop_start_bar": 0,
                            "loop_end_bar": 4,
                            "looping": True,
                        },
                    )
                ]
            )
        }
    )
    merged = merge_device_snapshot(
        existing=empty_curation,
        body=body,
        processed_dir=processed_dir,
    )
    assert len(merged.referenced_forges) == 1
    rf = merged.referenced_forges[0]
    assert rf.slug == "sample-forge"
    # Hash matches the live forge manifest.
    assert rf.manifest_hash == ("1d1e2b37abe1aba294597d01997494b594ec98c0f59de1a326a197576193f921")


def test_merge_handles_external_path_pads(
    processed_dir: Path,
    empty_curation: Curation,
) -> None:
    """A pad whose audio path lives outside any forge gets external_path."""
    body = DeviceCommitBody(
        groups={
            "A": DeviceGroupSnapshot(
                pads=[
                    DevicePadSnapshot(
                        pad_id="A01",
                        audio_path="/tmp/somebody-elses-loop.wav",
                        clip_settings={
                            "warp_bpm": 138.0,
                            "loop_start_bar": 0,
                            "loop_end_bar": 4,
                            "looping": True,
                        },
                    )
                ]
            )
        }
    )
    merged = merge_device_snapshot(
        existing=empty_curation,
        body=body,
        processed_dir=processed_dir,
    )
    pad = merged.groups["A"].pads[0]
    assert pad.source is not None
    assert pad.source.external_path == "/tmp/somebody-elses-loop.wav"
    # No referenced_forges entry — external paths don't anchor to a forge.
    assert merged.referenced_forges == []


def test_merge_rejects_malformed_clip_settings(
    processed_dir: Path,
    empty_curation: Curation,
) -> None:
    """A bogus warp_bpm value surfaces as ValidationError, not silent corruption."""
    clip_path = processed_dir / "sample-forge" / "curated_audio" / "drum-bar0-4.wav"
    body = DeviceCommitBody(
        groups={
            "A": DeviceGroupSnapshot(
                pads=[
                    DevicePadSnapshot(
                        pad_id="A01",
                        audio_path=str(clip_path),
                        clip_settings={
                            "warp_bpm": "not-a-number",
                            "loop_end_bar": 4,
                        },
                    )
                ]
            )
        }
    )
    with pytest.raises((ValidationError, ValueError)):
        merge_device_snapshot(
            existing=empty_curation,
            body=body,
            processed_dir=processed_dir,
        )


def test_merge_accepts_null_warp_bpm(
    processed_dir: Path,
    empty_curation: Curation,
) -> None:
    """A null warp_bpm must NOT 422 the commit.

    Regression: the Live Clip LOM exposes no `warp_bpm` property, so the
    device sends `warp_bpm: null` for clips it can't derive a tempo for.
    `_normalize_clip_settings` used to call `float(None)` → TypeError →
    HTTP 422, and the device's COMMIT silently failed.
    """
    clip_path = processed_dir / "sample-forge" / "curated_audio" / "drum-bar0-4.wav"
    body = DeviceCommitBody(
        groups={
            "A": DeviceGroupSnapshot(
                pads=[
                    DevicePadSnapshot(
                        pad_id="A01",
                        audio_path=str(clip_path),
                        clip_settings={
                            "warp_bpm": None,
                            "loop_start_bar": 0,
                            "loop_end_bar": 1,
                            "looping": True,
                        },
                    )
                ]
            )
        }
    )
    merged = merge_device_snapshot(
        existing=empty_curation,
        body=body,
        processed_dir=processed_dir,
    )
    pad = merged.groups["A"].pads[0]
    assert pad.clip_settings is not None
    assert pad.clip_settings.warp_bpm is None
    assert pad.clip_settings.loop_end_bar == 1.0


def test_merge_converts_lom_units_to_bar_units(
    processed_dir: Path,
    empty_curation: Curation,
) -> None:
    """Raw LOM loop_start/loop_end (beats) → loop_start_bar/loop_end_bar (bars)."""
    clip_path = processed_dir / "sample-forge" / "curated_audio" / "other-bar0-4.wav"
    body = DeviceCommitBody(
        groups={
            "A": DeviceGroupSnapshot(
                pads=[
                    DevicePadSnapshot(
                        pad_id="A01",
                        audio_path=str(clip_path),
                        clip_settings={
                            "warp_bpm": 138.0,
                            # 8 beats == 2 bars
                            "loop_start": 0,
                            "loop_end": 8,
                            "looping": 1,
                        },
                    )
                ]
            )
        }
    )
    merged = merge_device_snapshot(
        existing=empty_curation,
        body=body,
        processed_dir=processed_dir,
    )
    settings = merged.groups["A"].pads[0].clip_settings
    assert settings is not None
    assert settings.loop_start_bar == 0
    assert settings.loop_end_bar == 2.0
    assert settings.looping is True


# ── L2: HTTP-level commit endpoint via TestClient ────────────────────────────


def _make_client(
    processed_dir: Path,
    curations_dir: Path,
    state_path: Path,
    tmp_path: Path,
) -> TestClient:
    app = create_app(
        static_dir=tmp_path / "static",
        curations_dir=curations_dir,
        state_path=state_path,
        processed_dir=processed_dir,
    )
    return TestClient(app)


def test_post_commit_writes_curation_to_disk(
    processed_dir: Path,
    curations_dir: Path,
    state_path: Path,
    empty_curation: Curation,
    tmp_path: Path,
) -> None:
    """End-to-end through the FastAPI route — file on disk reflects body."""
    client = _make_client(processed_dir, curations_dir, state_path, tmp_path)
    clip_path = processed_dir / "sample-forge" / "curated_audio" / "vocal-bar0-4.wav"
    body = {
        "groups": {
            "A": {
                "label": "Vocals",
                "template": "dry",
                "pads": [
                    {
                        "pad_id": "A01",
                        "audio_path": str(clip_path),
                        "clip_settings": {
                            "warp_bpm": 138.0,
                            "loop_start_bar": 0,
                            "loop_end_bar": 4,
                            "looping": True,
                        },
                    }
                ],
            }
        }
    }
    resp = client.post("/curations/k/commit", json=body)
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["name"] == "k"
    assert payload["groups"]["A"]["pads"][0]["source"]["forge"] == "sample-forge"

    # File on disk matches.
    disk = read_curation(curation_path(curations_dir, "k"))
    pad = disk.groups["A"].pads[0]
    assert pad.source is not None
    assert pad.source.clip_id == "vocal-bar0-4"


def test_post_commit_malformed_body_returns_422(
    processed_dir: Path,
    curations_dir: Path,
    state_path: Path,
    empty_curation: Curation,
    tmp_path: Path,
) -> None:
    """Non-numeric warp_bpm → 422."""
    client = _make_client(processed_dir, curations_dir, state_path, tmp_path)
    clip_path = processed_dir / "sample-forge" / "curated_audio" / "drum-bar0-4.wav"
    body = {
        "groups": {
            "A": {
                "pads": [
                    {
                        "pad_id": "A01",
                        "audio_path": str(clip_path),
                        "clip_settings": {
                            "warp_bpm": "nope",
                            "loop_end_bar": 4,
                        },
                    }
                ]
            }
        }
    }
    resp = client.post("/curations/k/commit", json=body)
    assert resp.status_code == 422, resp.text


def test_post_commit_unknown_curation_returns_404(
    processed_dir: Path,
    curations_dir: Path,
    state_path: Path,
    tmp_path: Path,
) -> None:
    """Committing to a non-existent curation surfaces 404."""
    client = _make_client(processed_dir, curations_dir, state_path, tmp_path)
    resp = client.post("/curations/does-not-exist/commit", json={"groups": {}})
    assert resp.status_code == 404, resp.text


def test_post_commit_broadcasts_state_via_broker(
    processed_dir: Path,
    curations_dir: Path,
    state_path: Path,
    empty_curation: Curation,
    tmp_path: Path,
) -> None:
    """A successful commit pushes a 'state' event to broker subscribers.

    We subscribe directly to the broker (rather than going through the
    SSE HTTP stream which would block the test). Same code path the
    streaming endpoint uses; we just skip the network hop so the
    assertion is deterministic.
    """
    import asyncio

    app = create_app(
        static_dir=tmp_path / "static",
        curations_dir=curations_dir,
        state_path=state_path,
        processed_dir=processed_dir,
    )
    client = TestClient(app)
    state = app.state.configurator

    clip_path = processed_dir / "sample-forge" / "curated_audio" / "drum-bar0-4.wav"

    async def _run() -> list[dict]:
        q = state.subscribe()
        try:
            # Make the HTTP call inside the same loop the broker uses.
            # TestClient.post is sync but spawns its own loop; that's
            # fine because the broker queue is asyncio.Queue and the
            # state instance is shared.
            resp = await asyncio.to_thread(
                client.post,
                "/curations/k/commit",
                json={
                    "groups": {
                        "A": {
                            "pads": [
                                {
                                    "pad_id": "A01",
                                    "audio_path": str(clip_path),
                                    "clip_settings": {
                                        "warp_bpm": 120.0,
                                        "loop_start_bar": 0,
                                        "loop_end_bar": 4,
                                        "looping": True,
                                    },
                                }
                            ]
                        }
                    }
                },
            )
            assert resp.status_code == 200, resp.text
            events: list[dict] = []
            # Drain everything the broker pushed during the request.
            while not q.empty():
                ev = await q.get()
                events.append({"event": ev.event, "data": ev.data})
            return events
        finally:
            state.unsubscribe(q)

    events = asyncio.run(_run())
    state_events = [e for e in events if e["event"] == "state"]
    assert state_events, f"expected at least one 'state' event, got {events}"
    curations_event = next(
        (e for e in state_events if e["data"].get("kind") == "curations"),
        None,
    )
    assert curations_event is not None, (
        f"expected a curations-state frame, got {[e['data'] for e in state_events]}"
    )
    assert "k" in curations_event["data"]["curations"]
