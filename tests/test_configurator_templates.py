"""Server tests for the Phase 3A templates surface.

Two endpoint families:

* ``GET  /templates`` — scans ``~/stemforge/templates/*.adg``.
* ``PATCH /curations/{name}/template`` (already tested in Phase 1B for the
  YAML write) — now validates template existence + fires a device
  notification. The Phase 1B contract tests still live in
  ``test_configurator_curation_crud.py``; the new behaviour gates here.

Every test pins its own ``tmp_path``-rooted curations + templates dirs so
the user's real ``~/stemforge`` is never touched.
"""

from __future__ import annotations

import shutil
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from stemforge.configurator.curation_io import (
    curation_path,
    read_curation,
    write_curation_atomic,
)
from stemforge.configurator.schemas import (
    Curation,
    Group,
    Pad,
    Target,
)
from stemforge.configurator.server import create_app
from stemforge.configurator.template_io import (
    TemplateIndexEntry,
    list_templates,
    resolve_template_path,
    template_exists,
)

FIXTURES_ROOT = Path(__file__).parent / "fixtures" / "templates"


# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def templates_dir(tmp_path: Path) -> Path:
    """Provision a tmp templates dir with two ``.adg`` sentinels + a sidecar."""
    out = tmp_path / "templates"
    out.mkdir()
    shutil.copy(FIXTURES_ROOT / "drum-rack-classic.adg", out)
    shutil.copy(FIXTURES_ROOT / "drum-rack-classic.description", out)
    shutil.copy(FIXTURES_ROOT / "vocal-bloom.adg", out)
    return out


@pytest.fixture
def configurator_dirs(tmp_path: Path, templates_dir: Path) -> dict[str, Path]:
    curations_dir = tmp_path / "curations"
    curations_dir.mkdir()
    state_path = tmp_path / ".stemforge_state.json"
    static_dir = tmp_path / "static"
    return {
        "curations_dir": curations_dir,
        "state_path": state_path,
        "static_dir": static_dir,
        "templates_dir": templates_dir,
    }


@pytest.fixture
def device_notifications() -> list[tuple[str, tuple[str, ...]]]:
    """Capture list for the device_notifier stub."""
    return []


@pytest.fixture
def client(
    configurator_dirs: dict[str, Path],
    device_notifications: list[tuple[str, tuple[str, ...]]],
) -> TestClient:
    def stub(route: str, *args: str) -> None:
        device_notifications.append((route, tuple(args)))

    app = create_app(
        static_dir=configurator_dirs["static_dir"],
        curations_dir=configurator_dirs["curations_dir"],
        state_path=configurator_dirs["state_path"],
        templates_dir=configurator_dirs["templates_dir"],
        device_notifier=stub,
    )
    return TestClient(app)


def _seed_curation(curations_dir: Path, name: str) -> Curation:
    """Drop a 4-group/12-pad Curation YAML on disk."""
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


# ── template_io unit tests ──────────────────────────────────────────────────


def test_list_templates_returns_both_alphabetical(templates_dir: Path) -> None:
    entries = list_templates(templates_dir)
    assert [e.name for e in entries] == ["drum-rack-classic", "vocal-bloom"]
    assert all(isinstance(e, TemplateIndexEntry) for e in entries)


def test_list_templates_reads_description_sidecar(templates_dir: Path) -> None:
    entries = list_templates(templates_dir)
    drk = next(e for e in entries if e.name == "drum-rack-classic")
    assert drk.description is not None
    assert "drum rack" in drk.description.lower()
    # Templates without a sidecar surface description=None (dict-dropped).
    vb = next(e for e in entries if e.name == "vocal-bloom")
    assert vb.description is None
    assert "description" not in vb.to_dict()


def test_list_templates_empty_dir_returns_empty(tmp_path: Path) -> None:
    out = tmp_path / "empty_templates"
    out.mkdir()
    assert list_templates(out) == []


def test_list_templates_missing_dir_returns_empty(tmp_path: Path) -> None:
    # First-run-before-user-created-dir case.
    assert list_templates(tmp_path / "does-not-exist") == []


def test_template_exists_rejects_path_traversal(templates_dir: Path) -> None:
    assert template_exists(templates_dir, "drum-rack-classic") is True
    assert template_exists(templates_dir, "../etc/passwd") is False
    assert template_exists(templates_dir, "no-such-template") is False


def test_resolve_template_path_404_on_unknown(templates_dir: Path) -> None:
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        resolve_template_path(templates_dir, "unknown")
    assert exc.value.status_code == 404


# ── GET /templates endpoint tests ───────────────────────────────────────────


def test_get_templates_lists_both_fixtures(client: TestClient) -> None:
    r = client.get("/templates")
    assert r.status_code == 200
    body = r.json()
    assert "templates" in body
    names = [t["name"] for t in body["templates"]]
    assert names == ["drum-rack-classic", "vocal-bloom"]
    # Shape contract: each row has name/path/modified_at/size_bytes.
    for row in body["templates"]:
        assert set(row.keys()) >= {"name", "path", "modified_at", "size_bytes"}
        assert row["path"].endswith(".adg")


def test_get_templates_description_appears_when_sidecar_present(
    client: TestClient,
) -> None:
    body = client.get("/templates").json()
    drk = next(t for t in body["templates"] if t["name"] == "drum-rack-classic")
    assert "description" in drk
    vb = next(t for t in body["templates"] if t["name"] == "vocal-bloom")
    assert "description" not in vb  # absent, not null


def test_get_templates_empty_dir_returns_empty_list(
    tmp_path: Path, configurator_dirs: dict[str, Path]
) -> None:
    # Build a fresh app with an empty templates dir (overriding the fixture
    # which seeds two .adg files).
    empty = tmp_path / "empty_templates"
    empty.mkdir()
    app = create_app(
        static_dir=configurator_dirs["static_dir"],
        curations_dir=configurator_dirs["curations_dir"],
        state_path=configurator_dirs["state_path"],
        templates_dir=empty,
        device_notifier=lambda *args: None,
    )
    r = TestClient(app).get("/templates")
    assert r.status_code == 200
    assert r.json() == {"templates": []}


# ── PATCH /template + device-notify behaviour ───────────────────────────────


def test_patch_template_with_valid_args_writes_yaml_and_notifies_device(
    client: TestClient,
    configurator_dirs: dict[str, Path],
    device_notifications: list[tuple[str, tuple[str, ...]]],
) -> None:
    _seed_curation(configurator_dirs["curations_dir"], "verse_swap_v1")
    r = client.patch(
        "/curations/verse_swap_v1/template",
        json={"group_letter": "B", "template_name": "drum-rack-classic"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["groups"]["B"]["template"] == "drum-rack-classic"
    # YAML mutation landed.
    on_disk = read_curation(
        curation_path(configurator_dirs["curations_dir"], "verse_swap_v1"),
    )
    assert on_disk.groups["B"].template == "drum-rack-classic"
    # Device notification fired with exactly the canonical args.
    assert ("template-changed", ("B", "drum-rack-classic")) in device_notifications


def test_patch_template_with_unknown_template_returns_404(
    client: TestClient, configurator_dirs: dict[str, Path]
) -> None:
    _seed_curation(configurator_dirs["curations_dir"], "c")
    r = client.patch(
        "/curations/c/template",
        json={"group_letter": "A", "template_name": "no-such-rack"},
    )
    assert r.status_code == 404
    detail = r.json()["detail"]
    assert "no-such-rack" in detail


def test_patch_template_clear_uses_dash_sentinel_in_device_notify(
    client: TestClient,
    configurator_dirs: dict[str, Path],
    device_notifications: list[tuple[str, tuple[str, ...]]],
) -> None:
    _seed_curation(configurator_dirs["curations_dir"], "c")
    # First assign so we have something to clear.
    client.patch(
        "/curations/c/template",
        json={"group_letter": "A", "template_name": "drum-rack-classic"},
    )
    device_notifications.clear()
    r = client.patch(
        "/curations/c/template",
        json={"group_letter": "A", "template_name": None},
    )
    assert r.status_code == 200
    assert r.json()["groups"]["A"]["template"] is None
    # Clear surfaces as ``"-"`` sentinel so Max's UDP route can dispatch
    # without a None ↔ empty-string ambiguity.
    assert ("template-changed", ("A", "-")) in device_notifications


def test_patch_template_unknown_group_letter_no_device_notify(
    client: TestClient,
    configurator_dirs: dict[str, Path],
    device_notifications: list[tuple[str, tuple[str, ...]]],
) -> None:
    """Group-letter check fires before notify, so no message leaks out."""
    _seed_curation(configurator_dirs["curations_dir"], "c")
    r = client.patch(
        "/curations/c/template",
        json={"group_letter": "Z", "template_name": "drum-rack-classic"},
    )
    assert r.status_code == 404
    assert device_notifications == []


def test_patch_template_unknown_curation_returns_404(
    client: TestClient,
    device_notifications: list[tuple[str, tuple[str, ...]]],
) -> None:
    r = client.patch(
        "/curations/does-not-exist/template",
        json={"group_letter": "A", "template_name": "drum-rack-classic"},
    )
    assert r.status_code == 404
    assert device_notifications == []


def test_patch_template_device_notifier_failure_does_not_block_write(
    configurator_dirs: dict[str, Path],
) -> None:
    """Notifier exception is swallowed; curation write must still happen."""
    _seed_curation(configurator_dirs["curations_dir"], "c")

    def boom(_route: str, *_args: str) -> None:
        raise OSError("simulated UDP send failure")

    app = create_app(
        static_dir=configurator_dirs["static_dir"],
        curations_dir=configurator_dirs["curations_dir"],
        state_path=configurator_dirs["state_path"],
        templates_dir=configurator_dirs["templates_dir"],
        device_notifier=boom,
    )
    r = TestClient(app).patch(
        "/curations/c/template",
        json={"group_letter": "A", "template_name": "drum-rack-classic"},
    )
    assert r.status_code == 200
    on_disk = read_curation(curation_path(configurator_dirs["curations_dir"], "c"))
    assert on_disk.groups["A"].template == "drum-rack-classic"


# ── POST /open + device-notify behaviour ────────────────────────────────────


def test_open_curation_notifies_device(
    client: TestClient,
    configurator_dirs: dict[str, Path],
    device_notifications: list[tuple[str, tuple[str, ...]]],
) -> None:
    """Opening a curation in the popup tells the device to load it."""
    _seed_curation(configurator_dirs["curations_dir"], "verse_swap_v1")
    r = client.post("/curations/verse_swap_v1/open", json={"als_path": "__popup__"})
    assert r.status_code == 200
    # Wire shape: ``curation-opened <name>`` — the device routes this into
    # curationOpened(name) and loads the YAML so COMMIT can run.
    assert ("curation-opened", ("verse_swap_v1",)) in device_notifications


def test_open_unknown_curation_no_device_notify(
    client: TestClient,
    device_notifications: list[tuple[str, tuple[str, ...]]],
) -> None:
    """404 fires before notify — no message leaks for a missing curation."""
    r = client.post("/curations/does-not-exist/open", json={"als_path": "__popup__"})
    assert r.status_code == 404
    assert device_notifications == []


def test_open_curation_device_notifier_failure_does_not_block(
    configurator_dirs: dict[str, Path],
) -> None:
    """Notifier exception is swallowed; the open must still succeed."""
    _seed_curation(configurator_dirs["curations_dir"], "c")

    def boom(_route: str, *_args: str) -> None:
        raise OSError("simulated UDP send failure")

    app = create_app(
        static_dir=configurator_dirs["static_dir"],
        curations_dir=configurator_dirs["curations_dir"],
        state_path=configurator_dirs["state_path"],
        templates_dir=configurator_dirs["templates_dir"],
        device_notifier=boom,
    )
    r = TestClient(app).post("/curations/c/open", json={"als_path": "__popup__"})
    assert r.status_code == 200
