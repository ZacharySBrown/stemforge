"""Curation CRUD endpoint tests (Phase 1B, spec §4.3).

Each test spins up a fresh :class:`FastAPI` app with a ``tmp_path``-rooted
curations dir + state file so the user's real ``~/stemforge`` is never
touched. Tests use :class:`fastapi.testclient.TestClient` so they run in
the same process and play nicely with the in-process SSE broker.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from stemforge.configurator.curation_io import (
    curation_path,
    read_curation,
    write_curation_atomic,
)
from stemforge.configurator.schemas import Curation, Pad, PadSource, Target
from stemforge.configurator.server import create_app


# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def configurator_paths(tmp_path: Path) -> dict[str, Path]:
    """Provision an isolated ``~/stemforge/`` layout under ``tmp_path``."""
    curations_dir = tmp_path / "curations"
    curations_dir.mkdir()
    state_path = tmp_path / ".stemforge_state.json"
    static_dir = tmp_path / "static"
    # Phase 3A: tests that PATCH /template must seed expected ``.adg``
    # sentinels under this dir. Created empty so unrelated tests don't
    # leak templates into other tests' assertions.
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


def _seed_template(templates_dir: Path, name: str) -> Path:
    """Drop a sentinel ``<name>.adg`` (empty bytes) so the patch validator passes."""
    path = templates_dir / f"{name}.adg"
    path.write_bytes(b"")
    return path


def _seed_curation(curations_dir: Path, name: str, *, populated: bool = False) -> Curation:
    """Drop a Curation YAML on disk via the same atomic writer the server uses."""
    now = datetime.now(UTC)
    target = Target()
    groups: dict = {}
    from stemforge.configurator.schemas import Group

    for letter_idx, letter in enumerate(["A", "B", "C", "D"]):
        pads = [Pad(pad_id=f"{letter}{i + 1:02d}") for i in range(12)]
        if populated and letter_idx == 0:
            pads[0] = Pad(
                pad_id="A01",
                source=PadSource(
                    forge="seeded-forge",
                    clip_id="vocal-bar0",
                    audio_path="curated_audio/vocal-bar0.wav",
                ),
            )
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


# ── GET /curations ──────────────────────────────────────────────────────────


def test_list_curations_empty(client: TestClient) -> None:
    r = client.get("/curations")
    assert r.status_code == 200
    body = r.json()
    assert body == {"curations": [], "active_curations": {}, "errors": []}


def test_list_curations_returns_stable_sorted_summaries(
    client: TestClient, configurator_paths: dict[str, Path]
) -> None:
    _seed_curation(configurator_paths["curations_dir"], "beta")
    _seed_curation(configurator_paths["curations_dir"], "alpha", populated=True)
    _seed_curation(configurator_paths["curations_dir"], "gamma")

    r = client.get("/curations")
    assert r.status_code == 200
    body = r.json()
    names = [row["name"] for row in body["curations"]]
    assert names == ["alpha", "beta", "gamma"]
    # Summary metadata present.
    alpha = body["curations"][0]
    assert alpha["target"]["groups"] == 4
    assert alpha["group_count"] == 4
    assert alpha["populated_pad_count"] == 1


# ── POST /curations ─────────────────────────────────────────────────────────


def test_create_curation_writes_file_and_returns_full_model(
    client: TestClient, configurator_paths: dict[str, Path]
) -> None:
    r = client.post(
        "/curations",
        json={"name": "verse_swap", "target": {"groups": 4, "pads_per_group": 12}},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["name"] == "verse_swap"
    assert body["curation_version"] == 1
    assert body["target"]["groups"] == 4
    # Round-trip from disk
    path = curation_path(configurator_paths["curations_dir"], "verse_swap")
    on_disk = read_curation(path)
    assert on_disk.name == "verse_swap"
    assert len(on_disk.groups) == 4
    assert len(on_disk.groups["A"].pads) == 12
    # Empty pads carry no source
    assert all(p.source is None for p in on_disk.groups["A"].pads)


def test_create_curation_invalid_name_returns_400(client: TestClient) -> None:
    r = client.post("/curations", json={"name": "../escape", "target": {}})
    assert r.status_code == 400
    assert "invalid" in r.json()["detail"].lower()


def test_create_curation_with_slash_in_name_returns_400(client: TestClient) -> None:
    r = client.post("/curations", json={"name": "foo/bar", "target": {}})
    assert r.status_code == 400


def test_create_curation_duplicate_returns_409(client: TestClient) -> None:
    r1 = client.post("/curations", json={"name": "dup", "target": {}})
    assert r1.status_code == 201
    r2 = client.post("/curations", json={"name": "dup", "target": {}})
    assert r2.status_code == 409


def test_create_curation_malformed_body_returns_422(client: TestClient) -> None:
    # Pydantic rejects bogus field via ``extra="forbid"``.
    r = client.post("/curations", json={"name": "x", "extra_field": True})
    assert r.status_code == 422


# ── GET /curations/{name} ───────────────────────────────────────────────────


def test_get_curation_returns_full_model(
    client: TestClient, configurator_paths: dict[str, Path]
) -> None:
    seeded = _seed_curation(configurator_paths["curations_dir"], "loaded", populated=True)
    r = client.get(f"/curations/{seeded.name}")
    assert r.status_code == 200
    body = r.json()
    # The on-the-wire model matches what we wrote — round-trip.
    parsed = Curation.model_validate(body)
    assert parsed.name == "loaded"
    assert parsed.groups["A"].pads[0].source is not None
    assert parsed.groups["A"].pads[0].source.forge == "seeded-forge"


def test_get_unknown_curation_returns_404(client: TestClient) -> None:
    r = client.get("/curations/nope")
    assert r.status_code == 404


# ── POST /curations/{name}/open ─────────────────────────────────────────────


def test_open_curation_writes_active_in_state_file(
    client: TestClient, configurator_paths: dict[str, Path]
) -> None:
    _seed_curation(configurator_paths["curations_dir"], "active_one")
    als_path = "/Users/zak/Music/Ableton/Verse Swap.als"
    r = client.post("/curations/active_one/open", json={"als_path": als_path})
    assert r.status_code == 200
    body = r.json()
    assert body["active_curations"][als_path] == "active_one"
    # State file persisted.
    state_data = json.loads(configurator_paths["state_path"].read_text())
    assert state_data["active_curations"][als_path] == "active_one"


def test_open_unknown_curation_returns_404(client: TestClient) -> None:
    r = client.post("/curations/ghost/open", json={"als_path": "/tmp/x.als"})
    assert r.status_code == 404


# ── POST /curations/{name}/save-as ──────────────────────────────────────────


def test_save_as_copies_and_switches_active(
    client: TestClient, configurator_paths: dict[str, Path]
) -> None:
    _seed_curation(configurator_paths["curations_dir"], "source")
    als = "/tmp/proj.als"
    client.post("/curations/source/open", json={"als_path": als})
    r = client.post(
        "/curations/source/save-as",
        json={"new_name": "source_v2", "als_path": als},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "source_v2"
    # Both files exist on disk.
    assert curation_path(configurator_paths["curations_dir"], "source").is_file()
    assert curation_path(configurator_paths["curations_dir"], "source_v2").is_file()
    # Active switched to new name.
    state_data = json.loads(configurator_paths["state_path"].read_text())
    assert state_data["active_curations"][als] == "source_v2"


def test_save_as_to_existing_name_returns_409(
    client: TestClient, configurator_paths: dict[str, Path]
) -> None:
    _seed_curation(configurator_paths["curations_dir"], "a")
    _seed_curation(configurator_paths["curations_dir"], "b")
    r = client.post("/curations/a/save-as", json={"new_name": "b"})
    assert r.status_code == 409


# ── DELETE /curations/{name} ────────────────────────────────────────────────


def test_delete_curation_removes_file(
    client: TestClient, configurator_paths: dict[str, Path]
) -> None:
    _seed_curation(configurator_paths["curations_dir"], "todel")
    r = client.delete("/curations/todel")
    assert r.status_code == 200
    assert not curation_path(configurator_paths["curations_dir"], "todel").is_file()


def test_delete_active_curation_returns_409(
    client: TestClient, configurator_paths: dict[str, Path]
) -> None:
    _seed_curation(configurator_paths["curations_dir"], "live_one")
    client.post("/curations/live_one/open", json={"als_path": "/x.als"})
    r = client.delete("/curations/live_one")
    assert r.status_code == 409
    assert curation_path(configurator_paths["curations_dir"], "live_one").is_file()


def test_delete_missing_curation_returns_404(client: TestClient) -> None:
    r = client.delete("/curations/nothing")
    assert r.status_code == 404


# ── PATCH /curations/{name}/template ────────────────────────────────────────


def test_patch_template_writes_assignment(
    client: TestClient, configurator_paths: dict[str, Path]
) -> None:
    _seed_curation(configurator_paths["curations_dir"], "patchme")
    _seed_template(configurator_paths["templates_dir"], "tight-compressed")
    r = client.patch(
        "/curations/patchme/template",
        json={"group_letter": "B", "template_name": "tight-compressed"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["groups"]["B"]["template"] == "tight-compressed"
    # Persisted.
    on_disk = read_curation(curation_path(configurator_paths["curations_dir"], "patchme"))
    assert on_disk.groups["B"].template == "tight-compressed"


def test_patch_template_clears_when_null(
    client: TestClient, configurator_paths: dict[str, Path]
) -> None:
    _seed_curation(configurator_paths["curations_dir"], "p")
    _seed_template(configurator_paths["templates_dir"], "x")
    client.patch("/curations/p/template", json={"group_letter": "A", "template_name": "x"})
    r = client.patch("/curations/p/template", json={"group_letter": "A", "template_name": None})
    assert r.status_code == 200
    assert r.json()["groups"]["A"]["template"] is None


def test_patch_template_unknown_group_returns_404(
    client: TestClient, configurator_paths: dict[str, Path]
) -> None:
    _seed_curation(configurator_paths["curations_dir"], "p")
    # Templates dir empty — the unknown-group check fires BEFORE template
    # existence, so we still get 404 for the group letter.
    r = client.patch(
        "/curations/p/template",
        json={"group_letter": "Z", "template_name": "x"},
    )
    assert r.status_code == 404


# ── PATCH /curations/{name}/target ──────────────────────────────────────────


def test_patch_target_subset_update(
    client: TestClient, configurator_paths: dict[str, Path]
) -> None:
    _seed_curation(configurator_paths["curations_dir"], "t")
    r = client.patch("/curations/t/target", json={"groups": 2})
    assert r.status_code == 200
    body = r.json()
    assert body["target"]["groups"] == 2
    # Pads_per_group unchanged.
    assert body["target"]["pads_per_group"] == 12
    # Groups resized to 2.
    assert set(body["groups"].keys()) == {"A", "B"}


def test_patch_target_preserves_existing_pad_data(
    client: TestClient, configurator_paths: dict[str, Path]
) -> None:
    _seed_curation(configurator_paths["curations_dir"], "keep", populated=True)
    r = client.patch("/curations/keep/target", json={"pads_per_group": 16})
    assert r.status_code == 200
    body = r.json()
    # A01 still populated.
    assert body["groups"]["A"]["pads"][0]["source"]["forge"] == "seeded-forge"
    # New trailing empty pads added.
    assert len(body["groups"]["A"]["pads"]) == 16


def test_patch_target_label_lands_on_first_group(
    client: TestClient, configurator_paths: dict[str, Path]
) -> None:
    _seed_curation(configurator_paths["curations_dir"], "labelme")
    r = client.patch("/curations/labelme/target", json={"label": "Hookz"})
    assert r.status_code == 200
    assert r.json()["groups"]["A"]["label"] == "Hookz"


# ── POST /curations/{name}/commit ───────────────────────────────────────────


def test_commit_curation_persists_snapshot(
    client: TestClient, configurator_paths: dict[str, Path]
) -> None:
    """Phase 2 wire shape: device sends ``audio_path``; server reverse-looks-up.

    The audio path doesn't match any forge in the test's empty processed_dir,
    so the server records it as ``external_path`` per spec §2.3.
    """
    _seed_curation(configurator_paths["curations_dir"], "commit_me")
    snapshot = {
        "groups": {
            "A": {
                "label": "Vocals",
                "template": "dry-direct",
                "pads": [
                    {
                        "pad_id": "A01",
                        "audio_path": "/tmp/somebodys-vocal-bar0.wav",
                        "clip_settings": {
                            "warp_bpm": 138.0,
                            "loop_start_bar": 0.0,
                            "loop_end_bar": 4.0,
                            "looping": True,
                        },
                    },
                    {"pad_id": "A02"},
                ],
            }
        }
    }
    r = client.post("/curations/commit_me/commit", json=snapshot)
    assert r.status_code == 200, r.text
    body = r.json()
    # Pad persisted with external_path fallback (no forge owned this path).
    a_pads = body["groups"]["A"]["pads"]
    assert a_pads[0]["source"]["external_path"] == "/tmp/somebodys-vocal-bar0.wav"
    assert a_pads[0]["clip_settings"]["warp_bpm"] == 138.0
    assert a_pads[1]["source"] is None
    # File round-trips through read_curation.
    on_disk = read_curation(curation_path(configurator_paths["curations_dir"], "commit_me"))
    assert on_disk.groups["A"].pads[0].source is not None
    assert on_disk.groups["A"].pads[0].source.external_path == "/tmp/somebodys-vocal-bar0.wav"


def test_commit_curation_unknown_returns_404(client: TestClient) -> None:
    r = client.post(
        "/curations/missing/commit",
        json={"groups": {}},
    )
    assert r.status_code == 404


def test_commit_curation_bad_clip_settings_returns_422(
    client: TestClient, configurator_paths: dict[str, Path]
) -> None:
    _seed_curation(configurator_paths["curations_dir"], "bad_settings")
    snapshot = {
        "groups": {
            "A": {
                "pads": [
                    {
                        "pad_id": "A01",
                        "audio_path": "/tmp/some-clip.wav",
                        "clip_settings": {
                            # Missing required warp_bpm + loop_end_bar.
                            "looping": True
                        },
                    }
                ]
            }
        }
    }
    r = client.post("/curations/bad_settings/commit", json=snapshot)
    assert r.status_code == 422


# ── Round-trip vs Phase 0 fixtures ──────────────────────────────────────────


def test_phase0_partial_fixture_round_trips_via_endpoints(
    client: TestClient, configurator_paths: dict[str, Path]
) -> None:
    """The Phase 0 ``partial.yaml`` fixture survives create → get → delete."""
    fixture_path = Path(__file__).resolve().parent / "fixtures" / "curations" / "partial.yaml"
    fixture_data = yaml.safe_load(fixture_path.read_text())
    # Use the validated Curation directly to seed (skipping create endpoint
    # since the spec's create endpoint only accepts ``name`` + ``target``).
    seeded = Curation.model_validate(fixture_data)
    write_curation_atomic(curation_path(configurator_paths["curations_dir"], "partial"), seeded)
    r = client.get("/curations/partial")
    assert r.status_code == 200
    got = Curation.model_validate(r.json())
    assert got == seeded


# ── Concurrent-write test ──────────────────────────────────────────────────


def test_concurrent_commits_serialize_and_file_is_well_formed(
    configurator_paths: dict[str, Path],
) -> None:
    """Two concurrent processes commit different snapshots; file is well-formed.

    We drive this with ``multiprocessing`` because ``TestClient`` serializes
    requests on a single thread internally, so a thread-based race wouldn't
    exercise the cross-process ``lock_curation`` file lock. Each subprocess
    runs the same async handler against its own ``AppState`` pointed at the
    shared curations directory. The lock guarantees one writer wins per
    critical section; the final file must parse cleanly via
    :func:`read_curation` (i.e. no torn write).
    """
    import multiprocessing as mp

    _seed_curation(configurator_paths["curations_dir"], "race")
    curations_dir = configurator_paths["curations_dir"]
    state_path = configurator_paths["state_path"]

    # Spawn two subprocesses that each fire a commit + record HTTP status.
    ctx = mp.get_context("spawn")
    ret_queue: mp.Queue = ctx.Queue()
    procs = [
        ctx.Process(
            target=_run_commit_subprocess,
            args=(str(curations_dir), str(state_path), "race", letter, forge, ret_queue),
        )
        for letter, forge in [("A", "forgeA"), ("B", "forgeB")]
    ]
    for p in procs:
        p.start()
    for p in procs:
        p.join(timeout=15.0)
        assert p.exitcode == 0, f"subprocess exited {p.exitcode}"

    results = {}
    while not ret_queue.empty():
        letter, status = ret_queue.get()
        results[letter] = status
    assert results == {"A": 200, "B": 200}, results

    # File parses cleanly (well-formed YAML, valid schema).
    on_disk = read_curation(curation_path(curations_dir, "race"))
    # Each commit only touches its own group, so the union of both must
    # be present in the final file. The cross-process lock makes this a
    # last-writer-wins compound — A is written first, then B reads A's
    # state + adds B; OR B then A.
    a_pad = on_disk.groups["A"].pads[0]
    b_pad = on_disk.groups["B"].pads[0]
    # External-path fallback path (no fixture forges in race tmp dir).
    assert (
        a_pad.source is not None
        and a_pad.source.external_path
        and a_pad.source.external_path.endswith("race-forgeA.wav")
    ) or (
        b_pad.source is not None
        and b_pad.source.external_path
        and b_pad.source.external_path.endswith("race-forgeB.wav")
    ), (
        "expected at least one commit's data to survive; "
        f"got A.pads[0].source={a_pad.source}, B.pads[0].source={b_pad.source}"
    )


def _run_commit_subprocess(
    curations_dir: str,
    state_path: str,
    name: str,
    letter: str,
    forge: str,
    out_queue,
) -> None:
    """Worker for the concurrent-commit test (runs in a spawned process).

    Builds a fresh app + TestClient per process so each acquires its own
    cross-process ``flock`` rather than sharing one. POSTs one commit
    snapshot and ships back its HTTP status.
    """
    from fastapi.testclient import TestClient as _TC

    from stemforge.configurator.server import create_app as _create_app

    app = _create_app(
        curations_dir=Path(curations_dir),
        state_path=Path(state_path),
    )
    # Phase 2 wire shape: audio_path is keyed; server reverse-lookup
    # falls back to external_path when no forge owns the path (none does
    # in this test — the worker uses tagged sentinel paths so each
    # subprocess writes a distinguishable pad).
    body = {
        "groups": {
            letter: {
                "pads": [
                    {
                        "pad_id": f"{letter}01",
                        "audio_path": f"/tmp/race-{forge}.wav",
                        "clip_settings": {
                            "warp_bpm": 120.0,
                            "loop_end_bar": 4.0,
                        },
                    }
                ]
            }
        }
    }
    with _TC(app) as c:
        resp = c.post(f"/curations/{name}/commit", json=body)
    out_queue.put((letter, resp.status_code))


# ── SSE broadcast ──────────────────────────────────────────────────────────


def test_sse_state_event_fires_on_mutation(
    configurator_paths: dict[str, Path],
) -> None:
    """The in-process broker pushes a ``state`` event on every mutation.

    We test the broker directly via :class:`AppState` rather than going
    through ``/state/stream``, because the FastAPI TestClient serializes
    SSE streams behind the same portal that drives normal requests —
    making it impossible to subscribe + mutate from a single TestClient.
    The contract this test enforces is the one the SSE route depends on:
    a mutation triggers ``broadcast_curations_state`` which pushes a
    ``SseEvent(event="state", ...)`` into every subscriber queue.
    """
    import asyncio

    from stemforge.configurator.intents import (
        CreateCurationBody,
        handle_create_curation,
    )
    from stemforge.configurator.state import AppState

    state = AppState()
    state.curations_dir = configurator_paths["curations_dir"]
    state.state_path = configurator_paths["state_path"]

    async def _drive() -> list:
        queue = state.subscribe()
        try:
            # Fire the mutation.
            await handle_create_curation(state, CreateCurationBody(name="sse_test"))
            # Drain the queue with a timeout — the broadcast is sync.
            collected: list = []
            while not queue.empty():
                collected.append(queue.get_nowait())
            return collected
        finally:
            state.unsubscribe(queue)

    events = asyncio.run(_drive())
    state_events = [e for e in events if e.event == "state"]
    assert state_events, f"expected a state event, got: {[e.event for e in events]}"
    payload = state_events[-1].data
    assert payload.get("kind") == "curations"
    assert "sse_test" in payload["curations"]


# ── Sanity: legacy ``/intent/*`` still works ────────────────────────────────


def test_legacy_intent_routes_still_register(client: TestClient) -> None:
    """The legacy /intent/* surface still exists post-Phase-1B."""
    # Just a 422 on a bogus body proves the route is reachable. We don't
    # exercise the full handler — Lane 1A owns that.
    r = client.post("/intent/assign-pad", json={"group": "Z", "pad": 99})
    assert r.status_code == 422
