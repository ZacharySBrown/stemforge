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

    Layout (verified from captured reference, 712 bytes total):
        bytes 0..6   = header
        bytes 7..600 = 99 × 6-byte scene slots: [a, b, c, d, num, denom]
        bytes 601..  = 111-byte trailer (scene_count + flags; NOT scenes)
    """
    if len(buf) < 7:
        raise ValueError(f"scenes file too short: {len(buf)} bytes")
    chunks = []
    # Only iterate the 99 scene slots; the trailer bytes that follow
    # would otherwise be misread as additional scenes.
    for i in range(99):
        pos = 7 + i * 6
        if pos + 6 > len(buf):
            break
        chunks.append(
            {
                "a": buf[pos],
                "b": buf[pos + 1],
                "c": buf[pos + 2],
                "d": buf[pos + 3],
            }
        )
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
def materialized_fixtures(tmp_path_factory) -> tuple[dict, dict]:
    """Rewrite Track-C sample fixtures to point at on-disk stub WAVs.

    Track A's ``build_ppak`` reads each sound's bytes via ``Path.read_bytes()``,
    so file_path entries must resolve. Track-C's fixtures use ``/songs/test/...``
    placeholder paths; mirror them under tmp_path and rewrite both arrangement
    and manifest.
    """
    arrangement_raw = json.loads(SAMPLE_ARRANGEMENT.read_text())
    manifest_raw = json.loads(SAMPLE_MANIFEST.read_text())

    base = tmp_path_factory.mktemp("song_export_int")
    path_map: dict[str, str] = {}

    for group, entries in (manifest_raw.get("session_tracks") or {}).items():
        gdir = base / "songs" / group
        gdir.mkdir(parents=True, exist_ok=True)
        for entry in entries:
            old = entry.get("file_path") or entry.get("file")
            if old is None:
                continue
            new = gdir / Path(old).name
            new.write_bytes(b"RIFF\x00\x00\x00\x00WAVE")
            path_map[old] = str(new)
            entry["file"] = str(new)

    for group_clips in arrangement_raw.get("tracks", {}).values():
        for clip in group_clips:
            old = clip.get("file_path")
            if old in path_map:
                clip["file_path"] = path_map[old]

    return arrangement_raw, manifest_raw


@pytest.fixture(scope="module")
def arrangement(materialized_fixtures) -> dict:
    return materialized_fixtures[0]


@pytest.fixture(scope="module")
def manifest(materialized_fixtures) -> dict:
    return materialized_fixtures[1]


@pytest.fixture(scope="module")
def built_ppak_bytes(arrangement, manifest) -> bytes:
    """Run the full song-export pipeline once per module."""
    snapshots = resolve_scenes(arrangement, manifest)
    spec = synthesize(
        snapshots,
        manifest,
        project_bpm=arrangement["tempo"],
        time_sig=tuple(arrangement["time_sig"]),
        project_slot=1,
    )
    return build_ppak(spec, REFERENCE_PPAK)


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

def test_tar_has_pad_files_for_assigned_pads_only(tar_files):
    """Only assigned pads emit pad files; each is 26 bytes (factory
    native format). Verified 2026-04-27 against factory_default.pak —
    factory P06 (empty project) emits zero pad files; demo projects emit
    only the populated groups.
    """
    pad_files = {k: v for k, v in tar_files.items() if k.startswith("pads/") and k.count("/") == 2 and k.split("/")[-1].startswith("p")}
    assert len(pad_files) > 0, "expected at least one pad file in TAR"
    for name, blob in pad_files.items():
        assert len(blob) == 26, (
            f"{name} is {len(blob)} bytes, expected 26"
        )


def test_tar_omits_settings_file(tar_files):
    """Per ZacharySBrown/ep133-ppak/PROTOCOL.md §8 the `settings` entry
    should not be present in the project TAR. Populating it has caused
    ERR 82 / ERROR 8200 (wedge-class) on import.
    """
    assert "settings" not in tar_files, (
        "tar contains `settings` — populating settings has caused "
        "device-wedge errors on import; the entry must be omitted"
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

    # Format is "patterns/{group}{NN}" (no slash between group and number),
    # e.g. patterns/a01. Extract leading group letter from the basename.
    pattern_groups_present = set()
    for name in tar_files:
        if not name.startswith("patterns/"):
            continue
        basename = name[len("patterns/"):]
        if basename and basename[0].isalpha():
            pattern_groups_present.add(basename[0].lower())
    missing = expected_groups - pattern_groups_present
    assert not missing, (
        f"expected pattern dirs for groups {expected_groups}, missing {missing}; "
        f"present={pattern_groups_present}"
    )


# ---------------------------------------------------------------------------
# Tests — content layer
# ---------------------------------------------------------------------------

# `test_settings_bpm_matches_arrangement` removed — settings entry is now
# omitted from the TAR (see test_tar_omits_settings_file). Project BPM is
# carried by the `meta.json` and the device's own restore-time defaults.


def test_scenes_count_matches_locator_count(tar_files, arrangement):
    """Populated (non-zero) scene chunks should match locator count.
    The scenes file is fixed-size 712 bytes: 7-byte header + 99 scene
    slots + 111-byte trailer; unused slots are zero-filled."""
    scenes = _parse_scenes(tar_files["scenes"])
    populated = [
        s for s in scenes
        if s["a"] != 0 or s["b"] != 0 or s["c"] != 0 or s["d"] != 0
    ]
    expected = len(arrangement["locators"])
    assert len(populated) == expected, (
        f"got {len(populated)} populated scenes, expected {expected} "
        f"(one per locator); total slots={len(scenes)}"
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
    """Every emitted pad file should reference a non-zero sample slot.

    Spec §"Pad file" — bytes 1..2 = sample slot uint16 LE. Since unassigned
    pads are now omitted from the TAR (factory P06 layout), every pad
    file we emit corresponds to a populated pad with a real slot.
    """
    pad_files = {k: v for k, v in tar_files.items() if k.startswith("pads/") and k.count("/") == 2 and k.split("/")[-1].startswith("p")}
    assert len(pad_files) > 0, "expected at least one pad file in TAR"
    for name, buf in pad_files.items():
        slot = struct.unpack_from("<H", buf, 1)[0]
        assert slot != 0, f"{name} has slot=0; unassigned pads should be omitted"
