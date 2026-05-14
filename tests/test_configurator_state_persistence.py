"""Phase 4A — active-curation persistence + ``/als-opened`` bootstrap tests.

Covers:

* :func:`stemforge.configurator.state.load_state_with_recovery` — the
  startup loader that survives a corrupt state file by archiving it.
* End-to-end round-trip across every mutation surface that touches
  ``.stemforge_state.json`` (open / rename / close / delete) using the
  Phase 1B + 1.5 HTTP endpoints, asserting on-disk parity with the
  in-memory cache.
* Atomic-write robustness — a failed write leaves the previous file
  intact (no half-written truncation).
* ``POST /als-opened`` returns the cached active curation and
  broadcasts a typed ``bootstrap`` SSE event to listeners.

The pattern (tmp_path-rooted ``~/stemforge/`` layout) mirrors
``tests/test_configurator_curation_crud.py`` — same fixture shape so
this file can share the eventual ``conftest.py`` extraction.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from stemforge.configurator.curation_io import (
    curation_path,
    write_curation_atomic,
)
from stemforge.configurator.schemas import (
    Curation,
    Group,
    Pad,
    StemforgeState,
    Target,
)
from stemforge.configurator.server import create_app
from stemforge.configurator.state import (
    load_state,
    load_state_with_recovery,
    save_state,
    set_active_curation,
)


# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def configurator_paths(tmp_path: Path) -> dict[str, Path]:
    """Provision an isolated ``~/stemforge/`` layout under ``tmp_path``."""
    curations_dir = tmp_path / "curations"
    curations_dir.mkdir()
    state_path = tmp_path / ".stemforge_state.json"
    static_dir = tmp_path / "static"
    templates_dir = tmp_path / "templates"
    templates_dir.mkdir()
    return {
        "curations_dir": curations_dir,
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
        templates_dir=configurator_paths["templates_dir"],
    )
    return TestClient(app)


def _seed_curation(curations_dir: Path, name: str) -> Curation:
    """Drop a minimal Curation YAML on disk via the canonical atomic writer."""
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


# ── 1) Round-trip equality through every mutation path ────────────────────


def test_round_trip_open_rename_close_delete(
    client: TestClient, configurator_paths: dict[str, Path]
) -> None:
    """Walk the full lifecycle and assert disk + cache parity at each step.

    open → rename (active follows new name) → close → delete. After each
    step we read the on-disk state file ourselves and compare against
    what ``GET /curations`` returns (the cache-backed view).
    """
    state_path = configurator_paths["state_path"]
    curations_dir = configurator_paths["curations_dir"]
    _seed_curation(curations_dir, "alpha")
    als = "/projects/song.als"

    # 1. open — writes active map entry.
    r = client.post("/curations/alpha/open", json={"als_path": als})
    assert r.status_code == 200
    disk = json.loads(state_path.read_text())
    assert disk["active_curations"] == {als: "alpha"}
    cache_view = client.get("/curations").json()
    assert cache_view["active_curations"] == {als: "alpha"}

    # 2. rename — active map entry follows the new name.
    r = client.post("/curations/alpha/rename", json={"new_name": "alpha_v2"})
    assert r.status_code == 200, r.text
    disk = json.loads(state_path.read_text())
    assert disk["active_curations"] == {als: "alpha_v2"}
    cache_view = client.get("/curations").json()
    assert cache_view["active_curations"] == {als: "alpha_v2"}

    # 3. close — entry removed (set to None pops it).
    r = client.post("/curations/active/close", json={"als_path": als})
    assert r.status_code == 200
    disk = json.loads(state_path.read_text())
    assert disk["active_curations"] == {}
    cache_view = client.get("/curations").json()
    assert cache_view["active_curations"] == {}

    # 4. delete — file gone, no active entries to clean up either.
    r = client.delete("/curations/alpha_v2")
    assert r.status_code == 200
    disk = json.loads(state_path.read_text())
    assert disk["active_curations"] == {}
    cache_view = client.get("/curations").json()
    assert cache_view["active_curations"] == {}


# ── 2) Atomic-write — failed write leaves prior file intact ───────────────


def test_save_state_atomic_failure_preserves_old_file(tmp_path: Path) -> None:
    """If the write fails mid-flight, the original file must be untouched.

    We simulate a write failure by forcing the underlying ``os.replace``
    call to raise after a successful tempfile flush. The tempfile is
    cleaned up; the destination file (with old contents) is preserved.
    """
    state_path = tmp_path / "saved.json"
    save_state(StemforgeState(active_curations={"/a.als": "old"}), state_path)
    before = state_path.read_text()

    new_state = StemforgeState(active_curations={"/a.als": "new"})
    # Patch the replace step so it raises after the temp write completes.
    # The save_state implementation's except branch unlinks the .tmp and
    # re-raises; the destination file must still hold the OLD bytes.
    with patch("stemforge.configurator.state.os.replace", side_effect=OSError("simulated")):
        with pytest.raises(OSError, match="simulated"):
            save_state(new_state, state_path)

    after = state_path.read_text()
    assert after == before, "old file was corrupted by failed write"
    # The .tmp scratch file should have been cleaned up by the except branch.
    leftover = list(tmp_path.glob(".*tmp"))
    assert not leftover, f"leftover tmp file(s) after failed write: {leftover}"


# ── 3) Multi-path updates ─────────────────────────────────────────────────


def test_multi_als_path_updates_keep_all_entries(
    client: TestClient, configurator_paths: dict[str, Path]
) -> None:
    """Opening several .als → name pairs persists every entry independently.

    Two .als paths, two curations, then close one — the other survives.
    Validates the map-shaped storage works as advertised and that close
    of one entry doesn't accidentally clear neighbors.
    """
    state_path = configurator_paths["state_path"]
    _seed_curation(configurator_paths["curations_dir"], "alpha")
    _seed_curation(configurator_paths["curations_dir"], "beta")

    client.post("/curations/alpha/open", json={"als_path": "/p/a.als"})
    client.post("/curations/beta/open", json={"als_path": "/p/b.als"})
    disk = json.loads(state_path.read_text())
    assert disk["active_curations"] == {"/p/a.als": "alpha", "/p/b.als": "beta"}

    # Close one — the other persists.
    client.post("/curations/active/close", json={"als_path": "/p/a.als"})
    disk = json.loads(state_path.read_text())
    assert disk["active_curations"] == {"/p/b.als": "beta"}


# ── 4) Startup load with corruption recovery ──────────────────────────────


def test_startup_load_recovers_from_corrupt_state_file(tmp_path: Path) -> None:
    """A malformed state file is moved aside, then create_app boots clean.

    Writes corrupt JSON, runs ``load_state_with_recovery``, and asserts:
      - returned state is empty (server boots with no active curations).
      - the corrupt file has been archived under ``.corrupt-<ts>``.
      - the canonical path is gone (next save_state will create it fresh).
    """
    state_path = tmp_path / ".stemforge_state.json"
    state_path.write_text("{not valid json at all")
    recovered = load_state_with_recovery(state_path)

    assert isinstance(recovered, StemforgeState)
    assert recovered.active_curations == {}
    assert not state_path.is_file(), "corrupt file should have been moved aside"

    # Backup file present with the corrupt-<ts> suffix.
    backups = list(tmp_path.glob(".stemforge_state.json.corrupt-*"))
    assert len(backups) == 1
    assert "{not valid json at all" in backups[0].read_text()


def test_startup_load_returns_empty_when_file_absent(tmp_path: Path) -> None:
    """No state file == fresh-install state; no backup needed, no error."""
    target = tmp_path / ".stemforge_state.json"
    recovered = load_state_with_recovery(target)
    assert recovered.active_curations == {}
    assert not target.exists()  # we did NOT create it as a side-effect
    # And no backup either — clean absence is not corruption.
    assert not list(tmp_path.glob(".stemforge_state.json.corrupt-*"))


# ── 5) SSE broadcast on /als-opened ──────────────────────────────────────


def test_als_opened_returns_active_and_broadcasts_bootstrap(
    client: TestClient, configurator_paths: dict[str, Path]
) -> None:
    """``POST /als-opened`` returns the cached active curation + emits SSE.

    Pre-populates the state file out-of-band, then re-creates the app so
    the cache primes from disk at startup. Hits the route and asserts
    both the JSON response shape and that a ``kind=bootstrap`` SSE event
    fired on the broker.
    """
    state_path = configurator_paths["state_path"]
    save_state(
        StemforgeState(active_curations={"/projects/song.als": "verse_swap_v1"}),
        state_path,
    )

    # Fresh app so startup-load reads the seeded file.
    app = create_app(
        static_dir=configurator_paths["static_dir"],
        curations_dir=configurator_paths["curations_dir"],
        state_path=state_path,
        templates_dir=configurator_paths["templates_dir"],
    )
    fresh_client = TestClient(app)

    # Capture SSE events as they're broadcast. Subscribing requires an
    # asyncio.Queue under the running loop; we capture by tapping into
    # the AppState's broadcast list directly.
    captured: list[dict] = []
    app_state = app.state.configurator

    async def _capture(event):  # type: ignore[no-untyped-def]
        captured.append({"event": event.event, "data": event.data})

    original_broadcast = app_state.broadcast

    async def _spy(event):  # type: ignore[no-untyped-def]
        await _capture(event)
        await original_broadcast(event)

    app_state.broadcast = _spy  # type: ignore[assignment]

    r = fresh_client.post("/als-opened", json={"als_path": "/projects/song.als"})
    assert r.status_code == 200
    body = r.json()
    assert body == {
        "ok": True,
        "als_path": "/projects/song.als",
        "active_curation": "verse_swap_v1",
    }

    bootstrap_events = [
        e for e in captured if e["event"] == "state" and e["data"].get("kind") == "bootstrap"
    ]
    assert len(bootstrap_events) == 1
    assert bootstrap_events[0]["data"]["als_path"] == "/projects/song.als"
    assert bootstrap_events[0]["data"]["active_curation"] == "verse_swap_v1"


def test_als_opened_unknown_path_returns_null_active(
    client: TestClient,
) -> None:
    """An unrecognized .als path acks with ``active_curation: None``.

    First-run / unseen Live sets land here. The device's ack handler
    interprets ``None`` as "do nothing further" — no auto-load.
    """
    r = client.post("/als-opened", json={"als_path": "/totally/new.als"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["als_path"] == "/totally/new.als"
    assert body["active_curation"] is None


def test_open_curation_refreshes_cache_for_subsequent_als_opened(
    client: TestClient, configurator_paths: dict[str, Path]
) -> None:
    """A live ``open`` mutation is visible to a subsequent ``als-opened`` call.

    Bridges the two halves of the lane: the writer (open endpoint) feeds
    the cache that the bootstrap endpoint reads. If the cache refresh
    were broken, the second call would still return ``null`` because the
    in-memory map would lag behind disk.
    """
    _seed_curation(configurator_paths["curations_dir"], "gamma")
    als = "/projects/late.als"

    # Bootstrap before open: no active curation yet.
    r = client.post("/als-opened", json={"als_path": als})
    assert r.json()["active_curation"] is None

    # Now open the curation for this .als path.
    r = client.post("/curations/gamma/open", json={"als_path": als})
    assert r.status_code == 200

    # Re-bootstrap: cache must have refreshed.
    r = client.post("/als-opened", json={"als_path": als})
    assert r.json()["active_curation"] == "gamma"


def test_load_state_with_recovery_handles_schema_violation(tmp_path: Path) -> None:
    """A pydantic-invalid JSON body archives the file just like bad JSON does.

    Edge case: file parses as JSON but doesn't match the StemforgeState
    shape (e.g. ``active_curations`` is a list, not an object). Recovery
    must still move it aside and return an empty state.
    """
    state_path = tmp_path / ".stemforge_state.json"
    state_path.write_text(json.dumps({"schema_version": 1, "active_curations": ["bogus"]}))
    recovered = load_state_with_recovery(state_path)
    assert recovered.active_curations == {}
    assert not state_path.is_file()
    backups = list(tmp_path.glob(".stemforge_state.json.corrupt-*"))
    assert len(backups) == 1


def test_set_active_curation_sets_last_seen_at(tmp_path: Path) -> None:
    """Sanity check on the writer: every save bumps ``last_seen_at``.

    Confirms ``set_active_curation``'s timestamp behaviour persists
    through ``load_state`` round-trip. Without this guard, a future
    refactor could silently drop the timestamp and we'd lose forensic
    information about when the active map was last touched.
    """
    state_path = tmp_path / "ts.json"
    before = datetime.now(UTC)
    set_active_curation("/x.als", "n", state_path)
    reloaded = load_state(state_path)
    assert reloaded.last_seen_at is not None
    assert reloaded.last_seen_at >= before
