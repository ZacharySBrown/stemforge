"""End-to-end builder tests using a synthetic in-memory skeleton.

These tests do NOT require the real `v0/assets/skeleton.als` to exist.
They build a minimal Live-like XML skeleton, gzip it, hand it to
`build()`, then verify the output is:

  (a) gzipped valid XML
  (b) has exactly 7 tracks
  (c) each track's Name/EffectiveName and ColorIndex match tracks.yaml
  (d) stock device params propagate correctly
"""

from __future__ import annotations

import gzip
import sys
import xml.etree.ElementTree as stdlib_ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402

from builder import (  # noqa: E402
    build,
    load_tracks_spec,
)
from colors import hex_to_color_index  # noqa: E402


SKELETON_XML = """<?xml version="1.0" encoding="UTF-8"?>
<Ableton MajorVersion="5" MinorVersion="12.0_12049" SchemaChangeCount="3" Creator="Ableton Live 12.1.0" Revision="">
  <LiveSet>
    <Tracks>
      <AudioTrack Id="1">
        <LomId Value="0" />
        <LomIdView Value="0" />
        <Name>
          <EffectiveName Value="" />
          <UserName Value="" />
          <Annotation Value="" />
        </Name>
        <ColorIndex Value="13" />
        <DeviceChain>
          <DeviceChain>
            <Devices />
          </DeviceChain>
        </DeviceChain>
      </AudioTrack>
      <MidiTrack Id="2">
        <LomId Value="0" />
        <LomIdView Value="0" />
        <Name>
          <EffectiveName Value="" />
          <UserName Value="" />
          <Annotation Value="" />
        </Name>
        <ColorIndex Value="13" />
        <DeviceChain>
          <DeviceChain>
            <Devices />
          </DeviceChain>
        </DeviceChain>
      </MidiTrack>
    </Tracks>
  </LiveSet>
</Ableton>
"""


@pytest.fixture
def fake_skeleton(tmp_path: Path) -> Path:
    p = tmp_path / "skeleton.als"
    with gzip.open(p, "wb") as f:
        f.write(SKELETON_XML.encode("utf-8"))
    return p


@pytest.fixture
def output_path(tmp_path: Path) -> Path:
    return tmp_path / "StemForge.als"


def _read_als(path: Path) -> stdlib_ET.ElementTree:
    """Parse a gzipped Live Set using the stdlib XML parser only."""
    with gzip.open(path, "rb") as f:
        return stdlib_ET.parse(f)


def test_build_produces_gzipped_valid_xml(fake_skeleton, output_path):
    out = build(
        skeleton_path=fake_skeleton,
        output_path=output_path,
    )
    assert out == output_path
    assert output_path.exists()
    assert output_path.stat().st_size > 0

    # gzip magic bytes
    with output_path.open("rb") as f:
        assert f.read(2) == b"\x1f\x8b"

    # stdlib XML parses it cleanly
    tree = _read_als(output_path)
    assert tree.getroot() is not None


def test_build_has_seven_tracks(fake_skeleton, output_path):
    build(skeleton_path=fake_skeleton, output_path=output_path)
    tree = _read_als(output_path)
    root = tree.getroot()
    tracks = root.findall(".//LiveSet/Tracks/")
    assert len(tracks) == 7, f"expected 7 tracks, got {len(tracks)}: {[t.tag for t in tracks]}"


def test_build_track_names_match_yaml(fake_skeleton, output_path):
    build(skeleton_path=fake_skeleton, output_path=output_path)
    spec = load_tracks_spec()
    expected_names = [t["name"] for t in spec["tracks"]]

    tree = _read_als(output_path)
    root = tree.getroot()
    tracks = root.findall(".//LiveSet/Tracks/")
    actual_names = [
        t.find("./Name/EffectiveName").get("Value") for t in tracks
    ]
    assert actual_names == expected_names


def test_build_track_colors_match_palette_index(fake_skeleton, output_path):
    build(skeleton_path=fake_skeleton, output_path=output_path)
    spec = load_tracks_spec()
    expected_indices = [hex_to_color_index(t["color"]) for t in spec["tracks"]]

    tree = _read_als(output_path)
    root = tree.getroot()
    tracks = root.findall(".//LiveSet/Tracks/")
    actual = [int(t.find("./ColorIndex").get("Value")) for t in tracks]
    assert actual == expected_indices


def test_build_track_kinds_match_yaml(fake_skeleton, output_path):
    build(skeleton_path=fake_skeleton, output_path=output_path)
    spec = load_tracks_spec()
    expected_tags = [
        "AudioTrack" if t["type"] == "audio" else "MidiTrack"
        for t in spec["tracks"]
    ]

    tree = _read_als(output_path)
    root = tree.getroot()
    tracks = root.findall(".//LiveSet/Tracks/")
    actual_tags = [t.tag for t in tracks]
    assert actual_tags == expected_tags


def test_build_ids_are_unique(fake_skeleton, output_path):
    build(skeleton_path=fake_skeleton, output_path=output_path)
    tree = _read_als(output_path)
    ids = [
        el.get("Id") for el in tree.getroot().iter() if el.get("Id") is not None
    ]
    assert len(ids) == len(set(ids)), "Id collisions in output"


def test_build_first_track_has_compressor_with_yaml_params(
    fake_skeleton, output_path
):
    # tracks.yaml drums_raw: threshold_db: -18, ratio: 4
    build(skeleton_path=fake_skeleton, output_path=output_path)
    tree = _read_als(output_path)
    root = tree.getroot()
    first_track = root.find(".//LiveSet/Tracks/AudioTrack")
    comp = first_track.find(".//Compressor")
    assert comp is not None
    assert comp.find("./Threshold/Manual").get("Value") == "-18"
    assert comp.find("./Ratio/Manual").get("Value") == "4"


def test_build_missing_skeleton_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        build(skeleton_path=tmp_path / "nope.als", output_path=tmp_path / "out.als")


def test_beat_chop_track_is_midi_with_simpler(fake_skeleton, output_path):
    build(skeleton_path=fake_skeleton, output_path=output_path)
    tree = _read_als(output_path)
    root = tree.getroot()
    midi_tracks = root.findall(".//LiveSet/Tracks/MidiTrack")
    assert len(midi_tracks) == 1  # only beat_chop_simpler is MIDI
    simpler = midi_tracks[0].find(".//OriginalSimpler")
    assert simpler is not None
    assert simpler.find("./Playback/PlayMode/Manual").get("Value") == "2"  # slice
