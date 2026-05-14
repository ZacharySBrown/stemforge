"""Fixture ``.als`` discovery + status reporting.

Live Sets (``.als``) are gzip-compressed XML. A ``PRESENT`` fixture
gunzips cleanly and starts with ``<?xml``. A ``CORRUPT`` fixture
exists but fails one of those checks (someone committed a raw binary
that isn't gzip, or the XML header is missing). A ``MISSING`` fixture
has no file at all — the smoke runner skips tests that require it.

The fixture inventory below MUST match the smoke-test table in
``live_runner.py`` and the README in ``tests/fixtures/als/``. The
drift test in ``tests/test_live_runner.py`` enforces the link.
"""

from __future__ import annotations

import gzip
import io
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class FixtureStatus(str, Enum):
    MISSING = "missing"
    PRESENT = "present"
    CORRUPT = "corrupt"


@dataclass(frozen=True)
class FixtureSpec:
    """One ``.als`` fixture the smoke suite references."""

    filename: str
    description: str
    # Optional: smoke tests that consume this fixture. Drift test asserts
    # every smoke uses a known fixture.
    used_by: tuple[str, ...] = ()


# Inventory — single source of truth for fixtures.
# Keep in sync with tests/fixtures/als/README.md and the smoke-test table.
FIXTURE_INVENTORY: tuple[FixtureSpec, ...] = (
    FixtureSpec(
        filename="empty-staging.als",
        description="Empty Live set with just StemForge.amxd loaded. No tracks beyond defaults.",
        used_by=("smoke_1_empty_boot",),
    ),
    FixtureSpec(
        filename="loaded-forge-stg-empty.als",
        description=(
            "Live set with one FORGE/* track group already loaded "
            "(breaks-n-beats-1 fixture forge), no staging populated."
        ),
        used_by=(
            "smoke_2_load_forge",
            "smoke_3_create_curation",
            "smoke_4_commit",
        ),
    ),
    FixtureSpec(
        filename="curation-active-stg-populated.als",
        description=(
            "Active curation 'verse_swap_v1' open, STG-A..STG-D tracks "
            "populated with at least 4 pads on STG-A."
        ),
        used_by=(
            "smoke_5_load_curation",
            "smoke_6_switch_curation",
            "smoke_7_reanchor",
            "smoke_8_bounce",
            "smoke_9_export",
            "smoke_10_stale",
        ),
    ),
)


def parse_fixture_status(path: Path) -> FixtureStatus:
    """Inspect a fixture path and classify it.

    Returns:
        MISSING — file does not exist or is a ``.gitkeep`` placeholder.
        CORRUPT — file exists but isn't a gzipped XML (Live's format).
        PRESENT — file exists, gunzips, starts with ``<?xml``.
    """
    if not path.exists():
        return FixtureStatus.MISSING
    if path.is_dir():
        return FixtureStatus.CORRUPT
    # A .gitkeep sibling beside a missing fixture is the canonical
    # "placeholder" — but the placeholder is the *.gitkeep*, not the
    # fixture path itself. If the caller asks for the .als and it's
    # absent, return MISSING regardless of whether a sibling .gitkeep
    # exists.
    try:
        with path.open("rb") as f:
            raw = f.read(4096)
    except OSError:
        return FixtureStatus.CORRUPT
    if len(raw) < 2:
        return FixtureStatus.CORRUPT
    # gzip magic = 1f 8b
    if raw[:2] != b"\x1f\x8b":
        return FixtureStatus.CORRUPT
    try:
        with gzip.open(io.BytesIO(raw), "rt", encoding="utf-8", errors="replace") as gf:
            head = gf.read(64)
    except OSError:
        return FixtureStatus.CORRUPT
    if not head.lstrip().startswith("<?xml"):
        return FixtureStatus.CORRUPT
    return FixtureStatus.PRESENT


def spec_for(filename: str) -> FixtureSpec | None:
    for spec in FIXTURE_INVENTORY:
        if spec.filename == filename:
            return spec
    return None


def fixture_path(fixtures_dir: Path, filename: str) -> Path:
    return fixtures_dir / filename


def all_statuses(fixtures_dir: Path) -> dict[str, FixtureStatus]:
    """Bulk-classify every fixture in the inventory."""
    return {
        spec.filename: parse_fixture_status(fixture_path(fixtures_dir, spec.filename))
        for spec in FIXTURE_INVENTORY
    }


def minimal_skeleton_als_bytes() -> bytes:
    """Return the bytes of a minimal hand-crafted Live set.

    Per the Phase 5 spec (option 3 in the plan): we ship ONE minimal
    skeleton for ``empty-staging.als`` so the "can the runner even talk
    to Live" smoke (smoke_1) has a real artifact to point at. The
    skeleton is the bare minimum Live needs to parse: an ``<Ableton>``
    root with a ``LiveSet`` and ``MajorVersion``/``MinorVersion``/
    ``Creator``/``Revision`` attributes. Live will load it (possibly
    with a "this set was created with a different version" warning),
    show an empty Session view, and the device M4L file can be dragged
    in by the operator the first time.

    NOTE — this skeleton is "open-able" but probably not "save-able as-
    is": Live will normalize it on first save. That's fine; the
    smoke_1 test only opens-and-asserts-device-boots; it does not
    require Live to roundtrip the file.

    Live `.als` files are gzip-compressed XML. We return the gzipped
    bytes so the caller can write them straight to ``empty-staging.als``.
    """
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<Ableton MajorVersion="5" MinorVersion="12.0_12049" '
        'Creator="Ableton Live 12.0.5" Revision="0">\n'
        "  <LiveSet>\n"
        "    <Tracks/>\n"
        "    <MainTrack>\n"
        "      <DeviceChain>\n"
        "        <Devices/>\n"
        "      </DeviceChain>\n"
        "    </MainTrack>\n"
        "  </LiveSet>\n"
        "</Ableton>\n"
    )
    return gzip.compress(xml.encode("utf-8"))
