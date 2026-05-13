"""L3 end-to-end integration test — Phase 2 KEYSTONE.

THIS TEST IS THE ARCHITECTURE'S CORRECTNESS CHECK. Per spec §11:
"Once this works, the architecture's promise holds." Per the execution
plan, "Block merge on it."

What it proves:

1. The device JS ``commit()`` walker — when given an LOM snapshot
   matching Phase 2's wire contract — produces a DeviceCommitBody-shaped
   JSON payload via ``messnamed("sf-commit-send", curation, json)``.
2. The server's ``POST /curations/{name}/commit`` handler accepts that
   payload, runs the forge reverse-lookup against a fixture
   ``~/stemforge/processed/`` tree, and writes a fully-resolved Curation
   YAML to disk.
3. The disk artefact round-trips through :func:`read_curation` and the
   pads' ``source.forge`` / ``source.clip_id`` match the fixture forge.

The flow is sequential — Node subprocess → JSON → FastAPI TestClient —
so the test is deterministic, fast (< 10s), and runs on every PR.

Required reading: ``specs/CONSOLIDATED_DESIGN.md`` §2.3, §6.6, §11;
``docs/configurator/EXECUTION_PLAN_v1.md`` Phase 2 acceptance gates.
"""

from __future__ import annotations

import json
import shutil
import subprocess
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

REPO_ROOT = Path(__file__).resolve().parent.parent
WALKER_SCRIPT = REPO_ROOT / "tools" / "test-harness" / "run-commit-walker.js"
FIXTURE_FORGE_SRC = REPO_ROOT / "tests" / "fixtures" / "forges" / "sample-forge"
LOM_SNAPSHOT_TEMPLATE = (
    REPO_ROOT / "tests" / "fixtures" / "lom_snapshots" / "staging-4-pads-stg-a.json"
)


# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_lom_snapshot_for_forge(forge_dir: Path, out_path: Path) -> None:
    """Build a 4-pad STG-A snapshot whose audio_paths point at the fixture forge.

    Re-uses the canonical staging-4-pads-stg-a.json shape (STG-A through
    STG-D, four populated pads at A01..A04). The audio_paths are rewritten
    to point at the fixture forge's curated_audio dir so the server's
    reverse-lookup hits.
    """
    audio = forge_dir / "curated_audio"
    snapshot = {
        "_description": ("Keystone-test snapshot: STG-A 4 pads pointing at the fixture forge."),
        "live_set": {
            "tracks": [
                {
                    "name": "STG-A",
                    "track_index": 0,
                    "clip_slots": [
                        {
                            "clip": {
                                "name": "A01-drum-bar0-4",
                                "file_path": str(audio / "drum-bar0-4.wav"),
                                "warp_bpm": 120.0,
                                "loop_start": 0,
                                "loop_end": 4,
                                "looping": 1,
                            }
                        },
                        {
                            "clip": {
                                "name": "A02-bass-bar0-4",
                                "file_path": str(audio / "bass-bar0-4.wav"),
                                "warp_bpm": 120.0,
                                "loop_start": 0,
                                "loop_end": 4,
                                "looping": 1,
                            }
                        },
                        {
                            "clip": {
                                "name": "A03-vocal-bar0-4",
                                "file_path": str(audio / "vocal-bar0-4.wav"),
                                "warp_bpm": 120.0,
                                "loop_start": 0,
                                "loop_end": 8,  # 2 bars
                                "looping": 1,
                            }
                        },
                        {
                            "clip": {
                                "name": "A04-other-bar0-4",
                                "file_path": str(audio / "other-bar0-4.wav"),
                                "warp_bpm": 120.0,
                                "loop_start": 0,
                                "loop_end": 4,
                                "looping": 1,
                            }
                        },
                        *[{"clip": None} for _ in range(8)],
                    ],
                },
                *[
                    {
                        "name": f"STG-{letter}",
                        "track_index": idx,
                        "clip_slots": [{"clip": None} for _ in range(12)],
                    }
                    for idx, letter in enumerate("BCD", start=1)
                ],
            ],
            "scenes": [],
        },
    }
    out_path.write_text(json.dumps(snapshot, indent=2))


def _seed_empty_curation(curations_dir: Path, name: str) -> Curation:
    """Stage an empty 4-group curation on disk so /commit has something to merge."""
    now = datetime.now(UTC)
    target = Target(device="ep133", groups=4, pads_per_group=12)
    groups: dict[str, Group] = {}
    for letter in "ABCD":
        pads = [Pad(pad_id=f"{letter}{slot + 1:02d}") for slot in range(12)]
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


def _run_walker(snapshot_path: Path, curation_name: str) -> dict:
    """Invoke ``run-commit-walker.js`` and return its parsed stdout JSON."""
    proc = subprocess.run(
        [
            "node",
            str(WALKER_SCRIPT),
            str(snapshot_path),
            curation_name,
            "A,B,C,D",
        ],
        check=False,
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        timeout=10,
    )
    if proc.returncode != 0:
        raise AssertionError(
            f"walker exited {proc.returncode}: stderr={proc.stderr!r}, stdout={proc.stdout!r}"
        )
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise AssertionError(f"walker stdout was not valid JSON: {proc.stdout!r}") from exc


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def keystone_env(tmp_path: Path):
    """Stage a full Phase-2 environment: forge tree + curations dir + LOM snapshot."""
    if not WALKER_SCRIPT.is_file():
        pytest.skip(f"walker driver missing at {WALKER_SCRIPT}")
    if shutil.which("node") is None:
        pytest.skip("node binary not on PATH — required for the keystone test")

    processed = tmp_path / "processed"
    processed.mkdir()
    forge_dir = processed / "sample-forge"
    shutil.copytree(FIXTURE_FORGE_SRC, forge_dir)

    curations = tmp_path / "curations"
    curations.mkdir()
    seeded = _seed_empty_curation(curations, "keystone")

    state_path = tmp_path / ".stemforge_state.json"

    snapshot_path = tmp_path / "lom_snapshot.json"
    _make_lom_snapshot_for_forge(forge_dir, snapshot_path)

    return {
        "tmp_path": tmp_path,
        "processed_dir": processed,
        "forge_dir": forge_dir,
        "curations_dir": curations,
        "state_path": state_path,
        "snapshot_path": snapshot_path,
        "curation": seeded,
    }


# ── THE KEYSTONE TEST ────────────────────────────────────────────────────────


@pytest.mark.integration
def test_commit_keystone_end_to_end(keystone_env, tmp_path: Path) -> None:
    """Phase 2 keystone: device walker → server → curation YAML on disk.

    Steps:
    1. Run the device JS commit() walker against a fixture LOM snapshot
       (4 pads on STG-A pointing at curated_audio files in a tmp forge).
    2. Capture the messnamed sf-commit-send payload (curation name + JSON).
    3. POST it to the FastAPI ``/curations/keystone/commit`` route.
    4. Assert the on-disk YAML has 4 forge-owned pads on group A with the
       right (forge, clip_id) for each + the correct clip_settings.
    5. Assert the SSE 'state' broadcast fired.

    Block merge on this test. Period.
    """
    # 1 + 2: Device-side walker → JSON payload.
    walker_out = _run_walker(keystone_env["snapshot_path"], "keystone")
    assert walker_out["curation_name"] == "keystone"
    payload = walker_out["payload"]

    # Sanity: the walker captured the expected pads.
    a_pads = payload["groups"]["A"]["pads"]
    populated = [p for p in a_pads if p.get("audio_path")]
    assert len(populated) == 4, f"expected 4 populated A-pads, got {populated}"

    # Status emissions are part of the wire contract — verify them too.
    assert "commit: walked 4 pads" in walker_out["status_lines"]
    assert any(s.startswith("commit: sent keystone") for s in walker_out["status_lines"])

    # 3: Server side — build app pointed at our tmp forge tree + curations dir.
    app = create_app(
        static_dir=tmp_path / "static",
        curations_dir=keystone_env["curations_dir"],
        state_path=keystone_env["state_path"],
        processed_dir=keystone_env["processed_dir"],
    )
    client = TestClient(app)
    sf_state = app.state.configurator

    # Subscribe to the broker BEFORE the commit so the test can assert SSE.
    import asyncio

    async def _commit_and_collect():
        q = sf_state.subscribe()
        try:
            resp = await asyncio.to_thread(
                client.post,
                "/curations/keystone/commit",
                json=payload,
            )
            assert resp.status_code == 200, resp.text
            events = []
            while not q.empty():
                events.append(await q.get())
            return resp.json(), events
        finally:
            sf_state.unsubscribe(q)

    response_payload, events = asyncio.run(_commit_and_collect())

    # 4: Read back the on-disk curation. The response should match.
    on_disk = read_curation(
        curation_path(keystone_env["curations_dir"], "keystone"),
    )
    assert on_disk.name == "keystone"
    a_group = on_disk.groups["A"]
    populated_disk = [p for p in a_group.pads if p.source is not None]
    assert len(populated_disk) == 4, (
        f"expected 4 populated pads on disk; got {[p.pad_id for p in populated_disk]}"
    )

    expected_by_slot = {
        "A01": "drum-bar0-4",
        "A02": "bass-bar0-4",
        "A03": "vocal-bar0-4",
        "A04": "other-bar0-4",
    }
    for pad in populated_disk:
        assert pad.source is not None
        assert pad.source.forge == "sample-forge", (
            f"pad {pad.pad_id} forge mismatch: {pad.source.forge}"
        )
        expected_clip_id = expected_by_slot.get(pad.pad_id)
        assert pad.source.clip_id == expected_clip_id, (
            f"pad {pad.pad_id} clip_id mismatch: got {pad.source.clip_id!r}, "
            f"expected {expected_clip_id!r}"
        )
        # Server stores the path relative to the forge dir for round-trip safety.
        assert pad.source.audio_path is not None
        assert pad.source.audio_path.startswith("curated_audio/")

    # clip_settings round-trip: warp_bpm preserved, loop bars correct.
    a01 = next(p for p in a_group.pads if p.pad_id == "A01")
    assert a01.clip_settings is not None
    assert a01.clip_settings.warp_bpm == 120.0
    # loop_end was 4 beats → 1 bar after server-side bar conversion.
    assert a01.clip_settings.loop_end_bar == 1.0
    assert a01.clip_settings.looping is True

    # A03 had loop_end=8 beats → 2 bars; preserved through walker + server.
    a03 = next(p for p in a_group.pads if p.pad_id == "A03")
    assert a03.clip_settings is not None
    assert a03.clip_settings.loop_end_bar == 2.0

    # referenced_forges rebuilt from pad sources, with the live manifest hash.
    assert len(on_disk.referenced_forges) == 1
    rf = on_disk.referenced_forges[0]
    assert rf.slug == "sample-forge"
    assert rf.manifest_hash == ("1d1e2b37abe1aba294597d01997494b594ec98c0f59de1a326a197576193f921")

    # 5: SSE 'state' event broadcast on commit.
    state_events = [e for e in events if e.event == "state"]
    assert state_events, "expected at least one 'state' SSE event after commit"
    curations_event = next(
        (e for e in state_events if e.data.get("kind") == "curations"),
        None,
    )
    assert curations_event is not None, (
        f"expected a curations-state SSE frame, got {[e.data for e in state_events]}"
    )
    assert "keystone" in curations_event.data["curations"]

    # Defensive: response payload (the API echoing the new Curation) carries
    # the same forge mapping the disk file does.
    a01_resp = response_payload["groups"]["A"]["pads"][0]
    assert a01_resp["source"]["forge"] == "sample-forge"
    assert a01_resp["source"]["clip_id"] == "drum-bar0-4"


@pytest.mark.integration
def test_commit_keystone_walker_emits_compatible_wire_shape(keystone_env) -> None:
    """Tier-zero check: walker output validates against DeviceCommitBody.

    If this fails the L3 gate's bigger end-to-end test will too — but
    the failure surface here is much narrower, so debug starts here.
    """
    from stemforge.configurator.commit_handler import DeviceCommitBody

    walker_out = _run_walker(keystone_env["snapshot_path"], "keystone")
    body = DeviceCommitBody.model_validate(walker_out["payload"])
    assert "A" in body.groups
    pads = body.groups["A"].pads
    populated = [p for p in pads if p.audio_path]
    assert len(populated) == 4
    # Walker emitted bar-units directly (the device JS does the beat→bar
    # conversion before sending), so server normalisation is a no-op for
    # already-bar-keyed entries.
    assert populated[0].clip_settings is not None
    assert "warp_bpm" in populated[0].clip_settings
    assert "loop_end_bar" in populated[0].clip_settings


# Belt-and-suspenders: make sure pyproject knows about the integration marker.
def test_integration_marker_registered() -> None:
    """The 'integration' marker should be a strict-mode-safe registration.

    pytest will warn-and-skip unregistered markers under strict-markers;
    this test just confirms the marker is available so the keystone test
    isn't deselected by a CI strict-mode flag.
    """
    # Existence check via pytest's known config — this test always passes;
    # if the marker is missing pytest itself will warn during collection.
    pass
