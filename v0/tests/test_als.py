"""Structural tests for ``StemForge.als`` (Track D output).

All tests here SKIP cleanly if ``v0/build/StemForge.als`` is not present —
Track D is currently blocked on ``v0/assets/skeleton.als`` (see
``v0/state/D/blocker.md``). Once the skeleton lands and D regenerates the
.als, this suite begins running without further changes.

We parse with the stdlib ``xml.etree`` rather than adding an ``lxml``
dependency — the checks here are structural (tag names, string matches) and
don't need lxml's extra features.
"""
from __future__ import annotations

import gzip
import xml.etree.ElementTree as ET
from pathlib import Path


# ── helpers ────────────────────────────────────────────────────────────────

def _parse_als(als_path: Path) -> ET.ElementTree:
    with gzip.open(als_path, "rb") as f:
        return ET.parse(f)


def _track_names(tree: ET.ElementTree) -> set[str]:
    """Collect effective names across all track types.

    Live stores names as ``Name/EffectiveName@Value`` on tracks; to be
    resilient to Live version drift we collect from a few candidate paths.
    """
    names: set[str] = set()
    root = tree.getroot()
    for el in root.iter():
        tag = el.tag.rsplit("}", 1)[-1]
        if tag in ("EffectiveName", "UserName", "MemorizedFirstClipName"):
            val = el.get("Value")
            if val:
                names.add(val)
    return names


def _find_track_by_name(tree: ET.ElementTree, name: str):
    """Find the track element whose EffectiveName equals ``name``.

    Returns the containing ``AudioTrack`` / ``MidiTrack`` element, or None.
    """
    root = tree.getroot()
    for track_el in root.iter():
        tag = track_el.tag.rsplit("}", 1)[-1]
        if tag not in ("AudioTrack", "MidiTrack"):
            continue
        for name_el in track_el.iter():
            name_tag = name_el.tag.rsplit("}", 1)[-1]
            if name_tag == "EffectiveName" and name_el.get("Value") == name:
                return track_el
    return None


# ── tests ──────────────────────────────────────────────────────────────────

def test_als_exists(als_path: Path) -> None:
    """File is present (else skipped) and is large enough to be real."""
    assert als_path.exists()
    assert als_path.stat().st_size > 512, f"implausibly small: {als_path.stat().st_size}"


def test_als_is_gzip_xml(als_path: Path) -> None:
    """``StemForge.als`` is a gzip stream containing well-formed XML."""
    tree = _parse_als(als_path)
    assert tree.getroot() is not None


def test_als_root_tag(als_path: Path) -> None:
    """Live sets have a root element named ``Ableton``."""
    tree = _parse_als(als_path)
    root_tag = tree.getroot().tag.rsplit("}", 1)[-1]  # strip any namespace
    assert root_tag == "Ableton", f"unexpected root tag: {root_tag!r}"


def test_als_has_expected_tracks(als_path: Path, tracks_yaml: dict) -> None:
    """Every track name from tracks.yaml appears in the .als."""
    tree = _parse_als(als_path)
    names = _track_names(tree)
    missing = [t["name"] for t in tracks_yaml["tracks"] if t["name"] not in names]
    assert not missing, (
        f"tracks from tracks.yaml missing in .als: {missing}. "
        f"Names seen: {sorted(names)}"
    )


def test_als_device_chains(als_path: Path) -> None:
    """Spot-check: ``SF | Drums Raw`` has Compressor as its first device.

    Per tracks.yaml, drums_raw's device chain starts with a stock Compressor.
    We search the track subtree for any element whose local name is
    ``Compressor2`` / ``Compressor`` (Live's internal class names).
    """
    tree = _parse_als(als_path)
    track = _find_track_by_name(tree, "SF | Drums Raw")
    assert track is not None, "SF | Drums Raw track not present in .als"

    compressor_tags = {"Compressor", "Compressor2"}
    found = False
    for el in track.iter():
        local = el.tag.rsplit("}", 1)[-1]
        if local in compressor_tags:
            found = True
            break
    assert found, (
        "SF | Drums Raw has no Compressor device in its chain "
        "(expected per tracks.yaml drums_raw.chain[0])"
    )
