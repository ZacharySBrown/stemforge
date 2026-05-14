"""Tests for the Pre-UAT P0 fixes (Lane A — server-only).

Three independent slices live here:

* **P0-1** — ``POST /intent/pick-manifest`` route + sniffer taxonomy.
* **P0-2** — ``OpenCurationBody.als_path`` / ``CloseActiveCurationBody.als_path``
  optional + ``POPUP_ALS_SENTINEL`` default.
* **P0-3** — initial SSE snapshot on ``/state/stream`` emits the
  ``kind: "curations"`` shape (not the legacy ``Project`` shape).

See ``docs/configurator/PRE_UAT_REVIEW.md`` for the upstream findings.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from stemforge.configurator.curation_io import (
    curation_path,
    write_curation_atomic,
)
from stemforge.configurator.intents import (
    POPUP_ALS_SENTINEL,
    sniff_manifest_kind,
)
from stemforge.configurator.schemas import Curation, Group, Pad, Target
from stemforge.configurator.server import create_app
from stemforge.configurator.state import AppState, current_curations_state


# ── Fixtures ────────────────────────────────────────────────────────────────


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


def _make_client(
    paths: dict[str, Path],
    runner: Any | None = None,
) -> TestClient:
    app = create_app(
        static_dir=paths["static_dir"],
        curations_dir=paths["curations_dir"],
        state_path=paths["state_path"],
        processed_dir=paths["processed_dir"],
        subprocess_runner=runner,
    )
    return TestClient(app)


def _seed_curation(curations_dir: Path, name: str) -> Curation:
    """Minimal curation YAML used as bait by the open/close/SSE tests."""
    from datetime import UTC, datetime

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


# ── P0-1: POST /intent/pick-manifest ────────────────────────────────────────


def test_pick_manifest_returns_forge_manifest_kind(
    configurator_paths: dict[str, Path], tmp_path: Path
) -> None:
    """Sniffer classifies a JSON with ``pads`` + ``schema_version`` correctly."""
    manifest = tmp_path / "fixtures" / "snare_kit" / "manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 3,
                "pads": [{"pad_id": "A01", "clip_id": "abc"}],
            }
        )
    )

    def runner(cmd: list[str], **kwargs: Any) -> Any:
        # Mocked osascript stdout = chosen path.
        assert cmd[0] == "osascript"
        return SimpleNamespace(returncode=0, stdout=str(manifest) + "\n", stderr="")

    client = _make_client(configurator_paths, runner=runner)
    r = client.post("/intent/pick-manifest", json={})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["path"] == str(manifest)
    assert body["kind"] == "forge_manifest"


def test_pick_manifest_classifies_audio_by_extension(
    configurator_paths: dict[str, Path], tmp_path: Path
) -> None:
    """An ``.wav`` path resolves to ``kind=audio`` even if the file's empty."""
    wav = tmp_path / "kick.wav"
    wav.write_bytes(b"RIFF\x00\x00\x00\x00WAVE")

    def runner(cmd: list[str], **kwargs: Any) -> Any:
        return SimpleNamespace(returncode=0, stdout=str(wav) + "\n", stderr="")

    client = _make_client(configurator_paths, runner=runner)
    r = client.post("/intent/pick-manifest", json={"filter": "audio"})
    assert r.status_code == 200
    body = r.json()
    assert body["path"] == str(wav)
    assert body["kind"] == "audio"


def test_pick_manifest_classifies_curation_yaml(
    configurator_paths: dict[str, Path], tmp_path: Path
) -> None:
    """A YAML with ``curation_version`` sniffs as ``curation``."""
    yaml_path = tmp_path / "my_curation.yaml"
    yaml_path.write_text("curation_version: 1\nname: test\n")

    def runner(cmd: list[str], **kwargs: Any) -> Any:
        return SimpleNamespace(returncode=0, stdout=str(yaml_path) + "\n", stderr="")

    client = _make_client(configurator_paths, runner=runner)
    r = client.post("/intent/pick-manifest", json={"filter": "manifest"})
    assert r.status_code == 200
    body = r.json()
    assert body["kind"] == "curation"


def test_pick_manifest_returns_null_kind_unknown_on_cancel(
    configurator_paths: dict[str, Path],
) -> None:
    """User cancel → ``{path: null, kind: "unknown"}`` (200, not 500)."""

    def runner(cmd: list[str], **kwargs: Any) -> Any:
        # AppleScript user-cancel = exit code 1.
        return SimpleNamespace(returncode=1, stdout="", stderr="User canceled.")

    client = _make_client(configurator_paths, runner=runner)
    r = client.post("/intent/pick-manifest", json={})
    assert r.status_code == 200
    body = r.json()
    assert body["path"] is None
    assert body["kind"] == "unknown"


def test_pick_manifest_handles_missing_osascript(
    configurator_paths: dict[str, Path],
) -> None:
    """Headless / non-mac runner without ``osascript`` doesn't 500."""

    def runner(cmd: list[str], **kwargs: Any) -> Any:
        raise FileNotFoundError("osascript not found")

    client = _make_client(configurator_paths, runner=runner)
    r = client.post("/intent/pick-manifest", json={})
    assert r.status_code == 200
    body = r.json()
    assert body["path"] is None
    assert body["kind"] == "unknown"


def test_pick_manifest_handles_subprocess_error_gracefully(
    configurator_paths: dict[str, Path],
) -> None:
    """Other subprocess errors (timeout / OSError) also surface as 200 + null."""

    def runner(cmd: list[str], **kwargs: Any) -> Any:
        import subprocess

        raise subprocess.TimeoutExpired(cmd=cmd, timeout=120)

    client = _make_client(configurator_paths, runner=runner)
    r = client.post("/intent/pick-manifest", json={})
    assert r.status_code == 200
    assert r.json() == {"path": None, "kind": "unknown"}


# ── Pure sniffer-helper tests ───────────────────────────────────────────────


def test_sniff_manifest_kind_arrangement_manifest(tmp_path: Path) -> None:
    """``chunks``-keyed JSON sniffs as arrangement_manifest."""
    path = tmp_path / "arrangement.json"
    path.write_text(json.dumps({"schema_version": 1, "chunks": []}))
    assert sniff_manifest_kind(str(path)) == "arrangement_manifest"


def test_sniff_manifest_kind_unknown_for_random_json(tmp_path: Path) -> None:
    """JSON without pads/chunks falls through to ``unknown``."""
    path = tmp_path / "random.json"
    path.write_text(json.dumps({"schema_version": 1, "other": 42}))
    assert sniff_manifest_kind(str(path)) == "unknown"


def test_sniff_manifest_kind_unknown_for_empty_path() -> None:
    """Empty / missing path is harmless."""
    assert sniff_manifest_kind("") == "unknown"


# ── P0-2: optional als_path + sentinel ──────────────────────────────────────


def test_popup_als_sentinel_constant_value() -> None:
    """The popup sentinel value is the public contract — pin it."""
    assert POPUP_ALS_SENTINEL == "__popup__"


def test_open_curation_with_empty_body_uses_popup_sentinel(
    configurator_paths: dict[str, Path],
) -> None:
    """POST /curations/{name}/open with no body → 200, sentinel keyed."""
    _seed_curation(configurator_paths["curations_dir"], "partial")
    client = _make_client(configurator_paths)
    r = client.post("/curations/partial/open", json={})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["active_curations"][POPUP_ALS_SENTINEL] == "partial"

    # State file on disk also shows the sentinel mapping.
    state_data = json.loads(configurator_paths["state_path"].read_text())
    assert state_data["active_curations"][POPUP_ALS_SENTINEL] == "partial"


def test_close_active_curation_with_empty_body_uses_popup_sentinel(
    configurator_paths: dict[str, Path],
) -> None:
    """POST /curations/active/close with ``{}`` → 200, sentinel removed."""
    _seed_curation(configurator_paths["curations_dir"], "partial")
    client = _make_client(configurator_paths)
    # First open the popup-attached curation.
    client.post("/curations/partial/open", json={})
    state_before = json.loads(configurator_paths["state_path"].read_text())
    assert state_before["active_curations"].get(POPUP_ALS_SENTINEL) == "partial"

    r = client.post("/curations/active/close", json={})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["als_path"] == POPUP_ALS_SENTINEL

    state_after = json.loads(configurator_paths["state_path"].read_text())
    assert POPUP_ALS_SENTINEL not in state_after["active_curations"]


def test_open_curation_with_explicit_als_path_still_works(
    configurator_paths: dict[str, Path],
) -> None:
    """Backward compat — Live-attached flows passing a real .als still work."""
    _seed_curation(configurator_paths["curations_dir"], "partial")
    client = _make_client(configurator_paths)
    als = "/Users/zak/Music/Ableton/Verse Swap.als"
    r = client.post("/curations/partial/open", json={"als_path": als})
    assert r.status_code == 200
    body = r.json()
    assert body["active_curations"][als] == "partial"
    # The popup sentinel is NOT used when a real path is supplied.
    assert POPUP_ALS_SENTINEL not in body["active_curations"]


# ── P0-3: initial SSE snapshot emits kind=curations ─────────────────────────


def test_initial_sse_snapshot_emits_curations_shape(
    configurator_paths: dict[str, Path],
) -> None:
    """First frame on ``/state/stream`` is the ``kind: "curations"`` shape.

    Previously the route emitted ``state.project`` (legacy Project shape)
    which the popup misrouted into the no-curation branch. The fix sends
    the same payload that ``broadcast_curations_state`` produces.

    Implementation note: we don't drive a real SSE connection through
    TestClient (the stream blocks forever waiting for keepalives).
    Instead we exercise the exact code path the route uses to build the
    first frame — ``current_curations_state(state)`` — and assert its
    shape matches the contract the popup's ``handleStateEvent`` expects.
    """
    _seed_curation(configurator_paths["curations_dir"], "alpha")
    _seed_curation(configurator_paths["curations_dir"], "beta")

    state = AppState()
    state.curations_dir = configurator_paths["curations_dir"]
    state.state_path = configurator_paths["state_path"]
    state.processed_dir = configurator_paths["processed_dir"]

    payload = current_curations_state(state)
    assert payload["kind"] == "curations"
    assert set(payload["curations"]) == {"alpha", "beta"}
    # The route wraps this in an ``SseEvent(event="state", data=...)``
    # frame — verify the wire format is what subscribers actually see.
    from stemforge.configurator.state import SseEvent

    wire = SseEvent(event="state", data=payload).to_wire()
    assert wire.startswith("event: state\n")
    assert '"kind": "curations"' in wire


def test_initial_sse_snapshot_reflects_active_curations(
    configurator_paths: dict[str, Path],
) -> None:
    """Cold-start payload mirrors current active_curations (POPUP sentinel).

    Drives a mutation through the FastAPI app (POST /curations/{name}/open
    with empty body — exercises P0-2 too) and then asks
    :func:`current_curations_state` for what a fresh subscriber would
    see on the next connection. Must reflect the popup-sentinel mapping.
    """
    _seed_curation(configurator_paths["curations_dir"], "partial")
    client = _make_client(configurator_paths)
    client.post("/curations/partial/open", json={})

    state = AppState()
    state.curations_dir = configurator_paths["curations_dir"]
    state.state_path = configurator_paths["state_path"]
    state.processed_dir = configurator_paths["processed_dir"]

    payload = current_curations_state(state)
    assert payload["kind"] == "curations"
    assert payload["active_curations"].get(POPUP_ALS_SENTINEL) == "partial"


def test_state_stream_route_imports_current_curations_state(
    configurator_paths: dict[str, Path],
) -> None:
    """The server module imports and uses ``current_curations_state``.

    Source-grep contract pin: the legacy bug was that ``/state/stream``
    built its first frame from ``state.project.model_dump_json(...)``;
    the fix replaces that with ``current_curations_state(state)``.
    We assert (a) the import is present at module scope, (b) the legacy
    Project-shape construction is gone from the route, and (c) the
    helper is wired into the event_source path.

    Why source-grep instead of an end-to-end stream subscription:
    Starlette/httpx TestClient hangs on context-manager exit when an
    SSE response generator is parked on an asyncio queue, even after
    a single chunk read. Source-grep is a sound proxy because the
    helper itself is exercised by
    ``test_current_curations_state_pure_helper`` and
    ``test_current_curations_state_matches_broadcaster_payload``.
    """
    import inspect

    import stemforge.configurator.server as server_module

    # (a) helper is importable from the module
    assert hasattr(server_module, "current_curations_state")

    # (b) stream_state route no longer constructs the legacy Project shape
    src = inspect.getsource(server_module)
    # The exact phrase from the pre-fix code path. If this lands back in
    # the file, the cold-start payload regression is back too.
    assert "state.project.model_dump_json" not in src, (
        "/state/stream's cold-start snapshot must NOT use the legacy "
        "Project shape — popup boot-state will regress (P0-3)."
    )

    # (c) the new helper is called from the route
    assert "current_curations_state(state)" in src


def test_current_curations_state_pure_helper(
    configurator_paths: dict[str, Path],
) -> None:
    """``current_curations_state`` returns the same shape the broadcaster pushes."""
    _seed_curation(configurator_paths["curations_dir"], "solo")
    state = AppState()
    state.curations_dir = configurator_paths["curations_dir"]
    state.state_path = configurator_paths["state_path"]
    state.processed_dir = configurator_paths["processed_dir"]

    payload = current_curations_state(state)
    assert payload["kind"] == "curations"
    assert payload["curations"] == ["solo"]
    assert isinstance(payload["active_curations"], dict)
    assert isinstance(payload["stale_by_curation"], dict)
    assert "ts" in payload


def test_current_curations_state_matches_broadcaster_payload(
    configurator_paths: dict[str, Path],
) -> None:
    """The broadcaster pushes the EXACT shape current_curations_state returns.

    Pins the contract between the cold-start path and the mutation-driven
    path: both must produce identical dicts (modulo ts).
    """
    from stemforge.configurator.intents import (
        CreateCurationBody,
        handle_create_curation,
    )

    state = AppState()
    state.curations_dir = configurator_paths["curations_dir"]
    state.state_path = configurator_paths["state_path"]
    state.processed_dir = configurator_paths["processed_dir"]

    async def _drive() -> tuple[dict[str, Any], dict[str, Any]]:
        queue = state.subscribe()
        try:
            await handle_create_curation(state, CreateCurationBody(name="contract"))
            broadcast_data: dict[str, Any] = {}
            while not queue.empty():
                ev = queue.get_nowait()
                if ev.event == "state":
                    broadcast_data = ev.data
            return broadcast_data, current_curations_state(state)
        finally:
            state.unsubscribe(queue)

    broadcast_payload, helper_payload = asyncio.run(_drive())
    # Compare ignoring ts (always now()).
    bp = {k: v for k, v in broadcast_payload.items() if k != "ts"}
    hp = {k: v for k, v in helper_payload.items() if k != "ts"}
    assert bp == hp
