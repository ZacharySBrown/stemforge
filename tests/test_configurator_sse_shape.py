"""SSE state-event shape regression tests (Pre-UAT P1-9).

Every ``state`` SSE frame emitted by the server MUST carry an explicit
``kind`` discriminator. Lane G locked this contract to unblock the
popup's ``handleStateEvent``, which now dispatches on ``kind`` first and
falls back to the legacy ``Project`` shape only when no recognized kind
is set.

The recognized kinds today are:

* ``curations`` — emitted on every curation CRUD mutation +
  ``/state/stream`` cold-start snapshot. Carries
  ``{curations, active_curations, stale_by_curation, ts}``.
* ``forges`` — emitted on forge load/unload/re-anchor/re-curate.
* ``bootstrap`` — emitted by ``POST /als-opened``.
* ``bounce-start`` — emitted by ``POST /curations/{name}/trigger-bounce``.
* ``project`` — Lane G's belt-and-suspenders kind for the legacy
  scene-model ``/intent/*`` broadcasts (``load-manifest``, ``commit``,
  ``assign-pad``, ``clear-pad``, ``set-group-format``, ``recompute``).

The test below subscribes to ``state.subscribers`` directly (no
TestClient SSE plumbing needed) and drives the broadcasters from the
public API, asserting every emitted ``state`` event has a kind in the
allowlist.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from stemforge.configurator.intents import (
    AssignPadRequest,
    ClearPadRequest,
    CreateCurationBody,
    LoadManifestRequest,
    OpenCurationBody,
    RecomputeRequest,
    SetGroupFormatRequest,
    handle_assign_pad,
    handle_clear_pad,
    handle_create_curation,
    handle_load_manifest,
    handle_open_curation,
    handle_recompute,
    handle_set_group_format,
)
from stemforge.configurator.schemas import Target
from stemforge.configurator.state import AppState, SseEvent

# Every state-kind the server is allowed to emit today. Adding a new
# kind requires adding it here AND documenting it in the module docstring.
ALLOWED_STATE_KINDS = frozenset(
    {
        "curations",
        "forges",
        "bootstrap",
        "bounce-start",
        "project",
    }
)


@pytest.fixture
def state(tmp_path: Path) -> AppState:
    s = AppState()
    s.curations_dir = tmp_path / "curations"
    s.curations_dir.mkdir()
    s.state_path = tmp_path / ".stemforge_state.json"
    s.processed_dir = tmp_path / "processed"
    s.processed_dir.mkdir()
    return s


def _drain(state: AppState, coro_factory) -> list[SseEvent]:
    """Subscribe, run ``coro_factory()``, collect all events, unsubscribe."""

    async def _run() -> list[SseEvent]:
        q = state.subscribe()
        try:
            await coro_factory()
            collected: list[SseEvent] = []
            while not q.empty():
                collected.append(q.get_nowait())
            return collected
        finally:
            state.unsubscribe(q)

    return asyncio.run(_run())


def _state_events(events: list[SseEvent]) -> list[SseEvent]:
    return [e for e in events if e.event == "state"]


# ── New shape lock: legacy /intent/* broadcasts now carry kind:"project" ───


def test_recompute_broadcast_carries_kind_project(state: AppState) -> None:
    """``POST /intent/recompute`` — legacy scene-model broadcast.

    Pre-P1-9 this emitted a bare ``Project`` JSON shape with no
    ``kind`` field, which the popup mis-routed into its legacy
    fallback. Lane G's belt-and-suspenders wraps the project shape in
    ``{"kind": "project", "project": {...}, "ts": ...}`` so the popup
    discriminates uniformly.
    """
    events = _drain(state, lambda: handle_recompute(state, RecomputeRequest()))
    state_events = _state_events(events)
    assert state_events, f"no state events emitted; got {[e.event for e in events]}"
    for evt in state_events:
        assert evt.data.get("kind") in ALLOWED_STATE_KINDS, (
            f"state event missing/unknown kind={evt.data.get('kind')!r}: {evt.data!r}"
        )


def test_assign_pad_broadcast_carries_kind_project(state: AppState) -> None:
    """``POST /intent/assign-pad`` legacy broadcast → kind:"project"."""
    events = _drain(
        state,
        lambda: handle_assign_pad(
            state,
            AssignPadRequest(group="A", pad=1, clip_id="abc123", clip_path=None),
        ),
    )
    state_events = _state_events(events)
    assert state_events
    for evt in state_events:
        assert evt.data.get("kind") in ALLOWED_STATE_KINDS, evt.data


def test_clear_pad_broadcast_carries_kind_project(state: AppState) -> None:
    """``POST /intent/clear-pad`` legacy broadcast → kind:"project"."""
    events = _drain(
        state,
        lambda: handle_clear_pad(state, ClearPadRequest(group="A", pad=1)),
    )
    state_events = _state_events(events)
    assert state_events
    for evt in state_events:
        assert evt.data.get("kind") in ALLOWED_STATE_KINDS, evt.data


def test_set_group_format_broadcast_carries_kind_project(state: AppState) -> None:
    """``POST /intent/set-group-format`` legacy broadcast → kind:"project"."""
    events = _drain(
        state,
        lambda: handle_set_group_format(state, SetGroupFormatRequest(group="A", format="drum")),
    )
    state_events = _state_events(events)
    assert state_events
    for evt in state_events:
        assert evt.data.get("kind") in ALLOWED_STATE_KINDS, evt.data


def test_load_manifest_failure_broadcast_carries_kind_project(
    state: AppState, tmp_path: Path
) -> None:
    """Even error paths shouldn't leak un-tagged state frames.

    ``handle_load_manifest`` doesn't broadcast on the manifest-not-found
    error branch (it emits an ``error`` SSE event instead), but the
    happy path (after this test seeds a valid manifest) goes through
    ``broadcast_state`` — our new kind-tagged path. Verifies that.
    """
    manifest_path = tmp_path / "stems.json"
    manifest_path.write_text(
        json.dumps(
            {
                "bpm": 120.0,
                "session_tracks": {"A": [], "B": [], "C": [], "D": []},
            }
        )
    )
    events = _drain(
        state,
        lambda: handle_load_manifest(
            state,
            LoadManifestRequest(
                manifest_path=manifest_path,
                bpm=120.0,
                time_sig=(4, 4),
                project_name="seed",
            ),
        ),
    )
    state_events = _state_events(events)
    assert state_events, "expected a state broadcast on successful load"
    for evt in state_events:
        assert evt.data.get("kind") in ALLOWED_STATE_KINDS, evt.data


# ── Curation CRUD path stays kind:"curations" ───────────────────────────────


def test_create_curation_broadcasts_kind_curations(state: AppState) -> None:
    events = _drain(
        state,
        lambda: handle_create_curation(state, CreateCurationBody(name="kindtest", target=Target())),
    )
    state_events = _state_events(events)
    assert state_events
    # The curation CRUD path emits kind="curations".
    assert any(e.data.get("kind") == "curations" for e in state_events), [
        e.data.get("kind") for e in state_events
    ]


def test_open_curation_broadcasts_kind_curations(state: AppState) -> None:
    # Seed first.
    asyncio.run(handle_create_curation(state, CreateCurationBody(name="openme", target=Target())))
    events = _drain(
        state,
        lambda: handle_open_curation(state, "openme", OpenCurationBody()),
    )
    state_events = _state_events(events)
    assert state_events
    assert any(e.data.get("kind") == "curations" for e in state_events)


# ── Cold-start SSE snapshot path (server.py /state/stream) ─────────────────


def test_cold_start_snapshot_uses_current_curations_state(state: AppState) -> None:
    """Lane A's cold-start snapshot must emit kind:"curations" too.

    Reaches into the server module to exercise the same builder the
    ``/state/stream`` route uses on subscribe.
    """
    from stemforge.configurator.state import current_curations_state

    snapshot = current_curations_state(state)
    assert snapshot["kind"] == "curations", snapshot
    assert "curations" in snapshot
    assert "active_curations" in snapshot


# ── Audit: every kind we ever emit is in the allowlist ─────────────────────


def test_no_legacy_untagged_project_broadcast_remains() -> None:
    """Static-source check: ``broadcast_state`` must wrap with kind:"project".

    A regression that reverts this contract (dropping the kind tag back
    to a bare Project dump) is the failure mode we're protecting against.
    Greps the source for the legacy emitter so the test catches "someone
    edited it back" faster than a runtime test that needs a broadcast
    to fire.
    """
    src = Path("stemforge/configurator/state.py").read_text()
    # The legacy emitter looked like:
    #   data=json.loads(project_to_json(self.project))
    # …unwrapped. The new one wraps in {"kind": "project", "project": ...}.
    bad = "data=json.loads(project_to_json(self.project))"
    assert bad not in src, (
        "found legacy untagged Project broadcast — Lane G's P1-9 fix regressed. "
        "Wrap the payload in {'kind': 'project', 'project': ..., 'ts': ...}."
    )
    # And the new wrapper IS present.
    assert '"kind": "project"' in src, (
        "kind:'project' tag missing from state.py broadcast_state. "
        "Lane G's P1-9 wrapper may have been removed."
    )


def test_allowed_kinds_is_documented_and_synced() -> None:
    """The allowlist + module docstring must stay synced.

    If a new kind is added to the allowlist, it must also appear in the
    module docstring (this file's top-of-file kind catalog). This is a
    cheap belt-and-suspenders to keep humans honest.
    """
    doc = __doc__ or ""
    for kind in ALLOWED_STATE_KINDS:
        assert f"``{kind}``" in doc, (
            f"kind {kind!r} is in ALLOWED_STATE_KINDS but missing from the "
            "module docstring. Update the catalog at the top of this file."
        )
