"""Phase 4B — stale-detection unit + endpoint tests.

L2 (pure-function) coverage for :mod:`stemforge.configurator.stale_check`
plus an L3 round-trip through the new ``POST /curations/{name}/refresh``
endpoint and SSE state event.

Fixtures isolate ``~/stemforge/`` under ``tmp_path`` so the user's real
filesystem is never touched. Real :class:`ForgeManifest` instances are
constructed (not mocks) so the test asserts the actual hash-comparison
codepath the broadcaster runs.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from stemforge.configurator.curation_io import (
    curation_path,
    read_curation,
    write_curation_atomic,
)
from stemforge.configurator.schemas import (
    ClipSettings,
    Curation,
    ForgeClip,
    ForgeManifest,
    Group,
    Pad,
    PadSource,
    ReferencedForge,
    Target,
    compute_manifest_hash,
)
from stemforge.configurator.server import create_app
from stemforge.configurator.stale_check import (
    PadStaleEntry,
    compute_stale,
    refresh_pad_refs,
    stale_summary,
)
from stemforge.forge.manifest_io import write_auto_curation


# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def configurator_paths(tmp_path: Path) -> dict[str, Path]:
    """Provision an isolated ``~/stemforge/`` layout under ``tmp_path``."""
    curations_dir = tmp_path / "curations"
    curations_dir.mkdir()
    processed_dir = tmp_path / "processed"
    processed_dir.mkdir()
    state_path = tmp_path / ".stemforge_state.json"
    static_dir = tmp_path / "static"
    templates_dir = tmp_path / "templates"
    templates_dir.mkdir()
    return {
        "curations_dir": curations_dir,
        "processed_dir": processed_dir,
        "state_path": state_path,
        "static_dir": static_dir,
        "templates_dir": templates_dir,
    }


@pytest.fixture
def client(configurator_paths: dict[str, Path]) -> TestClient:
    app = create_app(
        static_dir=configurator_paths["static_dir"],
        curations_dir=configurator_paths["curations_dir"],
        state_path=configurator_paths["state_path"],
        processed_dir=configurator_paths["processed_dir"],
        templates_dir=configurator_paths["templates_dir"],
    )
    return TestClient(app)


# ── Helpers ─────────────────────────────────────────────────────────────────


def _build_forge_manifest(
    slug: str,
    *,
    clip_ids: tuple[str, ...] = ("clip-0", "clip-1"),
    audio_paths: dict[str, str] | None = None,
    bpm: float = 120.0,
) -> ForgeManifest:
    """Construct a :class:`ForgeManifest` with a deterministic hash."""
    audio_paths = audio_paths or {cid: f"curated_audio/{cid}.wav" for cid in clip_ids}
    clips = [
        ForgeClip(
            clip_id=cid,
            audio_path=audio_paths[cid],
            stem="drum",
            source_bar_range=(i * 4, (i + 1) * 4),
            duration_bars=4,
            tags=["loop"],
        )
        for i, cid in enumerate(clip_ids)
    ]
    return ForgeManifest(
        schema_version=1,
        forge_slug=slug,
        source_audio=f"/tmp/{slug}.wav",
        bpm=bpm,
        first_downbeat_sec=0.0,
        manifest_hash=compute_manifest_hash([c.model_dump(mode="json") for c in clips]),
        clips=clips,
    )


def _seed_forge_on_disk(
    processed_dir: Path,
    slug: str,
    *,
    clip_ids: tuple[str, ...] = ("clip-0", "clip-1"),
    audio_paths: dict[str, str] | None = None,
) -> ForgeManifest:
    """Write a real forge dir + manifest to disk, returning the manifest."""
    forge_dir = processed_dir / slug
    forge_dir.mkdir(parents=True, exist_ok=True)
    manifest = _build_forge_manifest(slug, clip_ids=clip_ids, audio_paths=audio_paths)
    write_auto_curation(forge_dir, manifest)
    # write_auto_curation recomputes the hash; load it back so we have
    # the authoritative on-disk value.
    return _build_forge_manifest(slug, clip_ids=clip_ids, audio_paths=audio_paths)


def _build_curation(
    name: str,
    *,
    forge_slug: str = "alpha",
    forge_hash: str = "deadbeef",
    pad_clip_id: str = "clip-0",
    pad_audio_path: str = "curated_audio/clip-0.wav",
) -> Curation:
    """Construct a Curation that references one forge via pad A01."""
    now = datetime.now(UTC)
    groups: dict[str, Group] = {}
    for letter in ["A", "B", "C", "D"]:
        pads = [Pad(pad_id=f"{letter}{i + 1:02d}") for i in range(12)]
        groups[letter] = Group(label="", template=None, pads=pads)
    # Place a pad sourced from the forge in slot A01.
    groups["A"].pads[0] = Pad(
        pad_id="A01",
        source=PadSource(
            forge=forge_slug,
            clip_id=pad_clip_id,
            audio_path=pad_audio_path,
        ),
        clip_settings=ClipSettings(warp_bpm=120.0, loop_end_bar=4.0),
    )
    return Curation(
        name=name,
        type="deck",
        created_at=now,
        modified_at=now,
        target=Target(),
        referenced_forges=[ReferencedForge(slug=forge_slug, manifest_hash=forge_hash)],
        groups=groups,
    )


# ── L2: compute_stale ───────────────────────────────────────────────────────


def test_compute_stale_all_fresh_returns_all_false() -> None:
    """Curation hash matches forge hash → no pad is stale."""
    forge = _build_forge_manifest("alpha")
    curation = _build_curation("c1", forge_slug="alpha", forge_hash=forge.manifest_hash)

    flags = compute_stale(curation, {"alpha": forge})

    assert flags["A01"] is False
    # Empty pads are non-stale (no source = no forge reference).
    assert flags["A02"] is False
    # Every pad in the curation is keyed.
    assert len(flags) == 12 * 4


def test_compute_stale_with_stale_forge_marks_only_those_pads() -> None:
    """Only pads sourced from the mutated forge are flagged."""
    forge = _build_forge_manifest("alpha")
    # Curation was committed against an older hash.
    curation = _build_curation("c1", forge_slug="alpha", forge_hash="old-hash-value")

    flags = compute_stale(curation, {"alpha": forge})

    assert flags["A01"] is True  # only pad sourced from alpha
    assert flags["A02"] is False
    assert flags["B01"] is False


def test_compute_stale_missing_forge_marks_dependent_pads() -> None:
    """Forge gone → pads referencing it are stale (forges map carries ``None``)."""
    curation = _build_curation("c1", forge_slug="alpha", forge_hash="any-hash")

    flags = compute_stale(curation, {"alpha": None})

    assert flags["A01"] is True
    assert flags["B02"] is False


def test_compute_stale_external_path_pad_is_never_stale() -> None:
    """A pad sourced from external_path has no forge reference; non-stale."""
    now = datetime.now(UTC)
    groups: dict[str, Group] = {}
    for letter in ["A"]:
        pads = [Pad(pad_id=f"{letter}{i + 1:02d}") for i in range(2)]
        groups[letter] = Group(label="", template=None, pads=pads)
    groups["A"].pads[0] = Pad(
        pad_id="A01",
        source=PadSource(external_path="/tmp/external.wav"),
    )
    curation = Curation(
        name="external-c1",
        type="deck",
        created_at=now,
        modified_at=now,
        target=Target(groups=1, pads_per_group=2),
        referenced_forges=[],
        groups=groups,
    )

    flags = compute_stale(curation, {})

    assert flags["A01"] is False
    assert flags["A02"] is False


# ── L2: stale_summary (broadcaster shape) ──────────────────────────────────


def test_stale_summary_emits_current_manifest_hash_when_fresh() -> None:
    forge = _build_forge_manifest("alpha")
    curation = _build_curation("c1", forge_slug="alpha", forge_hash=forge.manifest_hash)

    summary = stale_summary(curation, {"alpha": forge})

    assert isinstance(summary["A01"], PadStaleEntry)
    assert summary["A01"].stale is False
    assert summary["A01"].current_manifest_hash == forge.manifest_hash
    # Empty pads: no source = no forge ref = null current hash.
    assert summary["A02"].current_manifest_hash is None


def test_stale_summary_emits_null_when_forge_missing() -> None:
    curation = _build_curation("c1", forge_slug="alpha", forge_hash="any-hash")

    summary = stale_summary(curation, {"alpha": None})

    assert summary["A01"].stale is True
    assert summary["A01"].current_manifest_hash is None


def test_pad_stale_entry_to_dict_is_serialisable() -> None:
    """``PadStaleEntry.to_dict`` produces wire-shape; json.dumps handles it."""
    entry = PadStaleEntry(stale=True, current_manifest_hash="abc123")
    raw = json.dumps(entry.to_dict())
    decoded = json.loads(raw)
    assert decoded == {"stale": True, "current_manifest_hash": "abc123"}


# ── L2: refresh_pad_refs ────────────────────────────────────────────────────


def test_refresh_pad_refs_idempotent_when_no_change() -> None:
    forge = _build_forge_manifest("alpha")
    curation = _build_curation(
        "c1",
        forge_slug="alpha",
        forge_hash=forge.manifest_hash,
        pad_clip_id="clip-0",
        pad_audio_path="curated_audio/clip-0.wav",
    )

    once = refresh_pad_refs(curation, {"alpha": forge})
    twice = refresh_pad_refs(once, {"alpha": forge})

    assert once.referenced_forges == twice.referenced_forges
    assert once.groups["A"].pads[0].source == twice.groups["A"].pads[0].source


def test_refresh_pad_refs_rewrites_audio_path_after_reanchor() -> None:
    """A re-anchor that moves clip-0 onto a new relative path is honoured."""
    new_forge = _build_forge_manifest(
        "alpha",
        clip_ids=("clip-0", "clip-1"),
        audio_paths={
            "clip-0": "curated_audio/v2/clip-0.wav",
            "clip-1": "curated_audio/v2/clip-1.wav",
        },
    )
    curation = _build_curation(
        "c1",
        forge_slug="alpha",
        forge_hash="stale-hash",
        pad_audio_path="curated_audio/clip-0.wav",
    )

    refreshed = refresh_pad_refs(curation, {"alpha": new_forge})

    assert refreshed.groups["A"].pads[0].source is not None
    assert refreshed.groups["A"].pads[0].source.audio_path == "curated_audio/v2/clip-0.wav"
    # referenced_forges adopts the current hash so the popup stops reading stale.
    assert refreshed.referenced_forges[0].slug == "alpha"
    assert refreshed.referenced_forges[0].manifest_hash == new_forge.manifest_hash


def test_refresh_pad_refs_drops_ref_for_missing_forge() -> None:
    """Forge gone → its entry is dropped from referenced_forges."""
    curation = _build_curation("c1", forge_slug="alpha", forge_hash="hash-v1")

    refreshed = refresh_pad_refs(curation, {"alpha": None})

    # Pad source is preserved (we can't materialize a replacement), but the
    # ``referenced_forges`` slot for ``alpha`` is dropped because we have
    # no current hash to anchor against.
    assert refreshed.groups["A"].pads[0].source is not None
    assert refreshed.groups["A"].pads[0].source.forge == "alpha"
    assert refreshed.referenced_forges == []


def test_refresh_pad_refs_preserves_pad_when_clip_id_vanishes() -> None:
    """Clip removed from manifest → pad's audio_path is left untouched."""
    new_forge = _build_forge_manifest(
        "alpha",
        clip_ids=("clip-1",),  # clip-0 dropped
    )
    curation = _build_curation(
        "c1",
        forge_slug="alpha",
        forge_hash="hash-v1",
        pad_clip_id="clip-0",
        pad_audio_path="curated_audio/clip-0.wav",
    )

    refreshed = refresh_pad_refs(curation, {"alpha": new_forge})

    # audio_path was NOT silently rewritten to clip-1's path.
    assert refreshed.groups["A"].pads[0].source is not None
    assert refreshed.groups["A"].pads[0].source.audio_path == "curated_audio/clip-0.wav"
    # The forge slug is still referenced from a pad, so referenced_forges
    # carries the current hash (even though that pad can't fully resolve).
    assert refreshed.referenced_forges[0].manifest_hash == new_forge.manifest_hash


# ── L3: POST /curations/{name}/refresh ──────────────────────────────────────


def test_refresh_endpoint_round_trip_updates_yaml(
    client: TestClient, configurator_paths: dict[str, Path]
) -> None:
    """POST /refresh writes the updated YAML and returns the new doc."""
    forge = _seed_forge_on_disk(
        configurator_paths["processed_dir"],
        "alpha",
        clip_ids=("clip-0", "clip-1"),
    )
    # Persist a curation referencing the forge AT a stale hash.
    curation = _build_curation(
        "c1",
        forge_slug="alpha",
        forge_hash="stale-snapshot-hash",
        pad_audio_path="curated_audio/clip-0.wav",
    )
    write_curation_atomic(
        curation_path(configurator_paths["curations_dir"], "c1"),
        curation,
    )

    resp = client.post("/curations/c1/refresh")
    assert resp.status_code == 200

    body = resp.json()
    refreshed_hash = body["referenced_forges"][0]["manifest_hash"]
    assert refreshed_hash == forge.manifest_hash

    # Verify YAML was rewritten on disk too.
    on_disk = read_curation(curation_path(configurator_paths["curations_dir"], "c1"))
    assert on_disk.referenced_forges[0].manifest_hash == forge.manifest_hash


def test_refresh_endpoint_404_when_curation_missing(client: TestClient) -> None:
    resp = client.post("/curations/does-not-exist/refresh")
    assert resp.status_code == 404


def test_refresh_endpoint_rejects_invalid_name(client: TestClient) -> None:
    """A reserved/dotted name should not write to disk — 4xx, not 5xx."""
    resp = client.post("/curations/.../refresh")
    # The validator either 400s on the bad name OR the curation-not-found
    # path 404s before touching disk — both are acceptable.
    assert resp.status_code in {400, 404}


def test_refresh_endpoint_idempotent_when_nothing_stale(
    client: TestClient, configurator_paths: dict[str, Path]
) -> None:
    """Two consecutive refreshes against a fresh curation yield equal pad sources."""
    forge = _seed_forge_on_disk(
        configurator_paths["processed_dir"],
        "alpha",
        clip_ids=("clip-0",),
    )
    curation = _build_curation(
        "c1",
        forge_slug="alpha",
        forge_hash=forge.manifest_hash,
    )
    write_curation_atomic(
        curation_path(configurator_paths["curations_dir"], "c1"),
        curation,
    )

    first = client.post("/curations/c1/refresh").json()
    second = client.post("/curations/c1/refresh").json()

    assert first["referenced_forges"] == second["referenced_forges"]
    assert first["groups"]["A"]["pads"][0]["source"] == second["groups"]["A"]["pads"][0]["source"]


# ── L3: SSE state event carries stale flags ─────────────────────────────────
#
# These tests exercise :meth:`AppState.broadcast_curations_state` directly
# rather than driving an end-to-end SSE stream via ``client.stream``. The
# TestClient's sync stream + sync POST combo deadlocks in pytest because
# both operations want the same event loop; calling the broadcaster
# directly hits the same code path with no transport.


def _drain_subscriber(queue) -> list[dict[str, object]]:
    """Drain a subscriber queue into a list of decoded SSE payloads."""
    import asyncio as _asyncio

    out: list[dict[str, object]] = []
    while True:
        try:
            evt = queue.get_nowait()
        except _asyncio.QueueEmpty:
            break
        if hasattr(evt, "data"):
            out.append(dict(evt.data))
        elif isinstance(evt, dict):
            out.append(evt)
    return out


def test_sse_state_event_carries_stale_by_curation_after_refresh(
    client: TestClient, configurator_paths: dict[str, Path]
) -> None:
    """After refresh, the state SSE event includes the stale_by_curation map."""
    import asyncio

    forge = _seed_forge_on_disk(
        configurator_paths["processed_dir"],
        "alpha",
        clip_ids=("clip-0",),
    )
    curation = _build_curation(
        "c1",
        forge_slug="alpha",
        forge_hash="stale-hash-before-refresh",
    )
    write_curation_atomic(
        curation_path(configurator_paths["curations_dir"], "c1"),
        curation,
    )

    # Subscribe to the broker, then drive the refresh endpoint. The
    # endpoint's broadcast lands in our queue synchronously because the
    # broker uses ``put_nowait`` per :class:`AppState.broadcast`.
    async def run() -> list[dict[str, object]]:
        app_state = client.app.state.configurator
        q = app_state.subscribe()
        try:
            refresh = client.post("/curations/c1/refresh")
            assert refresh.status_code == 200
            return _drain_subscriber(q)
        finally:
            app_state.unsubscribe(q)

    events = asyncio.run(run())

    curations_events = [e for e in events if e.get("kind") == "curations"]
    assert curations_events, "broadcast_curations_state did not fire after refresh"
    payload = curations_events[-1]
    assert "stale_by_curation" in payload
    pad_entry = payload["stale_by_curation"]["c1"]["A01"]
    # After refresh the curation is no longer stale; the current hash
    # matches the forge.
    assert pad_entry["stale"] is False
    assert pad_entry["current_manifest_hash"] == forge.manifest_hash


def test_sse_state_event_marks_pads_stale_when_forge_diverges(
    client: TestClient, configurator_paths: dict[str, Path]
) -> None:
    """Curation pinned to old hash + current forge → broadcast flags pad stale."""
    import asyncio

    forge = _seed_forge_on_disk(
        configurator_paths["processed_dir"],
        "alpha",
        clip_ids=("clip-0",),
    )
    curation = _build_curation(
        "c1",
        forge_slug="alpha",
        forge_hash="snapshot-from-yesterday",
    )
    write_curation_atomic(
        curation_path(configurator_paths["curations_dir"], "c1"),
        curation,
    )

    async def run() -> list[dict[str, object]]:
        app_state = client.app.state.configurator
        q = app_state.subscribe()
        try:
            # Direct invocation of the broadcaster — same code path the
            # mutation handlers walk, without needing a writeable endpoint.
            await app_state.broadcast_curations_state()
            return _drain_subscriber(q)
        finally:
            app_state.unsubscribe(q)

    events = asyncio.run(run())

    curations_events = [e for e in events if e.get("kind") == "curations"]
    assert curations_events, "broadcast_curations_state produced no event"
    payload = curations_events[-1]
    pad_entry = payload["stale_by_curation"]["c1"]["A01"]
    assert pad_entry["stale"] is True
    assert pad_entry["current_manifest_hash"] == forge.manifest_hash
