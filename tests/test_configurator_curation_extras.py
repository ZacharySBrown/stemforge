"""Curation extras tests (Phase 1.5 bridge).

Covers the new ``POST /curations/{name}/rename`` + ``POST /curations/
active/close`` endpoints, plus the schema fix that makes ``color_palette``
and ``label`` persist on ``PATCH /curations/{name}/target``.
"""

from __future__ import annotations

import asyncio
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
from stemforge.configurator.schemas import Curation, Group, Pad, Target
from stemforge.configurator.server import create_app


# ── Fixtures (mirror Phase 1B layout) ────────────────────────────────────────


@pytest.fixture
def configurator_paths(tmp_path: Path) -> dict[str, Path]:
    curations_dir = tmp_path / "curations"
    curations_dir.mkdir()
    processed_dir = tmp_path / "processed"
    processed_dir.mkdir()
    state_path = tmp_path / ".stemforge_state.json"
    static_dir = tmp_path / "static"
    return {
        "curations_dir": curations_dir,
        "processed_dir": processed_dir,
        "state_path": state_path,
        "static_dir": static_dir,
    }


@pytest.fixture
def client(configurator_paths: dict[str, Path]) -> TestClient:
    app = create_app(
        static_dir=configurator_paths["static_dir"],
        curations_dir=configurator_paths["curations_dir"],
        state_path=configurator_paths["state_path"],
        processed_dir=configurator_paths["processed_dir"],
    )
    return TestClient(app)


def _seed_curation(curations_dir: Path, name: str) -> Curation:
    """Drop a minimal curation YAML for round-trip tests."""
    now = datetime.now(UTC)
    target = Target()
    groups: dict[str, Group] = {}
    for letter in ["A", "B", "C", "D"]:
        pads = [Pad(pad_id=f"{letter}{i + 1:02d}") for i in range(12)]
        groups[letter] = Group(label="", template=None, pads=pads)
    curation = Curation(
        name=name,
        type="deck",
        created_at=now,
        modified_at=now,
        target=target,
        referenced_forges=[],
        groups=groups,
    )
    write_curation_atomic(curation_path(curations_dir, name), curation)
    return curation


# ── POST /curations/{name}/rename ────────────────────────────────────────────


def test_rename_curation_roundtrip(client: TestClient, configurator_paths: dict[str, Path]) -> None:
    _seed_curation(configurator_paths["curations_dir"], "original")
    r = client.post("/curations/original/rename", json={"new_name": "fancy_name"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["name"] == "fancy_name"
    # Old file gone; new file present and parses cleanly.
    assert not curation_path(configurator_paths["curations_dir"], "original").is_file()
    new_path = curation_path(configurator_paths["curations_dir"], "fancy_name")
    assert new_path.is_file()
    on_disk = read_curation(new_path)
    assert on_disk.name == "fancy_name"


def test_rename_curation_to_existing_returns_409(
    client: TestClient, configurator_paths: dict[str, Path]
) -> None:
    _seed_curation(configurator_paths["curations_dir"], "src")
    _seed_curation(configurator_paths["curations_dir"], "dst")
    r = client.post("/curations/src/rename", json={"new_name": "dst"})
    assert r.status_code == 409
    # Both originals must still be on disk.
    assert curation_path(configurator_paths["curations_dir"], "src").is_file()
    assert curation_path(configurator_paths["curations_dir"], "dst").is_file()


def test_rename_curation_to_invalid_name_returns_400(
    client: TestClient, configurator_paths: dict[str, Path]
) -> None:
    _seed_curation(configurator_paths["curations_dir"], "valid")
    r = client.post("/curations/valid/rename", json={"new_name": "../escape"})
    assert r.status_code == 400
    # File untouched.
    assert curation_path(configurator_paths["curations_dir"], "valid").is_file()


def test_rename_unknown_curation_returns_404(client: TestClient) -> None:
    r = client.post("/curations/no-such/rename", json={"new_name": "whatever"})
    assert r.status_code == 404


def test_rename_updates_active_curation_state(
    client: TestClient, configurator_paths: dict[str, Path]
) -> None:
    """Renaming the active curation rewrites .stemforge_state.json."""
    _seed_curation(configurator_paths["curations_dir"], "old_name")
    als = "/Users/zak/Music/Ableton/Set.als"
    client.post("/curations/old_name/open", json={"als_path": als})
    r = client.post("/curations/old_name/rename", json={"new_name": "new_name"})
    assert r.status_code == 200
    # State file points at the new name now.
    state_data = json.loads(configurator_paths["state_path"].read_text())
    assert state_data["active_curations"][als] == "new_name"


def test_rename_idempotent_when_new_name_equals_old(
    client: TestClient, configurator_paths: dict[str, Path]
) -> None:
    """No-op rename: same-name request must still succeed."""
    _seed_curation(configurator_paths["curations_dir"], "stay")
    r = client.post("/curations/stay/rename", json={"new_name": "stay"})
    assert r.status_code == 200
    assert r.json()["name"] == "stay"
    assert curation_path(configurator_paths["curations_dir"], "stay").is_file()


def test_rename_broadcasts_sse(configurator_paths: dict[str, Path]) -> None:
    """Mutation triggers ``state`` SSE event (broker-direct test)."""
    from stemforge.configurator.intents import (
        RenameCurationBody,
        handle_rename_curation,
    )
    from stemforge.configurator.state import AppState

    _seed_curation(configurator_paths["curations_dir"], "from")
    state = AppState()
    state.curations_dir = configurator_paths["curations_dir"]
    state.state_path = configurator_paths["state_path"]

    async def _drive() -> list:
        q = state.subscribe()
        try:
            await handle_rename_curation(state, "from", RenameCurationBody(new_name="to"))
            collected: list = []
            while not q.empty():
                collected.append(q.get_nowait())
            return collected
        finally:
            state.unsubscribe(q)

    events = asyncio.run(_drive())
    state_events = [e for e in events if e.event == "state"]
    assert state_events, f"no state events; got {[e.event for e in events]}"
    payload = state_events[-1].data
    assert payload.get("kind") == "curations"
    assert "to" in payload["curations"]


# ── POST /curations/active/close ─────────────────────────────────────────────


def test_close_active_curation_clears_state(
    client: TestClient, configurator_paths: dict[str, Path]
) -> None:
    _seed_curation(configurator_paths["curations_dir"], "live")
    als = "/tmp/x.als"
    client.post("/curations/live/open", json={"als_path": als})
    # Sanity: it's active before close.
    state_before = json.loads(configurator_paths["state_path"].read_text())
    assert state_before["active_curations"][als] == "live"

    r = client.post("/curations/active/close", json={"als_path": als})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["als_path"] == als
    # State file no longer has an active for that als path.
    state_after = json.loads(configurator_paths["state_path"].read_text())
    assert als not in state_after["active_curations"]


def test_close_active_curation_idempotent_when_no_active(
    client: TestClient, configurator_paths: dict[str, Path]
) -> None:
    """No active to close is a no-op — must still return 200."""
    r = client.post("/curations/active/close", json={"als_path": "/never.als"})
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_close_broadcasts_sse(configurator_paths: dict[str, Path]) -> None:
    from stemforge.configurator.intents import (
        CloseActiveCurationBody,
        handle_close_active_curation,
    )
    from stemforge.configurator.state import (
        AppState,
        set_active_curation,
    )

    _seed_curation(configurator_paths["curations_dir"], "broadcast_close")
    state = AppState()
    state.curations_dir = configurator_paths["curations_dir"]
    state.state_path = configurator_paths["state_path"]
    set_active_curation("/tmp/y.als", "broadcast_close", state.state_path)

    async def _drive() -> list:
        q = state.subscribe()
        try:
            await handle_close_active_curation(
                state, CloseActiveCurationBody(als_path="/tmp/y.als")
            )
            collected: list = []
            while not q.empty():
                collected.append(q.get_nowait())
            return collected
        finally:
            state.unsubscribe(q)

    events = asyncio.run(_drive())
    state_events = [e for e in events if e.event == "state"]
    assert state_events, "expected state event on close"


# ── PATCH /curations/{name}/target — color_palette + label persistence ──────


def test_patch_target_persists_color_palette_and_label(
    client: TestClient, configurator_paths: dict[str, Path]
) -> None:
    """Phase 1.5 schema fix: color_palette + label round-trip via the API."""
    _seed_curation(configurator_paths["curations_dir"], "palette_test")
    palette = ["#ff0000", "#00ff00", "#0000ff"]
    r = client.patch(
        "/curations/palette_test/target",
        json={"color_palette": palette, "label": "Studio EP-133"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    # Target.label is now first-class.
    assert body["target"]["label"] == "Studio EP-133"
    # color_palette lives on the curation root.
    assert body["color_palette"] == palette

    # Round-trip via GET — confirm persistence on disk too.
    r2 = client.get("/curations/palette_test")
    assert r2.status_code == 200
    body2 = r2.json()
    assert body2["target"]["label"] == "Studio EP-133"
    assert body2["color_palette"] == palette

    # And via direct file read.
    on_disk = read_curation(curation_path(configurator_paths["curations_dir"], "palette_test"))
    assert on_disk.target.label == "Studio EP-133"
    assert on_disk.color_palette == palette


def test_patch_target_color_palette_alone_preserves_label(
    client: TestClient, configurator_paths: dict[str, Path]
) -> None:
    """Setting one slot doesn't clobber a previously-set sibling."""
    _seed_curation(configurator_paths["curations_dir"], "preserve_test")
    client.patch(
        "/curations/preserve_test/target",
        json={"label": "First Label"},
    )
    client.patch(
        "/curations/preserve_test/target",
        json={"color_palette": ["#abcdef"]},
    )
    r = client.get("/curations/preserve_test")
    body = r.json()
    assert body["target"]["label"] == "First Label"
    assert body["color_palette"] == ["#abcdef"]


def test_patch_target_label_lands_on_target_not_just_first_group(
    client: TestClient, configurator_paths: dict[str, Path]
) -> None:
    """Phase 1.5 promotes label to Target. Group A mirroring continues for compat."""
    _seed_curation(configurator_paths["curations_dir"], "label_target")
    r = client.patch(
        "/curations/label_target/target",
        json={"label": "Performance Rig"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["target"]["label"] == "Performance Rig"
    # Legacy mirroring still in place — Phase 1B readers keyed off groups.A.label.
    assert body["groups"]["A"]["label"] == "Performance Rig"


# ── Sanity: existing /curations endpoints unaffected ────────────────────────


def test_existing_curations_routes_still_present(client: TestClient) -> None:
    """Smoke test: GET /curations returns the wrapped index, not a 404."""
    r = client.get("/curations")
    assert r.status_code == 200
    body = r.json()
    assert "curations" in body
    assert "active_curations" in body


@pytest.mark.parametrize(
    "endpoint",
    [
        "/forges",
        "/curations",
    ],
)
def test_index_endpoints_return_dict(client: TestClient, endpoint: str) -> None:
    """Both index endpoints emit a top-level dict, not a bare array."""
    r = client.get(endpoint)
    assert r.status_code == 200
    assert isinstance(r.json(), dict)
