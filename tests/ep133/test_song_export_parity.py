"""Byte-identity parity test for the EP-133 song-export pipeline.

Pins the per-entry SHA256 of every byte the song-export pipeline emits for
the canonical ``sample_arrangement.json`` + ``sample_manifest.json`` fixture.
The integration test (``test_song_integration.py``) verifies that the bytes
*decode* correctly; this test verifies that they don't *change* unexpectedly.

It exists to make the Configurator Phase 1 lift acceptance gate ("byte-
identical ``.ppak`` for every fixture") verifiable in CI:

    pre-lift  : parity test passes — captured baseline.
    post-lift : parity test still passes — lift did not alter outputs.

The fixed ``generated_at`` patch sidesteps the only nondeterministic field
in the writer (``meta.json.generated_at`` = ``datetime.now(...)``); every
other field is already deterministic (``date_time=(1980,1,1,0,0,0)`` on
ZIP entries, ``mtime=0`` on TAR entries).

If a deliberate change to the export pipeline updates these bytes, regen
the baseline with the helper script printed at the bottom of this file
and update the constants.
"""

from __future__ import annotations

import hashlib
import io
import json
import tarfile
import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest

FIXTURES = Path(__file__).parent / "fixtures"
REFERENCE_PPAK = FIXTURES / "reference.ppak"
SAMPLE_ARRANGEMENT = FIXTURES / "sample_arrangement.json"
SAMPLE_MANIFEST = FIXTURES / "sample_manifest.json"

if not REFERENCE_PPAK.exists():
    pytest.skip(
        "reference.ppak required (same gating as test_song_integration.py)",
        allow_module_level=True,
    )

if not SAMPLE_ARRANGEMENT.exists() or not SAMPLE_MANIFEST.exists():
    pytest.skip(
        "sample_arrangement.json / sample_manifest.json missing",
        allow_module_level=True,
    )

from stemforge.exporters.ep133.ppak_writer import build_ppak  # noqa: E402
from stemforge.exporters.ep133.song_resolver import resolve_scenes  # noqa: E402
from stemforge.exporters.ep133.song_synthesizer import synthesize  # noqa: E402

# Frozen timestamp for the only nondeterministic field. Any value is fine —
# what matters is that pre-lift and post-lift use the same value.
FIXED_GENERATED_AT = "2026-05-08T20:00:00.000Z"

# Captured pre-lift on 2026-05-08 (commit before Configurator Phase 1).
EXPECTED_OVERALL_LEN = 1758
EXPECTED_OVERALL_SHA256 = "53bdc105369919ca15556c07798180a697d3242dfd3883675c874829f0a7c1ba"

EXPECTED_ZIP_ENTRIES: dict[str, tuple[int, str]] = {
    "/meta.json": (301, "3bdbd9093e2ab58dd1aca932415321aeabfeda8a5430dcd6f8d40e30e2c59f0d"),
    "/projects/P01.tar": (30720, "cf8b3f04d722adf0f57a00eb46bfa03adefaa9fb362a05989403066a30a76a03"),
    "/sounds/700 700_loop_a1.wav": (
        12,
        "56ddf20bae94693a26732a7629d110957d63d8afd31c95f098b32b0d9ec5b387",
    ),
    "/sounds/701 701_loop_a2.wav": (
        12,
        "56ddf20bae94693a26732a7629d110957d63d8afd31c95f098b32b0d9ec5b387",
    ),
    "/sounds/702 702_loop_a3.wav": (
        12,
        "56ddf20bae94693a26732a7629d110957d63d8afd31c95f098b32b0d9ec5b387",
    ),
    "/sounds/720 720_bass_b1.wav": (
        12,
        "56ddf20bae94693a26732a7629d110957d63d8afd31c95f098b32b0d9ec5b387",
    ),
    "/sounds/721 721_bass_b2.wav": (
        12,
        "56ddf20bae94693a26732a7629d110957d63d8afd31c95f098b32b0d9ec5b387",
    ),
    "/sounds/740 740_vox_c1.wav": (
        12,
        "56ddf20bae94693a26732a7629d110957d63d8afd31c95f098b32b0d9ec5b387",
    ),
}

EXPECTED_TAR_ENTRIES: dict[str, tuple[int, str]] = {
    "pads/a/p01": (26, "af0ae0af1ae4183d05b755bf15352c5cff140c1d51002d837449f1aa035e9d23"),
    "pads/a/p02": (26, "6888345d9dea704afc3d70eaf44209a7a00ab3d646efdba862aa900f63c2efb4"),
    "pads/a/p03": (26, "06c0c659c93a7e3bb4d62dcf45d3685e07b35da408ff62418b8b83f8e7033845"),
    "pads/b/p01": (26, "642e849e796e39d6d041aa4ec831cb23b49d5750a7df04aa17abd421a96f209c"),
    "pads/b/p02": (26, "5a576fb37ce0587012d0b1675d8d40d42ae6d4067104fb6c686af40de964141a"),
    "pads/c/p01": (26, "b87e8df74bbd48174ad932d8a20886af4ff134e327dd4110134442909a0d0166"),
    "patterns/a01": (12, "d9b06ef4a3ce94090176ffb3c3a1508d9b7b80e1481a9cbaeb210c9f6be798b6"),
    "patterns/a02": (20, "efc5feae6bf22f8afa9451c32a06edaa9b599f1a8b0bcd393c7b42897b49bbf3"),
    "patterns/a03": (12, "5d89580aa8fdf3f6fd75cec03c7fc8d014e0510388cc410fbe11085849226156"),
    "patterns/b01": (12, "d9b06ef4a3ce94090176ffb3c3a1508d9b7b80e1481a9cbaeb210c9f6be798b6"),
    "patterns/b02": (20, "efc5feae6bf22f8afa9451c32a06edaa9b599f1a8b0bcd393c7b42897b49bbf3"),
    "patterns/c01": (12, "d9b06ef4a3ce94090176ffb3c3a1508d9b7b80e1481a9cbaeb210c9f6be798b6"),
    "patterns/c99": (4, "6e1ae50c2c807c6630b5a02ea29761a723e422e503100fc2ee23f2d715d3a001"),
    "patterns/d05": (4, "bc3817c13bc4e6f192a840895fa937d252db153efb89bb14a6c2ddf1f9c55409"),
    "patterns/d99": (4, "6e1ae50c2c807c6630b5a02ea29761a723e422e503100fc2ee23f2d715d3a001"),
    "scenes": (712, "ac32e2e6c65164f8a089a45288cf49d13199e28deae2e28ca96b93de72e28431"),
}


def _materialize(tmp_path: Path) -> tuple[dict, dict]:
    """Mirror sample manifest paths under tmp_path (same as test_song_integration)."""
    arrangement_raw = json.loads(SAMPLE_ARRANGEMENT.read_text())
    manifest_raw = json.loads(SAMPLE_MANIFEST.read_text())

    path_map: dict[str, str] = {}
    for group, entries in (manifest_raw.get("session_tracks") or {}).items():
        gdir = tmp_path / "songs" / group
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
def baseline_payload(tmp_path_factory) -> bytes:
    base = tmp_path_factory.mktemp("song_export_parity")
    arrangement, manifest = _materialize(base)
    snapshots = resolve_scenes(arrangement, manifest)
    spec = synthesize(
        snapshots,
        manifest,
        project_bpm=arrangement["tempo"],
        time_sig=tuple(arrangement["time_sig"]),
        project_slot=1,
    )
    with patch(
        "stemforge.exporters.ep133.ppak_writer._utc_iso8601",
        return_value=FIXED_GENERATED_AT,
    ):
        return build_ppak(spec, REFERENCE_PPAK)


def test_overall_ppak_bytes_unchanged(baseline_payload):
    assert len(baseline_payload) == EXPECTED_OVERALL_LEN, (
        f"overall .ppak length changed: {len(baseline_payload)} vs "
        f"{EXPECTED_OVERALL_LEN}. Investigate before regenerating the baseline."
    )
    actual = hashlib.sha256(baseline_payload).hexdigest()
    assert actual == EXPECTED_OVERALL_SHA256, (
        f"overall .ppak SHA256 changed: {actual} vs {EXPECTED_OVERALL_SHA256}. "
        "Per-entry assertions below should localize the diff."
    )


def test_zip_entry_set_matches_baseline(baseline_payload):
    with zipfile.ZipFile(io.BytesIO(baseline_payload)) as zf:
        present = {info.filename for info in zf.infolist()}
    expected = set(EXPECTED_ZIP_ENTRIES)
    assert present == expected, (
        f"zip entry set changed.\n  added:   {sorted(present - expected)}\n"
        f"  removed: {sorted(expected - present)}"
    )


def test_zip_entry_bytes_unchanged(baseline_payload):
    with zipfile.ZipFile(io.BytesIO(baseline_payload)) as zf:
        for name, (expected_len, expected_sha) in EXPECTED_ZIP_ENTRIES.items():
            data = zf.read(name)
            actual_len = len(data)
            actual_sha = hashlib.sha256(data).hexdigest()
            assert (actual_len, actual_sha) == (expected_len, expected_sha), (
                f"zip entry {name!r} drifted: "
                f"len {actual_len}≠{expected_len} or sha {actual_sha}≠{expected_sha}"
            )


def test_tar_entry_set_matches_baseline(baseline_payload):
    with zipfile.ZipFile(io.BytesIO(baseline_payload)) as zf:
        tar_bytes = zf.read("/projects/P01.tar")
    with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r") as tar:
        present = {m.name for m in tar.getmembers() if m.isfile()}
    expected = set(EXPECTED_TAR_ENTRIES)
    assert present == expected, (
        f"tar entry set changed.\n  added:   {sorted(present - expected)}\n"
        f"  removed: {sorted(expected - present)}"
    )


def test_tar_entry_bytes_unchanged(baseline_payload):
    with zipfile.ZipFile(io.BytesIO(baseline_payload)) as zf:
        tar_bytes = zf.read("/projects/P01.tar")
    with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r") as tar:
        members = {m.name: m for m in tar.getmembers() if m.isfile()}
        for name, (expected_len, expected_sha) in EXPECTED_TAR_ENTRIES.items():
            f = tar.extractfile(members[name])
            assert f is not None, f"could not extract {name}"
            data = f.read()
            actual_len = len(data)
            actual_sha = hashlib.sha256(data).hexdigest()
            assert (actual_len, actual_sha) == (expected_len, expected_sha), (
                f"tar entry {name!r} drifted: "
                f"len {actual_len}≠{expected_len} or sha {actual_sha}≠{expected_sha}"
            )


# To regenerate after a deliberate output change, run:
#
#     uv run python -c "from tests.ep133.test_song_export_parity import \
#         _print_baseline; _print_baseline()"
#
# then paste the new constants over the EXPECTED_* dicts above.


def _print_baseline() -> None:  # pragma: no cover — operator helper
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        arrangement, manifest = _materialize(Path(td))
        snapshots = resolve_scenes(arrangement, manifest)
        spec = synthesize(
            snapshots,
            manifest,
            project_bpm=arrangement["tempo"],
            time_sig=tuple(arrangement["time_sig"]),
            project_slot=1,
        )
        with patch(
            "stemforge.exporters.ep133.ppak_writer._utc_iso8601",
            return_value=FIXED_GENERATED_AT,
        ):
            payload = build_ppak(spec, REFERENCE_PPAK)
    print(f"EXPECTED_OVERALL_LEN = {len(payload)}")
    print(f"EXPECTED_OVERALL_SHA256 = {hashlib.sha256(payload).hexdigest()!r}")
    print("EXPECTED_ZIP_ENTRIES = {")
    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        for info in zf.infolist():
            data = zf.read(info.filename)
            print(f"    {info.filename!r}: ({len(data)}, {hashlib.sha256(data).hexdigest()!r}),")
    print("}")
    print("EXPECTED_TAR_ENTRIES = {")
    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        tar_bytes = zf.read("/projects/P01.tar")
    with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r") as tar:
        for member in sorted(tar.getmembers(), key=lambda m: m.name):
            if not member.isfile():
                continue
            f = tar.extractfile(member)
            if f is None:
                continue
            data = f.read()
            print(f"    {member.name!r}: ({len(data)}, {hashlib.sha256(data).hexdigest()!r}),")
    print("}")
