"""Forge endpoint tests (Phase 1.5 bridge, spec §4.3).

Covers ``GET /forges`` discovery + ``POST /forges/{slug}/{load,unload,
re-anchor,re-curate,reveal}``. Each test spins up an isolated server
against ``tmp_path`` so the user's real ``~/stemforge`` is never touched;
``subprocess_runner`` is stubbed so re-anchor / re-curate / reveal calls
don't shell out to the real CLI.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from stemforge.configurator.schemas import (
    ArrangementChunk,
    ArrangementManifest,
    ForgeClip,
    ForgeManifest,
    compute_manifest_hash,
)
from stemforge.configurator.server import create_app
from stemforge.forge.manifest_io import (
    write_arrangement,
    write_auto_curation,
)


# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def configurator_paths(tmp_path: Path) -> dict[str, Path]:
    """Isolated ``~/stemforge`` layout under ``tmp_path``."""
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


def _make_runner_stub(
    *,
    returncode: int = 0,
    stdout: str = "",
    stderr: str = "",
) -> tuple[Callable, list[dict]]:
    """Build a fake ``subprocess.run`` that records each invocation.

    Returns ``(runner, calls)`` — caller asserts against ``calls``.
    """
    calls: list[dict] = []

    def runner(cmd, **kwargs):
        calls.append({"cmd": list(cmd), "kwargs": dict(kwargs)})
        return SimpleNamespace(
            returncode=returncode,
            stdout=stdout,
            stderr=stderr,
        )

    return runner, calls


@pytest.fixture
def client_with_runner(
    configurator_paths: dict[str, Path],
) -> Callable:
    """Factory: build a TestClient with a stub subprocess runner injected."""

    def _build(
        *,
        returncode: int = 0,
        stdout: str = "",
        stderr: str = "",
    ) -> tuple[TestClient, list[dict]]:
        runner, calls = _make_runner_stub(returncode=returncode, stdout=stdout, stderr=stderr)
        app = create_app(
            static_dir=configurator_paths["static_dir"],
            curations_dir=configurator_paths["curations_dir"],
            state_path=configurator_paths["state_path"],
            processed_dir=configurator_paths["processed_dir"],
            subprocess_runner=runner,
        )
        return TestClient(app), calls

    return _build


@pytest.fixture
def client(client_with_runner) -> TestClient:
    """Convenience: TestClient backed by a happy-path stub runner."""
    c, _ = client_with_runner()
    return c


# ── Forge fixture seeding ───────────────────────────────────────────────────


def _seed_new_shape_forge(
    processed_dir: Path,
    slug: str,
    *,
    with_arrangement: bool = True,
    n_clips: int = 3,
    n_chunks: int = 4,
    bpm: float = 120.0,
) -> Path:
    """Create a new-shape forge with auto-curation + arrangement manifests."""
    forge_dir = processed_dir / slug
    forge_dir.mkdir(parents=True, exist_ok=True)
    clips = [
        ForgeClip(
            clip_id=f"clip-{i}",
            audio_path=f"curated_audio/clip-{i}.wav",
            stem="drum",
            source_bar_range=(i * 4, (i + 1) * 4),
            duration_bars=4,
            tags=["loop"],
        )
        for i in range(n_clips)
    ]
    manifest = ForgeManifest(
        schema_version=1,
        forge_slug=slug,
        source_audio=f"/tmp/{slug}.wav",
        bpm=bpm,
        first_downbeat_sec=0.0,
        manifest_hash=compute_manifest_hash([c.model_dump(mode="json") for c in clips]),
        clips=clips,
    )
    write_auto_curation(forge_dir, manifest)
    if with_arrangement:
        chunks = [
            ArrangementChunk(
                chunk_id=f"chunk-{i}",
                audio_path=f"arrangement_chunks/chunk-{i}.wav",
                stem="drum",
                source_position_sec=float(i),
                duration_sec=4.0,
                bar_position=i * 4,
                duration_bars=4,
            )
            for i in range(n_chunks)
        ]
        arrangement = ArrangementManifest(
            schema_version=1,
            forge_slug=slug,
            source_audio=f"/tmp/{slug}.wav",
            bpm=bpm,
            first_downbeat_sec=0.0,
            manifest_hash=compute_manifest_hash([c.model_dump(mode="json") for c in chunks]),
            chunks=chunks,
        )
        write_arrangement(forge_dir, arrangement)
    return forge_dir


def _seed_legacy_forge(processed_dir: Path, slug: str) -> Path:
    """Drop a minimal legacy ``curated/manifest.json`` forge on disk."""
    forge_dir = processed_dir / slug
    (forge_dir / "curated").mkdir(parents=True, exist_ok=True)
    legacy = {
        "forge_slug": slug,
        "source_audio": f"/tmp/{slug}.wav",
        "bpm": 96.0,
        "n_bars": 4,
        "stems": {
            "drums": [
                {"file": f"curated/drums/{slug}_bar0.wav", "position": 1},
                {"file": f"curated/drums/{slug}_bar4.wav", "position": 2},
            ]
        },
    }
    (forge_dir / "curated" / "manifest.json").write_text(json.dumps(legacy))
    return forge_dir


# ── GET /forges ─────────────────────────────────────────────────────────────


def test_list_forges_empty_returns_empty_array(client: TestClient) -> None:
    r = client.get("/forges")
    assert r.status_code == 200
    assert r.json() == {"forges": []}


def test_list_forges_returns_both_shapes_sorted_by_slug(
    client: TestClient,
    configurator_paths: dict[str, Path],
) -> None:
    _seed_new_shape_forge(configurator_paths["processed_dir"], "zebra", n_clips=5, bpm=140.0)
    _seed_new_shape_forge(configurator_paths["processed_dir"], "alpha", n_clips=2)
    _seed_legacy_forge(configurator_paths["processed_dir"], "midnight")

    r = client.get("/forges")
    assert r.status_code == 200
    body = r.json()
    slugs = [e["slug"] for e in body["forges"]]
    assert slugs == ["alpha", "midnight", "zebra"]
    # Field sanity-check on a new-shape entry.
    alpha = next(e for e in body["forges"] if e["slug"] == "alpha")
    assert alpha["name"] == "alpha"
    assert alpha["sample_count"] == 2
    assert alpha["has_arrangement"] is True
    assert alpha["target_format"] == "auto_curation_v1"
    assert alpha["manifest_hash"]
    assert alpha["bar_count"] == 8  # 2 clips × 4 bars
    assert alpha["bpm"] == 120.0
    # Legacy entry advertises target_format=legacy.
    legacy = next(e for e in body["forges"] if e["slug"] == "midnight")
    assert legacy["target_format"] == "legacy"
    assert legacy["has_arrangement"] is False


def test_list_forges_skips_dirs_without_manifests(
    client: TestClient,
    configurator_paths: dict[str, Path],
) -> None:
    # Empty subdir — no manifest, should be skipped.
    (configurator_paths["processed_dir"] / "wip-track").mkdir()
    _seed_new_shape_forge(configurator_paths["processed_dir"], "real")
    r = client.get("/forges")
    slugs = [e["slug"] for e in r.json()["forges"]]
    assert slugs == ["real"]


def test_list_forges_skips_dotdirs(
    client: TestClient,
    configurator_paths: dict[str, Path],
) -> None:
    """Dotfiles + dotdirs are server-internal scratch (e.g. .DS_Store)."""
    hidden = configurator_paths["processed_dir"] / ".hidden-cache"
    hidden.mkdir()
    (hidden / "auto_curation_manifest.json").write_text("{}")
    _seed_new_shape_forge(configurator_paths["processed_dir"], "visible")
    r = client.get("/forges")
    slugs = [e["slug"] for e in r.json()["forges"]]
    assert slugs == ["visible"]


# ── POST /forges/{slug}/load + /unload ──────────────────────────────────────


def test_load_forge_404_when_slug_unknown(client: TestClient) -> None:
    r = client.post("/forges/no-such-forge/load", json={})
    assert r.status_code == 404
    assert "not found" in r.json()["detail"].lower()


def test_load_forge_400_on_dangerous_slug(client: TestClient) -> None:
    """A slug carrying a forbidden token (``..``) must not reach the FS.

    Starlette may reject the route earlier (405) when the URL-encoded
    payload doesn't match any registered path; any non-200 result is
    acceptable — the load-bearing invariant is that the directory was
    never opened/escape-traversed.
    """
    r = client.post("/forges/contains..parent/load", json={})
    # Slug contains ``..`` token → router validator should reject (400)
    # or the resulting dir lookup misses (404). Either is safe.
    assert r.status_code in (400, 404), r.text


def test_load_forge_marks_loaded_and_returns_path(
    client: TestClient,
    configurator_paths: dict[str, Path],
) -> None:
    forge_dir = _seed_new_shape_forge(configurator_paths["processed_dir"], "loadme")
    r = client.post("/forges/loadme/load", json={})
    assert r.status_code == 200
    body = r.json()
    assert body == {"ok": True, "slug": "loadme", "path": str(forge_dir)}


def test_unload_forge_returns_ok(
    client: TestClient,
    configurator_paths: dict[str, Path],
) -> None:
    _seed_new_shape_forge(configurator_paths["processed_dir"], "unloadme")
    # Load then unload.
    client.post("/forges/unloadme/load", json={})
    r = client.post("/forges/unloadme/unload", json={})
    assert r.status_code == 200
    assert r.json() == {"ok": True, "slug": "unloadme"}


def test_load_forge_broadcasts_sse_state(
    configurator_paths: dict[str, Path],
) -> None:
    """Mutating the loaded-forge set emits a ``state`` SSE event.

    We bypass TestClient (which serializes SSE behind its own portal)
    and test the broker directly via :class:`AppState` — same pattern as
    the Phase 1B CRUD SSE test.
    """
    import asyncio

    from stemforge.configurator.server import create_app as _create_app

    runner, _ = _make_runner_stub()
    app = _create_app(
        curations_dir=configurator_paths["curations_dir"],
        state_path=configurator_paths["state_path"],
        processed_dir=configurator_paths["processed_dir"],
        subprocess_runner=runner,
    )
    _seed_new_shape_forge(configurator_paths["processed_dir"], "ssetest")
    state = app.state.configurator

    async def _drive() -> list:
        queue = state.subscribe()
        try:
            # Drive the load handler inline using TestClient to keep
            # request plumbing simple; the broker is in-process so we
            # still see the event in the queue.
            with TestClient(app) as c:
                resp = c.post("/forges/ssetest/load", json={})
                assert resp.status_code == 200
            collected: list = []
            while not queue.empty():
                collected.append(queue.get_nowait())
            return collected
        finally:
            state.unsubscribe(queue)

    events = asyncio.run(_drive())
    state_events = [e for e in events if e.event == "state"]
    assert state_events, f"no state events; got {[e.event for e in events]}"
    forge_events = [e for e in state_events if e.data.get("kind") == "forges"]
    assert forge_events, "expected a forge-state event"
    assert forge_events[-1].data["loaded_forge"] == "ssetest"


# ── POST /forges/{slug}/reveal ──────────────────────────────────────────────


def test_reveal_invokes_open_with_forge_path(
    client_with_runner,
    configurator_paths: dict[str, Path],
) -> None:
    forge_dir = _seed_new_shape_forge(configurator_paths["processed_dir"], "showme")
    client, calls = client_with_runner()
    r = client.post("/forges/showme/reveal", json={})
    assert r.status_code == 200
    assert r.json() == {"ok": True, "path": str(forge_dir)}
    # One ``open`` call with the forge path.
    assert any(call["cmd"][0] == "open" and call["cmd"][1] == str(forge_dir) for call in calls)


def test_reveal_404_when_slug_unknown(client: TestClient) -> None:
    r = client.post("/forges/ghost/reveal", json={})
    assert r.status_code == 404


# ── POST /forges/{slug}/re-anchor ───────────────────────────────────────────


def test_re_anchor_invokes_cli_and_returns_stdout(
    client_with_runner,
    configurator_paths: dict[str, Path],
) -> None:
    forge_dir = _seed_new_shape_forge(configurator_paths["processed_dir"], "shiftme")
    client, calls = client_with_runner(returncode=0, stdout="re-anchor: done\n", stderr="")
    r = client.post(
        "/forges/shiftme/re-anchor",
        json={"first_downbeat_seconds": 0.247, "source_bpm": 138.0},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["slug"] == "shiftme"
    assert "done" in body["stdout"]
    assert body["stderr"] == ""
    # CLI was invoked with the right args.
    cli_calls = [c for c in calls if "re-anchor" in c["cmd"]]
    assert len(cli_calls) == 1
    cmd = cli_calls[0]["cmd"]
    assert cmd[:5] == ["uv", "run", "stemforge", "re-anchor", str(forge_dir)]
    assert "--bpm" in cmd
    assert "138.0" in cmd
    assert "--first-downbeat" in cmd
    assert "0.247" in cmd


def test_re_anchor_accepts_legacy_downbeat_sec_alias(
    client_with_runner,
    configurator_paths: dict[str, Path],
) -> None:
    """Spec §4.3 + popup-types both ship ``downbeat_sec``; honor it."""
    _seed_new_shape_forge(configurator_paths["processed_dir"], "shift2")
    client, _ = client_with_runner()
    r = client.post(
        "/forges/shift2/re-anchor",
        json={"downbeat_sec": 1.5, "source_bpm": 120.0},
    )
    assert r.status_code == 200


def test_re_anchor_422_on_missing_downbeat(
    client_with_runner,
    configurator_paths: dict[str, Path],
) -> None:
    _seed_new_shape_forge(configurator_paths["processed_dir"], "missing-db")
    client, _ = client_with_runner()
    r = client.post(
        "/forges/missing-db/re-anchor",
        json={"source_bpm": 120.0},
    )
    assert r.status_code == 422


def test_re_anchor_422_on_missing_source_bpm(
    client_with_runner,
    configurator_paths: dict[str, Path],
) -> None:
    _seed_new_shape_forge(configurator_paths["processed_dir"], "missing-bpm")
    client, _ = client_with_runner()
    r = client.post(
        "/forges/missing-bpm/re-anchor",
        json={"first_downbeat_seconds": 0.5},
    )
    assert r.status_code == 422


def test_re_anchor_returns_stderr_on_failure(
    client_with_runner,
    configurator_paths: dict[str, Path],
) -> None:
    _seed_new_shape_forge(configurator_paths["processed_dir"], "broken")
    client, _ = client_with_runner(returncode=1, stdout="", stderr="boom\n")
    r = client.post(
        "/forges/broken/re-anchor",
        json={"downbeat_sec": 0.5, "source_bpm": 120.0},
    )
    assert r.status_code == 200  # The endpoint reports failure in body.ok
    body = r.json()
    assert body["ok"] is False
    assert "boom" in body["stderr"]


def test_re_anchor_404_when_slug_unknown(
    client_with_runner,
) -> None:
    client, _ = client_with_runner()
    r = client.post(
        "/forges/no-forge/re-anchor",
        json={"downbeat_sec": 0.0, "source_bpm": 120.0},
    )
    assert r.status_code == 404


def test_re_anchor_malformed_body_returns_422(
    client_with_runner,
    configurator_paths: dict[str, Path],
) -> None:
    """Garbage payload fails Pydantic validation before reaching the handler."""
    _seed_new_shape_forge(configurator_paths["processed_dir"], "tightbody")
    client, _ = client_with_runner()
    r = client.post(
        "/forges/tightbody/re-anchor",
        json={"downbeat_sec": "not-a-number"},
    )
    assert r.status_code == 422


# ── POST /forges/{slug}/re-curate ───────────────────────────────────────────


def test_re_curate_invokes_cli_with_slug(
    client_with_runner,
    configurator_paths: dict[str, Path],
) -> None:
    _seed_new_shape_forge(configurator_paths["processed_dir"], "curateme")
    client, calls = client_with_runner(returncode=0, stdout="re-curate: wrote ...")
    r = client.post("/forges/curateme/re-curate", json={})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    cli_calls = [c for c in calls if "re-curate" in c["cmd"]]
    assert len(cli_calls) == 1
    assert cli_calls[0]["cmd"] == ["uv", "run", "stemforge", "re-curate", "curateme"]


def test_re_curate_404_when_slug_unknown(
    client_with_runner,
) -> None:
    client, _ = client_with_runner()
    r = client.post("/forges/no-such/re-curate", json={})
    assert r.status_code == 404


def test_re_curate_returns_failure_status_in_body(
    client_with_runner,
    configurator_paths: dict[str, Path],
) -> None:
    _seed_new_shape_forge(configurator_paths["processed_dir"], "willfail")
    client, _ = client_with_runner(returncode=2, stderr="curate exploded")
    r = client.post("/forges/willfail/re-curate", json={})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert "exploded" in body["stderr"]
