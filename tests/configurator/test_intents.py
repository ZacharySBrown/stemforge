"""Async handler tests — exercise each intent against a fresh AppState."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from stemforge.configurator import intents
from stemforge.configurator.schemas import (
    AssignPadRequest,
    ClearPadRequest,
    CommitRequest,
    LoadManifestRequest,
    RecomputeRequest,
    SetGroupFormatRequest,
)
from stemforge.configurator.state import AppState


def _run(coro):
    # Pytest doesn't bind a default event loop on Python 3.10+; create one
    # per call so handlers' asyncio.Lock() init binds to the loop they'll
    # run on. We can't use asyncio.run() because the AppState's Lock is
    # constructed in the fixture (outside the coroutine) and would bind to
    # a different loop. Solution: use the same event loop for all _run
    # calls within a test.
    loop = _ensure_loop()
    return loop.run_until_complete(coro)


_LOOP_CACHE: dict[str, asyncio.AbstractEventLoop] = {}


def _ensure_loop():
    loop = _LOOP_CACHE.get("loop")
    if loop is None or loop.is_closed():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        _LOOP_CACHE["loop"] = loop
    return loop


@pytest.fixture
def state() -> AppState:
    # Make sure the AppState's asyncio.Lock binds to the same loop the
    # _run helper uses. Initializing the loop here primes the policy.
    _ensure_loop()
    return AppState()


@pytest.fixture
def collected_events(state: AppState):
    """Subscribe to the broker and collect events into a list."""
    queue = state.subscribe()
    events: list = []

    async def drain():
        while not queue.empty():
            events.append(await queue.get())

    yield events, drain
    state.unsubscribe(queue)


def test_load_manifest_populates_state(state: AppState, small_manifest: Path):
    resp = _run(
        intents.handle_load_manifest(state, LoadManifestRequest(manifest_path=small_manifest))
    )
    assert resp.ok
    assert resp.state is not None
    song = resp.state.songs[0]
    # All four groups present, each with one pad.
    group_ids = {g.group_id for g in song.groups}
    assert group_ids == {"A", "B", "C", "D"}
    assert all(len(g.pads) == 1 for g in song.groups)
    # last_manifest_path tracked so /intent/commit can re-read.
    assert state.last_manifest_path == str(small_manifest.resolve())


def test_load_manifest_missing_file_returns_error(state: AppState, tmp_path: Path):
    resp = _run(
        intents.handle_load_manifest(
            state, LoadManifestRequest(manifest_path=tmp_path / "nope.json")
        )
    )
    assert not resp.ok
    assert resp.state is None
    assert any("not found" in e for e in resp.errors)


def test_load_manifest_broadcasts_state(state: AppState, small_manifest: Path, collected_events):
    events, drain = collected_events
    _run(intents.handle_load_manifest(state, LoadManifestRequest(manifest_path=small_manifest)))
    _run(drain())
    event_names = [e.event for e in events]
    assert "state" in event_names
    assert "log" in event_names


def test_commit_with_session_tracks_populates_audio_hash(
    state: AppState, small_manifest: Path, make_wav
):
    # Load first so we have a baseline.
    _run(intents.handle_load_manifest(state, LoadManifestRequest(manifest_path=small_manifest)))
    wav = make_wav("commit.wav")
    req = CommitRequest(
        session_tracks={
            "A": [{"slot": 0, "file_path": str(wav), "clip_length_sec": 0.5, "name": "v1"}]
        }
    )
    resp = _run(intents.handle_commit(state, req))
    assert resp.ok
    pad = resp.state.songs[0].groups[0].pads[0]
    assert pad.clip is not None
    assert pad.clip.audio_hash != ""
    assert len(pad.clip.audio_hash) == 16


def test_commit_requires_payload_source(state: AppState):
    resp = _run(intents.handle_commit(state, CommitRequest()))
    assert not resp.ok
    assert any("session_tracks or manifest_path" in e for e in resp.errors)


def test_commit_with_manifest_path_reads_from_disk(state: AppState, small_manifest: Path):
    resp = _run(intents.handle_commit(state, CommitRequest(manifest_path=small_manifest)))
    assert resp.ok
    # Manifest's session_tracks were applied.
    groups = {g.group_id: g for g in resp.state.songs[0].groups}
    assert len(groups["A"].pads) == 1


def test_assign_pad_creates_clip(state: AppState, make_wav):
    wav = make_wav("a.wav")
    resp = _run(
        intents.handle_assign_pad(
            state,
            AssignPadRequest(group="A", pad=3, clip_path=str(wav), name="hook"),
        )
    )
    assert resp.ok
    pads = {p.pad_id: p for p in resp.state.songs[0].groups[0].pads}
    assert "3" in pads
    assert pads["3"].clip is not None
    assert pads["3"].clip.name == "hook"
    assert pads["3"].clip.audio_hash != ""


def test_assign_pad_requires_clip_id_or_path(state: AppState):
    resp = _run(intents.handle_assign_pad(state, AssignPadRequest(group="A", pad=1)))
    assert not resp.ok


def test_clear_pad_drops_clip(state: AppState, make_wav):
    wav = make_wav("a.wav")
    _run(
        intents.handle_assign_pad(
            state,
            AssignPadRequest(group="A", pad=3, clip_path=str(wav)),
        )
    )
    resp = _run(intents.handle_clear_pad(state, ClearPadRequest(group="A", pad=3)))
    assert resp.ok
    pads = {p.pad_id: p for p in resp.state.songs[0].groups[0].pads}
    assert pads["3"].clip is None


def test_set_group_format_updates_profile(state: AppState):
    resp = _run(
        intents.handle_set_group_format(state, SetGroupFormatRequest(group="A", format="vocal"))
    )
    assert resp.ok
    g = {g.group_id: g for g in resp.state.songs[0].groups}["A"]
    assert g.format_profile == "vocal"


def test_recompute_broadcasts_without_mutation(state: AppState, collected_events):
    events, drain = collected_events
    resp = _run(intents.handle_recompute(state, RecomputeRequest()))
    _run(drain())
    assert resp.ok
    assert any(e.event == "state" for e in events)


def test_mutation_lock_prevents_concurrent_writes(state: AppState, small_manifest: Path):
    """Two concurrent commits must serialize; both succeed without partial state."""

    async def run_both():
        return await asyncio.gather(
            intents.handle_commit(
                state,
                CommitRequest(session_tracks={"A": [{"slot": 0, "name": "v1"}]}),
            ),
            intents.handle_commit(
                state,
                CommitRequest(session_tracks={"B": [{"slot": 0, "name": "v2"}]}),
            ),
        )

    a, b = _run(run_both())
    assert a.ok and b.ok
    # Final state: last writer wins for the group it wrote, but the other
    # group's pads are also persisted because each commit writes
    # one-group's worth of data.
    groups = {g.group_id: g for g in state.project.songs[0].groups}
    # The exact final state depends on serialization order, but both
    # groups must exist in the model.
    assert "A" in groups and "B" in groups
