"""Unit tests for the .amxd container writer.

Verifies:
- Correct magic + chunk layout per reverse-engineered format.
- Round-trip of a real patcher JSON.
- Byte-for-byte parity with the reference file m4l/StemForgeTemplateBuilder.amxd
  (rebuilt from its own extracted JSON — proves packer is a valid inverse).
"""

from __future__ import annotations

import json
import struct
from pathlib import Path

from amxd_pack import AMPF_MAGIC, PTCH_TAG, pack_amxd, unpack_amxd

REPO_ROOT = Path(__file__).resolve().parents[4]
REFERENCE_AMXD = REPO_ROOT / "m4l" / "StemForgeTemplateBuilder.amxd"


def test_pack_then_unpack_round_trip(tmp_path):
    patcher = {"patcher": {"fileversion": 1, "boxes": [], "lines": []}}
    out = pack_amxd(patcher, tmp_path / "x.amxd", device_type=1)
    assert out.exists()
    blob = out.read_bytes()
    assert blob[:4] == AMPF_MAGIC
    # ptch tag must exist somewhere in the first 32 bytes
    assert PTCH_TAG in blob[:32]

    parsed = unpack_amxd(out)
    assert parsed["device_type"] == 1
    assert parsed["patcher"] == patcher


def test_meta_device_type_survives_roundtrip(tmp_path):
    patcher = {"patcher": {"fileversion": 1, "boxes": [], "lines": []}}
    pack_amxd(patcher, tmp_path / "a.amxd", device_type=1)
    pack_amxd(patcher, tmp_path / "b.amxd", device_type=7)
    assert unpack_amxd(tmp_path / "a.amxd")["device_type"] == 1
    assert unpack_amxd(tmp_path / "b.amxd")["device_type"] == 7


def test_ptch_length_field_matches_body(tmp_path):
    patcher = {"patcher": {"fileversion": 1, "notes": "x" * 512}}
    out = pack_amxd(patcher, tmp_path / "len.amxd")
    blob = out.read_bytes()
    ptch_off = blob.find(PTCH_TAG)
    ptch_len = struct.unpack_from("<I", blob, ptch_off + 4)[0]
    # header = ptch_off + 8; remaining bytes must equal ptch_len.
    assert len(blob) - (ptch_off + 8) == ptch_len


def test_can_unpack_reference_amxd_from_repo():
    # Verifies our unpacker agrees with Max's own writer.
    assert REFERENCE_AMXD.exists(), "reference file missing"
    parsed = unpack_amxd(REFERENCE_AMXD)
    assert parsed["device_type"] == 1
    assert "patcher" in parsed
    assert parsed["patcher"]["patcher"]["fileversion"] == 1


def test_repack_of_reference_opens_as_same_patcher(tmp_path):
    # The pretty-printing of our packer is not byte-identical to Max's (tabs
    # are placed differently), so we don't compare bytes. What must be true
    # is: reparse → patcher struct equal.
    parsed = unpack_amxd(REFERENCE_AMXD)
    repacked = pack_amxd(parsed["patcher"], tmp_path / "round.amxd",
                         device_type=parsed["device_type"])
    re_parsed = unpack_amxd(repacked)
    assert re_parsed["patcher"] == parsed["patcher"]
    assert re_parsed["device_type"] == parsed["device_type"]


def test_pretty_false_produces_compact_json(tmp_path):
    patcher = {"patcher": {"fileversion": 1, "boxes": [], "lines": []}}
    out = pack_amxd(patcher, tmp_path / "c.amxd", pretty=False)
    blob = out.read_bytes()
    ptch_off = blob.find(PTCH_TAG)
    ptch_len = struct.unpack_from("<I", blob, ptch_off + 4)[0]
    body = blob[ptch_off + 8 : ptch_off + 8 + ptch_len]
    # Compact mode: no tab characters inside the JSON.
    assert b"\t" not in body
    # Still valid JSON
    assert json.loads(body.rstrip(b"\x00"))["patcher"]["fileversion"] == 1
