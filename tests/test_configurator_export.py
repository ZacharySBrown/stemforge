"""EXPORT endpoint tests (Phase 3C, spec §3.3 / §4.3 / §6.7).

Covers ``POST /curations/{name}/export`` + the ``perform_export``
unit-testable handler. ``subprocess_runner`` is stubbed end-to-end so
the real ``stemforge export`` CLI is never spawned; the focus here is
the control-plane wiring (validation, state mutation, SSE broadcast).

Includes coverage for the ``POST /intent/pick-save-path`` osascript
helper, which lives next to EXPORT on the route surface.
"""

from __future__ import annotations

import asyncio
import subprocess
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import yaml
from fastapi.testclient import TestClient

from stemforge.configurator.curation_io import (
    curation_path,
    read_curation,
    write_curation_atomic,
)
from stemforge.configurator.export_handler import (
    ExportValidationError,
    build_export_command,
    curation_to_deck_plan,
    perform_export,
    update_last_export,
    validate_curation_name,
    validate_out_path,
    validate_target_format,
)
from stemforge.configurator.schemas import Curation, Group, Pad, Target
from stemforge.configurator.schemas.curation import ClipSettings, PadSource
from stemforge.configurator.server import create_app


# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def configurator_paths(tmp_path: Path) -> dict[str, Path]:
    """Isolated ``~/stemforge/`` layout under ``tmp_path``."""
    curations_dir = tmp_path / "curations"
    curations_dir.mkdir()
    processed_dir = tmp_path / "processed"
    processed_dir.mkdir()
    state_path = tmp_path / ".stemforge_state.json"
    static_dir = tmp_path / "static"
    desktop = tmp_path / "Desktop"
    desktop.mkdir()
    return {
        "curations_dir": curations_dir,
        "processed_dir": processed_dir,
        "state_path": state_path,
        "static_dir": static_dir,
        "desktop": desktop,
    }


def _seed_curation(curations_dir: Path, name: str) -> Curation:
    """Drop a minimal Curation YAML on disk via the same atomic writer."""
    now = datetime.now(UTC)
    target = Target()
    groups: dict[str, Group] = {}
    for letter in ("A", "B", "C", "D"):
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


def _make_runner_stub(
    *,
    returncode: int = 0,
    stdout: str = "",
    stderr: str = "",
    timeout: bool = False,
    artifact_bytes: bytes | None = None,
) -> tuple[Callable, list[dict]]:
    """Build a fake ``subprocess.run`` recording each invocation.

    When ``artifact_bytes`` is supplied and the command looks like
    ``stemforge export ... --out <path>``, the stub writes those bytes
    to ``<path>`` so the post-export hashing branch can exercise.
    """
    calls: list[dict] = []

    def runner(cmd, **kwargs):
        calls.append({"cmd": list(cmd), "kwargs": dict(kwargs)})
        if timeout:
            raise subprocess.TimeoutExpired(
                cmd=cmd,
                timeout=kwargs.get("timeout", 0),
                output=stdout,
                stderr=stderr,
            )
        # Emulate the CLI writing its artifact when asked.
        if artifact_bytes is not None and "--out" in cmd:
            out_idx = cmd.index("--out") + 1
            if out_idx < len(cmd):
                Path(cmd[out_idx]).write_bytes(artifact_bytes)
        return SimpleNamespace(
            returncode=returncode,
            stdout=stdout,
            stderr=stderr,
        )

    return runner, calls


@pytest.fixture
def client_with_runner(configurator_paths: dict[str, Path]) -> Callable:
    """Factory: build a TestClient with a stub subprocess runner injected."""

    def _build(
        *,
        returncode: int = 0,
        stdout: str = "",
        stderr: str = "",
        timeout: bool = False,
        artifact_bytes: bytes | None = None,
    ) -> tuple[TestClient, list[dict]]:
        runner, calls = _make_runner_stub(
            returncode=returncode,
            stdout=stdout,
            stderr=stderr,
            timeout=timeout,
            artifact_bytes=artifact_bytes,
        )
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
    c, _ = client_with_runner()
    return c


# ── Unit: validators ────────────────────────────────────────────────────────


def test_validate_target_format_accepts_ppak() -> None:
    assert validate_target_format("ppak") == "ppak"
    assert validate_target_format("PPAK") == "ppak"


def test_validate_target_format_rejects_unknown() -> None:
    with pytest.raises(ExportValidationError):
        validate_target_format("ableton")
    with pytest.raises(ExportValidationError):
        validate_target_format("")


def test_validate_out_path_rejects_traversal(tmp_path: Path) -> None:
    with pytest.raises(ExportValidationError, match="traversal"):
        validate_out_path(str(tmp_path / "sub" / ".." / "etc.ppak"))
    with pytest.raises(ExportValidationError, match="traversal"):
        validate_out_path("../etc/secrets.ppak")


def test_validate_out_path_rejects_missing_parent(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist" / "kit.ppak"
    with pytest.raises(ExportValidationError, match="parent"):
        validate_out_path(str(missing))


def test_validate_out_path_accepts_existing_dir(tmp_path: Path) -> None:
    target = tmp_path / "kit.ppak"
    out = validate_out_path(str(target))
    assert out == target.resolve()


def test_validate_curation_name_rejects_bad_names() -> None:
    with pytest.raises(ExportValidationError):
        validate_curation_name("../escape")
    with pytest.raises(ExportValidationError):
        validate_curation_name("")


def test_build_export_command_shape(tmp_path: Path) -> None:
    deck_plan = tmp_path / "deck-plan.json"
    deck_plan.write_text("{}")
    cmd = build_export_command(
        deck_plan_path=deck_plan,
        out_path=tmp_path / "out.ppak",
    )
    # New shape: stemforge build-deck DECK_PLAN --out FILE.ppak
    # The legacy `stemforge export ... --target ppak --out ...` invocation
    # was wrong on three axes (subcommand, --target enum, --out vs --output)
    # and never produced a .ppak. See 2026-05-15 commit for the rewrite.
    assert cmd[:4] == ["uv", "run", "stemforge", "build-deck"]
    assert str(deck_plan) in cmd
    assert "--out" in cmd and cmd[cmd.index("--out") + 1] == str(tmp_path / "out.ppak")


def test_build_export_command_attaches_reference_template_if_present(
    tmp_path: Path,
) -> None:
    deck_plan = tmp_path / "deck-plan.json"
    deck_plan.write_text("{}")
    ref = tmp_path / "reference.ppak"
    ref.write_bytes(b"fake ppak template")
    cmd = build_export_command(
        deck_plan_path=deck_plan,
        out_path=tmp_path / "out.ppak",
        reference_template=ref,
    )
    assert "--reference-template" in cmd
    assert cmd[cmd.index("--reference-template") + 1] == str(ref)


def test_build_export_command_skips_missing_reference_template(
    tmp_path: Path,
) -> None:
    deck_plan = tmp_path / "deck-plan.json"
    deck_plan.write_text("{}")
    cmd = build_export_command(
        deck_plan_path=deck_plan,
        out_path=tmp_path / "out.ppak",
        reference_template=tmp_path / "does-not-exist.ppak",
    )
    # Missing template falls through to the CLI's "synthesise minimal" path
    # rather than failing the call. Asserts the flag is absent.
    assert "--reference-template" not in cmd


# ── Unit: curation_to_deck_plan adapter ─────────────────────────────────────


def _make_curation_with_pads(forges_dir_label: str = "sample-forge") -> Curation:
    """Build a curation with 2 populated + 1 empty pad across two groups."""
    now = datetime.now(UTC)
    groups: dict[str, Group] = {}
    # Group A: Vocals, A01 populated, A02 empty.
    groups["A"] = Group(
        label="Vocals",
        template="vocal-bloom",
        pads=[
            Pad(
                pad_id="A01",
                source=PadSource.for_forge(
                    forge=forges_dir_label,
                    clip_id="vocal-bar0-4",
                    audio_path="curated_audio/vocal-bar0-4.wav",
                ),
                clip_settings=ClipSettings(
                    warp_bpm=120.0,
                    loop_start_bar=0.0,
                    loop_end_bar=4.0,
                    looping=True,
                ),
            ),
            Pad(pad_id="A02"),
        ],
    )
    # Group B: Drums, B01 populated (external path).
    groups["B"] = Group(
        label="Drums",
        template=None,
        pads=[
            Pad(
                pad_id="B01",
                source=PadSource.for_external(
                    external_path="/tmp/external/kick.wav",
                ),
                clip_settings=ClipSettings(
                    warp_bpm=92.0,
                    loop_start_bar=0.0,
                    loop_end_bar=1.0,
                    looping=False,
                ),
            ),
        ],
    )
    return Curation(
        name="adapter_test",
        type="deck",
        created_at=now,
        modified_at=now,
        target=Target(),
        referenced_forges=[],
        groups=groups,
    )


def test_curation_to_deck_plan_resolves_forge_paths(tmp_path: Path) -> None:
    curation = _make_curation_with_pads()
    forges_dir = tmp_path / "processed"
    plan = curation_to_deck_plan(curation, forges_dir=forges_dir)
    assert plan["project"] == "adapter_test"
    assert plan["project_bpm"] == 120.0  # first populated pad's warp_bpm
    # Group A: vocal profile, forge-resolved path.
    grpA = plan["groups"]["A"]
    assert grpA["format_profile"] == "vocal"
    assert len(grpA["pads"]) == 1  # empty A02 dropped
    assert grpA["pads"][0]["pad"] == 1
    assert grpA["pads"][0]["path"] == str(
        forges_dir / "sample-forge" / "curated_audio" / "vocal-bar0-4.wav"
    )
    assert grpA["pads"][0]["source_bpm"] == 120.0


def test_curation_to_deck_plan_passes_external_paths_through(tmp_path: Path) -> None:
    curation = _make_curation_with_pads()
    plan = curation_to_deck_plan(curation, forges_dir=tmp_path / "processed")
    grpB = plan["groups"]["B"]
    assert grpB["format_profile"] == "drum"
    # External path is preserved verbatim (no forge prefix).
    assert grpB["pads"][0]["path"] == "/tmp/external/kick.wav"
    assert grpB["pads"][0]["source_bpm"] == 92.0


def test_curation_to_deck_plan_omits_groups_with_no_populated_pads(
    tmp_path: Path,
) -> None:
    now = datetime.now(UTC)
    groups: dict[str, Group] = {
        # All-empty group.
        "C": Group(
            label="FX",
            template=None,
            pads=[Pad(pad_id=f"C{i + 1:02d}") for i in range(12)],
        ),
    }
    curation = Curation(
        name="all_empty",
        type="deck",
        created_at=now,
        modified_at=now,
        target=Target(),
        referenced_forges=[],
        groups=groups,
    )
    plan = curation_to_deck_plan(curation, forges_dir=tmp_path)
    # Empty group dropped — CLI gets only populated groups.
    assert "C" not in plan["groups"]
    assert plan["project_bpm"] == 120.0  # default fallback


def test_curation_to_deck_plan_parses_pad_number_from_pad_id(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    groups: dict[str, Group] = {
        "A": Group(
            label="",
            template=None,
            pads=[
                Pad(
                    pad_id="A07",  # zero-padded
                    source=PadSource.for_external(external_path="/a.wav"),
                    clip_settings=ClipSettings(
                        warp_bpm=100.0, loop_end_bar=4.0
                    ),
                ),
                Pad(
                    pad_id="A·12",  # interpunct form
                    source=PadSource.for_external(external_path="/b.wav"),
                    clip_settings=ClipSettings(
                        warp_bpm=100.0, loop_end_bar=4.0
                    ),
                ),
            ],
        ),
    }
    curation = Curation(
        name="padform",
        type="deck",
        created_at=now,
        modified_at=now,
        target=Target(),
        referenced_forges=[],
        groups=groups,
    )
    plan = curation_to_deck_plan(curation, forges_dir=tmp_path)
    pad_numbers = sorted(p["pad"] for p in plan["groups"]["A"]["pads"])
    assert pad_numbers == [7, 12]


# ── Unit: perform_export orchestration ──────────────────────────────────────


def test_perform_export_success_writes_last_export(
    configurator_paths: dict[str, Path],
) -> None:
    _seed_curation(configurator_paths["curations_dir"], "alpha")
    runner, calls = _make_runner_stub(
        returncode=0,
        stdout="wrote 12345 bytes",
        artifact_bytes=b"PPAK_PAYLOAD_BYTES",
    )
    out_path = configurator_paths["desktop"] / "alpha.ppak"
    result = perform_export(
        curations_dir=configurator_paths["curations_dir"],
        name="alpha",
        out_path_raw=str(out_path),
        target_format_raw="ppak",
        subprocess_runner=runner,
    )
    assert result.ok is True
    assert "12345" in result.stdout
    # Subprocess was invoked with the canonical argv shape.
    assert calls and calls[0]["cmd"][:4] == ["uv", "run", "stemforge", "build-deck"]
    # last_export was persisted with timestamp + path + hash.
    persisted = read_curation(curation_path(configurator_paths["curations_dir"], "alpha"))
    assert persisted.last_export is not None
    assert persisted.last_export.output_path.endswith("alpha.ppak")
    assert persisted.last_export.target_format == "ppak"
    assert persisted.last_export.manifest_hash is not None
    assert persisted.last_export.manifest_hash.startswith("sha256:")


def test_perform_export_subprocess_failure_returns_envelope(
    configurator_paths: dict[str, Path],
) -> None:
    _seed_curation(configurator_paths["curations_dir"], "boomed")
    runner, _ = _make_runner_stub(returncode=2, stderr="exporter crashed")
    out_path = configurator_paths["desktop"] / "boomed.ppak"
    result = perform_export(
        curations_dir=configurator_paths["curations_dir"],
        name="boomed",
        out_path_raw=str(out_path),
        subprocess_runner=runner,
    )
    assert result.ok is False
    assert "crashed" in result.stderr
    # last_export is NOT persisted on failure.
    persisted = read_curation(curation_path(configurator_paths["curations_dir"], "boomed"))
    assert persisted.last_export is None


def test_perform_export_timeout_returns_timeout_tag(
    configurator_paths: dict[str, Path],
) -> None:
    _seed_curation(configurator_paths["curations_dir"], "slow")
    runner, _ = _make_runner_stub(timeout=True)
    out_path = configurator_paths["desktop"] / "slow.ppak"
    result = perform_export(
        curations_dir=configurator_paths["curations_dir"],
        name="slow",
        out_path_raw=str(out_path),
        subprocess_runner=runner,
    )
    assert result.ok is False
    assert result.error == "timeout"


def test_perform_export_missing_curation_raises_filenotfound(
    configurator_paths: dict[str, Path],
) -> None:
    # No curation seeded → FileNotFoundError (route maps to 404).
    runner, _ = _make_runner_stub()
    out_path = configurator_paths["desktop"] / "ghost.ppak"
    with pytest.raises(FileNotFoundError):
        perform_export(
            curations_dir=configurator_paths["curations_dir"],
            name="ghost",
            out_path_raw=str(out_path),
            subprocess_runner=runner,
        )


# ── Route: success path ─────────────────────────────────────────────────────


def test_export_route_success_updates_last_export_and_broadcasts_sse(
    configurator_paths: dict[str, Path],
) -> None:
    """End-to-end: route writes last_export AND broadcasts a state SSE event."""
    _seed_curation(configurator_paths["curations_dir"], "verse_swap_v1")
    out_path = configurator_paths["desktop"] / "verse_swap_v1.ppak"
    runner, calls = _make_runner_stub(
        returncode=0,
        stdout="ok",
        artifact_bytes=b"BYTES",
    )

    app = create_app(
        static_dir=configurator_paths["static_dir"],
        curations_dir=configurator_paths["curations_dir"],
        state_path=configurator_paths["state_path"],
        processed_dir=configurator_paths["processed_dir"],
        subprocess_runner=runner,
    )
    state = app.state.configurator

    async def _drive() -> list:
        queue = state.subscribe()
        try:
            with TestClient(app) as c:
                resp = c.post(
                    "/curations/verse_swap_v1/export",
                    json={"out_path": str(out_path), "target_format": "ppak"},
                )
                assert resp.status_code == 200, resp.text
                body = resp.json()
                assert body["ok"] is True
                assert body["name"] == "verse_swap_v1"
                assert body["last_export"]["target_format"] == "ppak"
                assert body["last_export"]["output_path"].endswith("verse_swap_v1.ppak")
            collected: list = []
            while not queue.empty():
                collected.append(queue.get_nowait())
            return collected
        finally:
            state.unsubscribe(queue)

    events = asyncio.run(_drive())
    # At least one curation-kind state event should have been broadcast.
    curation_events = [
        e for e in events if e.event == "state" and e.data.get("kind") == "curations"
    ]
    assert curation_events, f"no curation state events; got {[e.event for e in events]}"
    # Subprocess was invoked with the build-deck argv.
    assert any("build-deck" in c["cmd"] for c in calls)


# ── Route: failure paths ────────────────────────────────────────────────────


def test_export_route_subprocess_failure_returns_200_with_stderr(
    client_with_runner,
    configurator_paths: dict[str, Path],
) -> None:
    """Match re-anchor pattern: shell failure ⇒ 200 with diagnostics in body."""
    _seed_curation(configurator_paths["curations_dir"], "broken")
    client, _ = client_with_runner(returncode=1, stderr="boom\n")
    out_path = configurator_paths["desktop"] / "broken.ppak"
    r = client.post(
        "/curations/broken/export",
        json={"out_path": str(out_path), "target_format": "ppak"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert "boom" in body["stderr"]
    # last_export is NOT persisted on failure.
    persisted = read_curation(curation_path(configurator_paths["curations_dir"], "broken"))
    assert persisted.last_export is None


def test_export_route_timeout_returns_200_with_error_tag(
    client_with_runner,
    configurator_paths: dict[str, Path],
) -> None:
    _seed_curation(configurator_paths["curations_dir"], "slowboat")
    client, _ = client_with_runner(timeout=True)
    out_path = configurator_paths["desktop"] / "slowboat.ppak"
    r = client.post(
        "/curations/slowboat/export",
        json={"out_path": str(out_path), "target_format": "ppak"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert body["error"] == "timeout"


def test_export_route_400_on_path_traversal(
    client_with_runner,
    configurator_paths: dict[str, Path],
) -> None:
    _seed_curation(configurator_paths["curations_dir"], "alpha")
    client, _ = client_with_runner()
    r = client.post(
        "/curations/alpha/export",
        json={"out_path": "../../../etc/passwd", "target_format": "ppak"},
    )
    assert r.status_code == 400
    assert "traversal" in r.json()["detail"].lower()


def test_export_route_400_on_missing_parent(
    client_with_runner,
    configurator_paths: dict[str, Path],
    tmp_path: Path,
) -> None:
    _seed_curation(configurator_paths["curations_dir"], "alpha")
    client, _ = client_with_runner()
    bad_path = tmp_path / "does-not-exist" / "alpha.ppak"
    r = client.post(
        "/curations/alpha/export",
        json={"out_path": str(bad_path), "target_format": "ppak"},
    )
    assert r.status_code == 400
    assert "parent" in r.json()["detail"].lower()


def test_export_route_400_on_unknown_target_format(
    client_with_runner,
    configurator_paths: dict[str, Path],
) -> None:
    _seed_curation(configurator_paths["curations_dir"], "alpha")
    client, _ = client_with_runner()
    out_path = configurator_paths["desktop"] / "alpha.ableton"
    r = client.post(
        "/curations/alpha/export",
        json={"out_path": str(out_path), "target_format": "ableton"},
    )
    assert r.status_code == 400
    assert "target_format" in r.json()["detail"].lower()


def test_export_route_404_on_unknown_curation(
    client_with_runner,
    configurator_paths: dict[str, Path],
) -> None:
    client, _ = client_with_runner()
    out_path = configurator_paths["desktop"] / "ghost.ppak"
    r = client.post(
        "/curations/ghost/export",
        json={"out_path": str(out_path), "target_format": "ppak"},
    )
    assert r.status_code == 404


def test_export_route_400_on_invalid_curation_name(
    client_with_runner,
    configurator_paths: dict[str, Path],
) -> None:
    """Reserved curation names (e.g. ``.``) are rejected before disk lookup."""
    client, _ = client_with_runner()
    out_path = configurator_paths["desktop"] / "x.ppak"
    # ``.`` is in the reserved-names set per ``is_valid_curation_name``.
    r = client.post(
        "/curations/./export",
        json={"out_path": str(out_path), "target_format": "ppak"},
    )
    # Either Starlette's 405 path collision OR our 400 validation is fine;
    # the load-bearing invariant is "no 5xx, no disk read attempted".
    assert r.status_code in (400, 404, 405)


def test_export_route_idempotent_reexport_updates_last_export(
    client_with_runner,
    configurator_paths: dict[str, Path],
) -> None:
    """Two successful exports in a row: second one's timestamp/path overwrites the first."""
    _seed_curation(configurator_paths["curations_dir"], "iter")
    out1 = configurator_paths["desktop"] / "iter_v1.ppak"
    out2 = configurator_paths["desktop"] / "iter_v2.ppak"

    client_v1, _ = client_with_runner(returncode=0, artifact_bytes=b"V1")
    r1 = client_v1.post(
        "/curations/iter/export",
        json={"out_path": str(out1), "target_format": "ppak"},
    )
    assert r1.status_code == 200 and r1.json()["ok"] is True

    persisted_after_first = read_curation(
        curation_path(configurator_paths["curations_dir"], "iter")
    )
    first_ts = persisted_after_first.last_export.exported_at
    first_path = persisted_after_first.last_export.output_path
    first_hash = persisted_after_first.last_export.manifest_hash
    assert first_path.endswith("iter_v1.ppak")

    # Second export with different bytes → new path + new hash.
    client_v2, _ = client_with_runner(returncode=0, artifact_bytes=b"V2_DIFFERENT")
    r2 = client_v2.post(
        "/curations/iter/export",
        json={"out_path": str(out2), "target_format": "ppak"},
    )
    assert r2.status_code == 200 and r2.json()["ok"] is True

    persisted_after_second = read_curation(
        curation_path(configurator_paths["curations_dir"], "iter")
    )
    assert persisted_after_second.last_export.output_path.endswith("iter_v2.ppak")
    assert persisted_after_second.last_export.exported_at >= first_ts
    assert persisted_after_second.last_export.manifest_hash != first_hash


def test_export_route_defaults_target_format_to_ppak(
    client_with_runner,
    configurator_paths: dict[str, Path],
) -> None:
    """``target_format`` is optional on the wire — defaults to ``ppak``."""
    _seed_curation(configurator_paths["curations_dir"], "defaults")
    client, calls = client_with_runner(returncode=0, artifact_bytes=b"X")
    out_path = configurator_paths["desktop"] / "defaults.ppak"
    r = client.post(
        "/curations/defaults/export",
        json={"out_path": str(out_path)},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    # Persisted ``target_format`` reflects the default.
    assert body["last_export"]["target_format"] == "ppak"
    # The build-deck CLI doesn't take --target (it's ppak-only by design),
    # so we just verify the build-deck subcommand was invoked.
    build_deck_call = next(
        (c for c in calls if "build-deck" in c["cmd"]), None
    )
    assert build_deck_call is not None


def test_export_route_invokes_build_deck_with_temp_plan_and_out_path(
    client_with_runner,
    configurator_paths: dict[str, Path],
) -> None:
    """Verify the CLI argv shape: ``stemforge build-deck <plan> --out <ppak>``."""
    _seed_curation(configurator_paths["curations_dir"], "argv_check")
    client, calls = client_with_runner(returncode=0, artifact_bytes=b"X")
    out_path = configurator_paths["desktop"] / "argv_check.ppak"
    r = client.post(
        "/curations/argv_check/export",
        json={"out_path": str(out_path), "target_format": "ppak"},
    )
    assert r.status_code == 200
    build_deck_call = next(c for c in calls if "build-deck" in c["cmd"])
    cmd = build_deck_call["cmd"]
    # Shape: stemforge build-deck DECK_PLAN --out FILE.ppak
    assert cmd[0:4] == ["uv", "run", "stemforge", "build-deck"]
    # Positional after build-deck is the deck-plan JSON (a tempfile path).
    assert cmd[4].endswith(".json")
    assert "argv_check" in cmd[4]  # tempfile carries the curation name
    assert "--out" in cmd
    assert cmd[cmd.index("--out") + 1] == str(out_path.resolve())


# ── Route: pick-save-path osascript helper ──────────────────────────────────


def test_pick_save_path_returns_chosen_path(
    configurator_paths: dict[str, Path],
) -> None:
    """Stubbed osascript runner returns a path on stdout; endpoint surfaces it."""
    chosen = str(configurator_paths["desktop"] / "user_pick.ppak")

    def runner(cmd: list[str], **kwargs: Any) -> Any:
        assert cmd[0] == "osascript"
        return SimpleNamespace(returncode=0, stdout=chosen + "\n", stderr="")

    app = create_app(
        static_dir=configurator_paths["static_dir"],
        curations_dir=configurator_paths["curations_dir"],
        state_path=configurator_paths["state_path"],
        processed_dir=configurator_paths["processed_dir"],
        subprocess_runner=runner,
    )
    client = TestClient(app)
    r = client.post(
        "/intent/pick-save-path",
        json={"default_name": "kit.ppak"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["path"] == chosen


def test_pick_save_path_returns_null_on_cancel(
    configurator_paths: dict[str, Path],
) -> None:
    """User-cancel surfaces as non-zero exit; we return path=None."""

    def runner(cmd: list[str], **kwargs: Any) -> Any:
        # AppleScript's user-cancel is exit-code 1 (or error -128).
        return SimpleNamespace(returncode=1, stdout="", stderr="User canceled.")

    app = create_app(
        static_dir=configurator_paths["static_dir"],
        curations_dir=configurator_paths["curations_dir"],
        state_path=configurator_paths["state_path"],
        processed_dir=configurator_paths["processed_dir"],
        subprocess_runner=runner,
    )
    client = TestClient(app)
    r = client.post("/intent/pick-save-path", json={})
    assert r.status_code == 200
    assert r.json()["path"] is None


def test_pick_save_path_handles_missing_osascript(
    configurator_paths: dict[str, Path],
) -> None:
    """Non-mac runner without ``osascript`` shouldn't 500."""

    def runner(cmd: list[str], **kwargs: Any) -> Any:
        raise FileNotFoundError("osascript not found")

    app = create_app(
        static_dir=configurator_paths["static_dir"],
        curations_dir=configurator_paths["curations_dir"],
        state_path=configurator_paths["state_path"],
        processed_dir=configurator_paths["processed_dir"],
        subprocess_runner=runner,
    )
    client = TestClient(app)
    r = client.post("/intent/pick-save-path", json={})
    assert r.status_code == 200
    assert r.json()["path"] is None


# ── Direct unit test: update_last_export ────────────────────────────────────


def test_update_last_export_persists_record(
    configurator_paths: dict[str, Path],
) -> None:
    _seed_curation(configurator_paths["curations_dir"], "direct")
    out_path = configurator_paths["desktop"] / "direct.ppak"
    out_path.write_bytes(b"hello")
    now = datetime.now(UTC)
    curation, record = update_last_export(
        curations_dir=configurator_paths["curations_dir"],
        name="direct",
        out_path=out_path,
        target_format="ppak",
        now=now,
    )
    assert record.target_format == "ppak"
    assert record.output_path == str(out_path)
    assert record.manifest_hash is not None
    # Re-read the file to confirm on-disk shape.
    raw = (configurator_paths["curations_dir"] / "direct.yaml").read_text()
    payload = yaml.safe_load(raw)
    assert payload["last_export"]["target_format"] == "ppak"
    assert payload["last_export"]["output_path"].endswith("direct.ppak")
