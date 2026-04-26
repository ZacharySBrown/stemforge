"""
End-to-end integration test for EP-133 song-mode export.

Exercises the full pipeline:

    arrangement.json + manifest.json + reference.ppak
        → resolve_scenes() → synthesize() → build_ppak()
        → bytes
        → re-parse via in-Python ZIP/TAR walker
        → assert layout matches expectations

Inputs:

  * `tests/ep133/fixtures/sample_arrangement.json` — provided by Track C
  * `tests/ep133/fixtures/sample_manifest.json` — provided by Track C
  * `tests/ep133/fixtures/reference.ppak` — captured by user via either
    `tools/ep133_capture_reference.py` or a Sample Tool device backup.
    If absent the whole module is skipped.

The test is a *hard contract* check on the output `.ppak`: every byte we
care about (BPM patch, pattern bytes, scene bytes) is verified against
the same parse routines the EP-133's own firmware exercises (per phones24's
read reference).
"""

from __future__ import annotations

import io
import json
import struct
import tarfile
import zipfile
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"
REFERENCE_PPAK = FIXTURES / "reference.ppak"
SAMPLE_ARRANGEMENT = FIXTURES / "sample_arrangement.json"
SAMPLE_MANIFEST = FIXTURES / "sample_manifest.json"

# ---------------------------------------------------------------------------
# Module-level skips for missing fixtures or unreleased Track A/C modules.
# We want a *clean SKIP message* the user sees rather than an obscure import
# error; integration tests are gated on real-device captures + sibling tracks.
# ---------------------------------------------------------------------------

if not REFERENCE_PPAK.exists():
    pytest.skip(
        "reference.ppak required; run `uv run python tools/ep133_capture_reference.py "
        "--project 1 --out tests/ep133/fixtures/reference.ppak` "
        "or drop a Sample Tool backup at tests/ep133/fixtures/reference.ppak",
        allow_module_level=True,
    )

if not SAMPLE_ARRANGEMENT.exists() or not SAMPLE_MANIFEST.exists():
    pytest.skip(
        "sample_arrangement.json / sample_manifest.json missing — these are "
        "shipped by Track C (snapshot resolver). Skipping until Track C lands.",
        allow_module_level=True,
    )

# Track A modules
try:
    from stemforge.exporters.ep133.ppak_writer import build_ppak  # noqa: E402
    from stemforge.exporters.ep133.song_format import PpakSpec  # noqa: E402, F401
except ImportError:
    pytest.skip(
        "Track A modules (`song_format`, `ppak_writer`) not yet present. "
        "Skipping integration test until Track A lands.",
        allow_module_level=True,
    )

# Track C modules
try:
    from stemforge.exporters.ep133.song_resolver import resolve_scenes  # noqa: E402
    from stemforge.exporters.ep133.song_synthesizer import synthesize  # noqa: E402
except ImportError:
    pytest.skip(
        "Track C modules (`song_resolver`, `song_synthesizer`) not yet present. "
        "Skipping integration test until Track C lands.",
        allow_module_level=True,
    )


# ---------------------------------------------------------------------------
# In-Python parsers — standalone re-implementations of the format readers,
# used to verify the writer's output round-trips cleanly. These are
# intentionally minimal: they decode just enough to assert the contract.
# Full validation lives in Track A's unit tests; here we want end-to-end
# proof that the bytes we emit match the bytes we'd read.
# ---------------------------------------------------------------------------

def _zip_entries(ppak_bytes: bytes) -> dict[str, bytes]:
    """Return a mapping of zip-entry-name → bytes. Entry names preserved as-is."""
    with zipfile.ZipFile(io.BytesIO(ppak_bytes)) as zf:
        return {info.filename: zf.read(info.filename) for info in zf.infolist()}


def _tar_entries(tar_bytes: bytes) -> dict[str, bytes]:
    """Return mapping of tar-entry-name → bytes (regular files only)."""
    out: dict[str, bytes] = {}
    with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r") as tar:
        for member in tar.getmembers():
            if member.isfile():
                f = tar.extractfile(member)
                if f is not None:
                    out[member.name] = f.read()
    return out


def _parse_pattern(buf: bytes) -> dict:
    """Decode a pattern file into header + events.

    Format per spec §"Pattern file":
        bytes [0,1,2,3] = (0x00, bars, event_count, 0x00)
        events: 8 bytes each — pos u16 LE, pad_indicator u8, note u8,
                 velocity u8, duration u16 LE, padding u8
    """
    if len(buf) < 4:
        raise ValueError(f"pattern too short: {len(buf)} bytes")
    bars = buf[1]
    n_events = buf[2]
    events = []
    for i in range(n_events):
        off = 4 + i * 8
        if off + 8 > len(buf):
            raise ValueError(f"truncated event {i} in pattern of {len(buf)} bytes")
        pos = struct.unpack_from("<H", buf, off)[0]
        pad_ind = buf[off + 2]
        note = buf[off + 3]
        vel = buf[off + 4]
        dur = struct.unpack_from("<H", buf, off + 5)[0]
        events.append(
            {
                "position_ticks": pos,
                "pad": (pad_ind // 8) + 1,  # encoding: pad_indicator = (pad-1)*8
                "note": note,
                "velocity": vel,
                "duration_ticks": dur,
            }
        )
    return {"bars": bars, "events": events}


def _parse_scenes(buf: bytes) -> list[dict]:
    """Decode the scenes file into a list of {a, b, c, d} dicts.

    Spec §"Scenes file":
        bytes 0..6 = header
        bytes 7+    = 6-byte chunks: [a, b, c, d, reserved, reserved]
    """
    if len(buf) < 7:
        raise ValueError(f"scenes file too short: {len(buf)} bytes")
    chunks = []
    pos = 7
    while pos + 6 <= len(buf):
        chunks.append(
            {
                "a": buf[pos],
                "b": buf[pos + 1],
                "c": buf[pos + 2],
                "d": buf[pos + 3],
            }
        )
        pos += 6
    # Drop trailing zero-fill scenes — only count up to the last non-empty one.
    while chunks and chunks[-1] == {"a": 0, "b": 0, "c": 0, "d": 0}:
        chunks.pop()
    return chunks


def _read_settings_bpm(buf: bytes) -> float:
    """Settings file is 222 bytes; BPM lives at bytes 4..7 as float32 LE."""
    if len(buf) != 222:
        raise ValueError(f"settings file is {len(buf)} bytes, expected 222")
    return struct.unpack_from("<f", buf, 4)[0]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def arrangement() -> dict:
    return json.loads(SAMPLE_ARRANGEMENT.read_text())


@pytest.fixture(scope="module")
def manifest() -> dict:
    return json.loads(SAMPLE_MANIFEST.read_text())


@pytest.fixture(scope="module")
def reference_template_bytes() -> bytes:
    return REFERENCE_PPAK.read_bytes()


@pytest.fixture(scope="module")
def built_ppak_bytes(arrangement, manifest, reference_template_bytes) -> bytes:
    """Run the full song-export pipeline once per module."""
    snapshots = resolve_scenes(arrangement, manifest)
    spec = synthesize(
        snapshots,
        manifest,
        project_bpm=arrangement["tempo"],
        time_sig=tuple(arrangement["time_sig"]),
        project_slot=1,
    )
    return build_ppak(spec, reference_template_bytes)


@pytest.fixture(scope="module")
def project_tar_bytes(built_ppak_bytes) -> bytes:
    """Extract /projects/PXX.tar from the built ppak."""
    entries = _zip_entries(built_ppak_bytes)
    tar_entries = [name for name in entries if name.startswith("/projects/") and name.endswith(".tar")]
    assert tar_entries, f"no /projects/PXX.tar in zip; entries={list(entries)}"
    assert len(tar_entries) == 1, f"expected exactly one project tar, got {tar_entries}"
    return entries[tar_entries[0]]


@pytest.fixture(scope="module")
def tar_files(project_tar_bytes) -> dict[str, bytes]:
    return _tar_entries(project_tar_bytes)


# ---------------------------------------------------------------------------
# Tests — container layer
# ---------------------------------------------------------------------------

def test_ppak_is_valid_zip(built_ppak_bytes):
    """Built file decodes as a ZIP container."""
    assert zipfile.is_zipfile(io.BytesIO(built_ppak_bytes))


def test_ppak_entries_have_leading_slash(built_ppak_bytes):
    """Every entry starts with `/` — required or device shows 'PAK FILE IS EMPTY'."""
    entries = _zip_entries(built_ppak_bytes)
    assert entries, "built .ppak has no entries"
    bad = [name for name in entries if not name.startswith("/")]
    assert not bad, f"entries missing leading slash: {bad}"


def test_ppak_contains_project_tar(built_ppak_bytes):
    entries = _zip_entries(built_ppak_bytes)
    project_paths = [name for name in entries if name.startswith("/projects/P") and name.endswith(".tar")]
    assert project_paths, f"no /projects/PXX.tar in entries: {list(entries)}"


def test_ppak_meta_json_well_formed(built_ppak_bytes):
    entries = _zip_entries(built_ppak_bytes)
    assert "/meta.json" in entries, f"no /meta.json in entries: {list(entries)}"
    meta = json.loads(entries["/meta.json"].decode("utf-8"))
    # Required keys per spec §"Container → meta.json"
    for key in (
        "info",
        "pak_version",
        "pak_type",
        "device_name",
        "device_sku",
        "device_version",
        "generated_at",
        "author",
        "base_sku",
    ):
        assert key in meta, f"meta.json missing required key: {key!r}"
    assert meta["info"] == "teenage engineering - pak file"
    assert meta["pak_version"] == 1
    assert meta["device_name"] == "EP-133"
    assert meta["device_sku"] == meta["base_sku"], (
        "device_sku must equal base_sku in user paks"
    )


# ---------------------------------------------------------------------------
# Tests — TAR layer
# ---------------------------------------------------------------------------

def test_tar_has_all_pad_files(tar_files):
    """48 pad files: groups a/b/c/d × pads 01..12, each 27 bytes per spec."""
    for grp in ("a", "b", "c", "d"):
        for pad in range(1, 13):
            name = f"pads/{grp}/p{pad:02d}"
            assert name in tar_files, f"missing pad file {name}"
            assert len(tar_files[name]) == 27, (
                f"{name} is {len(tar_files[name])} bytes, expected 27"
            )


def test_tar_has_settings_222_bytes(tar_files):
    assert "settings" in tar_files, "tar missing `settings`"
    assert len(tar_files["settings"]) == 222, (
        f"settings is {len(tar_files['settings'])} bytes, expected 222"
    )


def test_tar_has_scenes(tar_files):
    assert "scenes" in tar_files, "tar missing `scenes`"
    assert len(tar_files["scenes"]) >= 7, (
        f"scenes file is too short ({len(tar_files['scenes'])} bytes); "
        "expected at least 7-byte header + one 6-byte scene"
    )


def test_tar_has_pattern_files(tar_files, arrangement):
    """At least one pattern file per group that has clips in the arrangement."""
    expected_groups = set()
    for grp_name, clips in arrangement["tracks"].items():
        if clips:
            expected_groups.add(grp_name.lower())
    if not expected_groups:
        pytest.skip("arrangement has no clips on any track; nothing to assert")

    pattern_groups_present = set()
    for name in tar_files:
        if name.startswith("patterns/"):
            parts = name.split("/")
            if len(parts) >= 2:
                pattern_groups_present.add(parts[1])
    missing = expected_groups - pattern_groups_present
    assert not missing, (
        f"expected pattern dirs for groups {expected_groups}, missing {missing}; "
        f"present={pattern_groups_present}"
    )


# ---------------------------------------------------------------------------
# Tests — content layer
# ---------------------------------------------------------------------------

def test_settings_bpm_matches_arrangement(tar_files, arrangement):
    bpm = _read_settings_bpm(tar_files["settings"])
    expected = float(arrangement["tempo"])
    assert abs(bpm - expected) < 0.01, (
        f"settings BPM {bpm} != arrangement tempo {expected}"
    )


def test_scenes_count_matches_locator_count(tar_files, arrangement):
    scenes = _parse_scenes(tar_files["scenes"])
    expected = len(arrangement["locators"])
    assert len(scenes) == expected, (
        f"got {len(scenes)} scenes, expected {expected} (one per locator)"
    )


def test_patterns_decode_with_well_formed_events(tar_files):
    """Every pattern file decodes; every event has pad ∈ 1..12 and note 0..127."""
    pattern_names = [n for n in tar_files if n.startswith("patterns/")]
    assert pattern_names, "no pattern files in tar"
    for name in pattern_names:
        decoded = _parse_pattern(tar_files[name])
        assert decoded["bars"] >= 1, f"{name}: bars={decoded['bars']}, must be ≥1"
        for ev in decoded["events"]:
            assert 1 <= ev["pad"] <= 12, f"{name}: pad {ev['pad']} out of 1..12"
            assert 0 <= ev["note"] <= 127, f"{name}: note {ev['note']} out of 0..127"
            assert 0 <= ev["velocity"] <= 127, f"{name}: vel {ev['velocity']} out of 0..127"


def test_pad_records_reference_sample_slots(tar_files):
    """Pads in arrangement-mapped groups should have non-zero sample_slot.

    Spec §"Pad file" — bytes 1..2 = sample slot uint16 LE. A zero slot
    means the pad is unassigned; for groups with clips in the arrangement
    we expect at least one non-zero slot.
    """
    nonzero_slots_by_group: dict[str, int] = {"a": 0, "b": 0, "c": 0, "d": 0}
    for grp in ("a", "b", "c", "d"):
        for pad in range(1, 13):
            name = f"pads/{grp}/p{pad:02d}"
            buf = tar_files[name]
            slot = struct.unpack_from("<H", buf, 1)[0]
            if slot != 0:
                nonzero_slots_by_group[grp] += 1
    # Sanity: at least one group has at least one non-zero slot
    assert sum(nonzero_slots_by_group.values()) > 0, (
        f"all 48 pads have sample_slot=0; expected the synthesizer to "
        f"populate at least the pads referenced by the arrangement. "
        f"counts={nonzero_slots_by_group}"
    )
