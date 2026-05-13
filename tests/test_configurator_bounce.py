"""Phase 3B BOUNCE refactor — L2 unit + L3 endpoint integration tests.

Covers two boundaries:

* :mod:`stemforge.configurator.bounce_handler` — pure functions
  (``build_bounce_spec``, ``merge_bounce_completion``). Unit-tested
  directly.
* :mod:`stemforge.configurator.server` — ``POST /trigger-bounce`` /
  ``/bounce-progress`` / ``/bounce-complete``. Tested through
  :class:`fastapi.testclient.TestClient`, asserting both the response
  shape and SSE broadcasts.

Spec refs:

- ``specs/CONSOLIDATED_DESIGN.md`` §3.3 (BOUNCE verb)
- ``specs/CONSOLIDATED_DESIGN.md`` §4.3 (endpoints)
- ``specs/CONSOLIDATED_DESIGN.md`` §5.5 (bounce flow)
- ``docs/configurator/EXECUTION_PLAN_v1.md`` Lane 3B acceptance gates
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from stemforge.configurator.bounce_handler import (
    BounceCompletion,
    BounceSpec,
    build_bounce_spec,
    merge_bounce_completion,
)
from stemforge.configurator.curation_io import (
    curation_path,
    read_curation,
    write_curation_atomic,
)
from stemforge.configurator.schemas import (
    ClipSettings,
    Curation,
    Group,
    Pad,
    PadSource,
    Target,
)
from stemforge.configurator.server import create_app


# ── Fixtures ────────────────────────────────────────────────────────────────


def _empty_pad(pad_id: str) -> Pad:
    return Pad(pad_id=pad_id)


def _filled_pad(pad_id: str, clip_id: str) -> Pad:
    return Pad(
        pad_id=pad_id,
        source=PadSource(
            forge="sample-forge",
            clip_id=clip_id,
            audio_path=f"curated_audio/{clip_id}.wav",
        ),
        clip_settings=ClipSettings(
            warp_bpm=120.0,
            loop_start_bar=0.0,
            loop_end_bar=4.0,
            looping=True,
        ),
    )


def _build_curation(
    name: str,
    *,
    populated_specs: dict[str, list[tuple[str, str]]] | None = None,
    templates: dict[str, str | None] | None = None,
) -> Curation:
    """Build a 4-group / 12-pad curation with optional populated pads.

    ``populated_specs`` maps group letter → [(pad_id, clip_id), …].
    Pads not listed are empty placeholders.
    """
    now = datetime.now(UTC)
    target = Target(device="ep133", groups=4, pads_per_group=12)
    groups: dict[str, Group] = {}
    populated_specs = populated_specs or {}
    templates = templates or {}
    for letter in "ABCD":
        filled = dict(populated_specs.get(letter, []))
        pads = []
        for i in range(12):
            pid = f"{letter}{i + 1:02d}"
            if pid in filled:
                pads.append(_filled_pad(pid, filled[pid]))
            else:
                pads.append(_empty_pad(pid))
        groups[letter] = Group(
            label="",
            template=templates.get(letter),
            pads=pads,
        )
    return Curation(
        name=name,
        type="deck",
        created_at=now,
        modified_at=now,
        target=target,
        referenced_forges=[],
        groups=groups,
    )


@pytest.fixture
def tmp_curations(tmp_path: Path) -> dict[str, Path]:
    curations_dir = tmp_path / "curations"
    curations_dir.mkdir()
    state_path = tmp_path / ".stemforge_state.json"
    return {
        "tmp_path": tmp_path,
        "curations_dir": curations_dir,
        "state_path": state_path,
        "static_dir": tmp_path / "static",
        "processed_dir": tmp_path / "processed",
    }


@pytest.fixture
def client(tmp_curations: dict[str, Path]) -> TestClient:
    tmp_curations["processed_dir"].mkdir(parents=True, exist_ok=True)
    app = create_app(
        static_dir=tmp_curations["static_dir"],
        curations_dir=tmp_curations["curations_dir"],
        state_path=tmp_curations["state_path"],
        processed_dir=tmp_curations["processed_dir"],
    )
    return TestClient(app)


# ── build_bounce_spec ────────────────────────────────────────────────────────


def test_build_bounce_spec_empty_curation_returns_no_pads() -> None:
    """An empty curation has no populated pads → spec.pads is empty."""
    curation = _build_curation("empty")
    spec = build_bounce_spec(curation)
    assert isinstance(spec, BounceSpec)
    assert spec.curation_name == "empty"
    assert spec.bounce_dir == "bounced/empty"
    assert spec.manifest_path == "bounced/empty/bounce_manifest.json"
    assert spec.pads == []


def test_build_bounce_spec_partial_curation_returns_only_populated() -> None:
    """Only pads with ``source`` end up in the spec; empty pads are skipped."""
    curation = _build_curation(
        "partial",
        populated_specs={
            "A": [("A01", "vocal-bar0"), ("A03", "vocal-bar4")],
            "B": [("B01", "drum-bar0")],
        },
        templates={"A": "VOCAL_LO_KEY", "B": "DRUM_PUNCH"},
    )
    spec = build_bounce_spec(curation)
    assert len(spec.pads) == 3
    pad_ids = [p.pad_id for p in spec.pads]
    assert pad_ids == ["A01", "A03", "B01"]  # group-major, slot-ascending
    a01 = spec.pads[0]
    assert a01.group == "A"
    assert a01.slot == 1
    assert a01.template == "VOCAL_LO_KEY"
    assert a01.output_path == "bounced/partial/A01.wav"
    a03 = spec.pads[1]
    assert a03.slot == 3
    assert a03.template == "VOCAL_LO_KEY"
    b01 = spec.pads[2]
    assert b01.template == "DRUM_PUNCH"


def test_build_bounce_spec_pad_ids_filter_subsets_the_render() -> None:
    """When ``pad_ids`` is provided, only those pads are rendered."""
    curation = _build_curation(
        "partial",
        populated_specs={
            "A": [("A01", "v0"), ("A02", "v1"), ("A03", "v2")],
            "B": [("B01", "d0")],
        },
    )
    spec = build_bounce_spec(curation, pad_ids=["A01", "A02"])
    assert [p.pad_id for p in spec.pads] == ["A01", "A02"]


def test_build_bounce_spec_accepts_interpunct_pad_ids() -> None:
    """The popup may pass ``A·01`` form; the handler normalizes both ways."""
    curation = _build_curation(
        "partial",
        populated_specs={"A": [("A01", "v0"), ("A02", "v1")]},
    )
    spec = build_bounce_spec(curation, pad_ids=["A·01"])
    assert [p.pad_id for p in spec.pads] == ["A01"]


def test_build_bounce_spec_unknown_pad_ids_silently_skipped() -> None:
    """An unknown filter id doesn't blow up — it just shrinks the spec."""
    curation = _build_curation(
        "partial",
        populated_specs={"A": [("A01", "v0")]},
    )
    spec = build_bounce_spec(curation, pad_ids=["B99", "A01"])
    assert [p.pad_id for p in spec.pads] == ["A01"]


# ── merge_bounce_completion ──────────────────────────────────────────────────


def test_merge_bounce_completion_populates_last_bounce() -> None:
    curation = _build_curation(
        "verse_swap_v1",
        populated_specs={"A": [("A01", "v0"), ("A02", "v1")]},
    )
    bounced_at = datetime(2026, 5, 13, 12, 30, tzinfo=UTC)
    completion = BounceCompletion(
        manifest_path="bounced/verse_swap_v1/bounce_manifest.json",
        pad_audio_hashes={"A01": "a" * 64, "A02": "b" * 64},
        bounced_at=bounced_at,
    )
    merged = merge_bounce_completion(existing=curation, completion=completion)
    assert merged.last_bounce is not None
    assert merged.last_bounce.bounced_at == bounced_at
    assert merged.last_bounce.manifest_path == "bounced/verse_swap_v1/bounce_manifest.json"
    assert merged.last_bounce.pad_audio_hashes == {
        "A01": "a" * 64,
        "A02": "b" * 64,
    }
    # modified_at bumped to match the bounce timestamp.
    assert merged.modified_at == bounced_at


def test_merge_bounce_completion_stamps_now_when_no_timestamp() -> None:
    curation = _build_curation("k", populated_specs={"A": [("A01", "v0")]})
    completion = BounceCompletion(
        manifest_path="bounced/k/bounce_manifest.json",
        pad_audio_hashes={"A01": "c" * 64},
    )
    before = datetime.now(UTC)
    merged = merge_bounce_completion(existing=curation, completion=completion)
    after = datetime.now(UTC)
    assert merged.last_bounce is not None
    assert before <= merged.last_bounce.bounced_at <= after


def test_merge_bounce_completion_canonicalizes_pad_ids() -> None:
    """Interpunct pad ids in completion get normalized to canonical form."""
    curation = _build_curation("k", populated_specs={"A": [("A01", "v0")]})
    completion = BounceCompletion(
        manifest_path="bounced/k/bounce_manifest.json",
        pad_audio_hashes={"A·01": "e" * 64},
    )
    merged = merge_bounce_completion(existing=curation, completion=completion)
    assert merged.last_bounce is not None
    assert "A01" in merged.last_bounce.pad_audio_hashes
    assert "A·01" not in merged.last_bounce.pad_audio_hashes


# ── POST /curations/{name}/trigger-bounce ────────────────────────────────────


def test_trigger_bounce_404_for_unknown_curation(client: TestClient) -> None:
    resp = client.post("/curations/does-not-exist/trigger-bounce", json={})
    assert resp.status_code == 404


def test_trigger_bounce_400_for_empty_curation(
    client: TestClient, tmp_curations: dict[str, Path]
) -> None:
    """A curation with no populated pads → 400 (nothing to render)."""
    empty = _build_curation("empty")
    write_curation_atomic(curation_path(tmp_curations["curations_dir"], "empty"), empty)
    resp = client.post("/curations/empty/trigger-bounce", json={})
    assert resp.status_code == 400
    assert "no pads to bounce" in resp.json()["detail"]


def test_trigger_bounce_returns_spec_and_broadcasts_sse(
    client: TestClient, tmp_curations: dict[str, Path]
) -> None:
    """A populated curation returns the spec + broadcasts ``bounce-start``."""
    populated = _build_curation(
        "verse_swap_v1",
        populated_specs={
            "A": [("A01", "v0"), ("A02", "v1")],
            "B": [("B01", "d0")],
        },
        templates={"A": "VOCAL_LO_KEY"},
    )
    write_curation_atomic(curation_path(tmp_curations["curations_dir"], "verse_swap_v1"), populated)

    app = client.app  # type: ignore[attr-defined]
    sf_state = app.state.configurator

    async def _trigger_and_collect():
        q = sf_state.subscribe()
        try:
            resp = await asyncio.to_thread(
                client.post,
                "/curations/verse_swap_v1/trigger-bounce",
                json={},
            )
            assert resp.status_code == 200, resp.text
            events = []
            while not q.empty():
                events.append(await q.get())
            return resp.json(), events
        finally:
            sf_state.unsubscribe(q)

    response_payload, events = asyncio.run(_trigger_and_collect())

    # Response payload carries the spec for popup UI.
    assert response_payload["ok"] is True
    spec = response_payload["spec"]
    assert spec["curation_name"] == "verse_swap_v1"
    assert spec["bounce_dir"] == "bounced/verse_swap_v1"
    assert len(spec["pads"]) == 3
    assert [p["pad_id"] for p in spec["pads"]] == ["A01", "A02", "B01"]
    assert spec["pads"][0]["template"] == "VOCAL_LO_KEY"
    # SSE: bounce-start event went out for the device's listener.
    bounce_starts = [
        e for e in events if e.event == "state" and e.data.get("kind") == "bounce-start"
    ]
    assert len(bounce_starts) == 1
    assert bounce_starts[0].data["curation"] == "verse_swap_v1"
    assert len(bounce_starts[0].data["spec"]["pads"]) == 3


def test_trigger_bounce_pad_ids_filter_propagates(
    client: TestClient, tmp_curations: dict[str, Path]
) -> None:
    """``pad_ids`` body filter shrinks the returned spec accordingly."""
    populated = _build_curation(
        "filtered",
        populated_specs={"A": [("A01", "v0"), ("A02", "v1"), ("A03", "v2")]},
    )
    write_curation_atomic(curation_path(tmp_curations["curations_dir"], "filtered"), populated)
    resp = client.post(
        "/curations/filtered/trigger-bounce",
        json={"pad_ids": ["A01", "A03"]},
    )
    assert resp.status_code == 200, resp.text
    spec = resp.json()["spec"]
    assert [p["pad_id"] for p in spec["pads"]] == ["A01", "A03"]


# ── POST /curations/{name}/bounce-progress ───────────────────────────────────


def test_bounce_progress_emits_sse_progress_event(
    client: TestClient, tmp_curations: dict[str, Path]
) -> None:
    """Per-pad device beacon rebroadcasts as an SSE ``progress`` event."""
    populated = _build_curation(
        "progressing",
        populated_specs={"A": [("A01", "v0"), ("A02", "v1")]},
    )
    write_curation_atomic(curation_path(tmp_curations["curations_dir"], "progressing"), populated)
    app = client.app  # type: ignore[attr-defined]
    sf_state = app.state.configurator

    async def _post_and_collect():
        q = sf_state.subscribe()
        try:
            resp = await asyncio.to_thread(
                client.post,
                "/curations/progressing/bounce-progress",
                json={
                    "pad_id": "A01",
                    "rendered_count": 1,
                    "total_count": 2,
                    "output_path": "bounced/progressing/A01.wav",
                },
            )
            events = []
            while not q.empty():
                events.append(await q.get())
            return resp, events
        finally:
            sf_state.unsubscribe(q)

    resp, events = asyncio.run(_post_and_collect())
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body == {"ok": True, "rendered": 1, "total": 2}
    progress_events = [e for e in events if e.event == "progress"]
    assert len(progress_events) == 1
    assert progress_events[0].data["op"] == "bounce:progressing"
    assert 0.0 < progress_events[0].data["progress"] < 1.0


def test_bounce_progress_404_for_unknown_curation(client: TestClient) -> None:
    resp = client.post(
        "/curations/nope/bounce-progress",
        json={"pad_id": "A01", "rendered_count": 0, "total_count": 1},
    )
    assert resp.status_code == 404


# ── POST /curations/{name}/bounce-complete ───────────────────────────────────


def test_bounce_complete_writes_last_bounce_and_broadcasts(
    client: TestClient, tmp_curations: dict[str, Path]
) -> None:
    """The full flow: trigger → complete → curation YAML has last_bounce."""
    populated = _build_curation(
        "verse_swap_v1",
        populated_specs={
            "A": [("A01", "v0"), ("A02", "v1")],
        },
    )
    path = curation_path(tmp_curations["curations_dir"], "verse_swap_v1")
    write_curation_atomic(path, populated)

    app = client.app  # type: ignore[attr-defined]
    sf_state = app.state.configurator

    async def _complete_and_collect():
        q = sf_state.subscribe()
        try:
            resp = await asyncio.to_thread(
                client.post,
                "/curations/verse_swap_v1/bounce-complete",
                json={
                    "manifest_path": "bounced/verse_swap_v1/bounce_manifest.json",
                    "pad_audio_hashes": {"A01": "a" * 64, "A02": "b" * 64},
                    "bounced_at": "2026-05-13T12:30:00+00:00",
                },
            )
            events = []
            while not q.empty():
                events.append(await q.get())
            return resp, events
        finally:
            sf_state.unsubscribe(q)

    resp, events = asyncio.run(_complete_and_collect())
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["last_bounce"]["pad_audio_hashes"] == {
        "A01": "a" * 64,
        "A02": "b" * 64,
    }

    # Disk: curation file has last_bounce populated.
    on_disk = read_curation(path)
    assert on_disk.last_bounce is not None
    assert on_disk.last_bounce.manifest_path == ("bounced/verse_swap_v1/bounce_manifest.json")
    assert on_disk.last_bounce.pad_audio_hashes["A01"] == "a" * 64

    # SSE: a curation-state broadcast went out so the popup re-renders.
    curation_states = [
        e for e in events if e.event == "state" and e.data.get("kind") == "curations"
    ]
    assert len(curation_states) >= 1


def test_bounce_complete_404_for_unknown_curation(client: TestClient) -> None:
    resp = client.post(
        "/curations/nope/bounce-complete",
        json={
            "manifest_path": "bounced/nope/bounce_manifest.json",
            "pad_audio_hashes": {},
        },
    )
    assert resp.status_code == 404
