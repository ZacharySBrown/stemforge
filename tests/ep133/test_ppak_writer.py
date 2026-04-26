"""End-to-end tests for the ``.ppak`` writer.

Each test builds a minimal :class:`PpakSpec`, writes it via
:func:`build_ppak` against a synthesized template, then re-parses the
resulting bytes (ZIP → TAR → file blobs) and asserts both layout and
content. No real device capture required.
"""

from __future__ import annotations

import io
import json
import struct
import tarfile
import zipfile
from pathlib import Path

import pytest

from stemforge.exporters.ep133.ppak_writer import (
    GROUPS,
    build_ppak,
    build_synthetic_template_ppak,
)
from stemforge.exporters.ep133.song_format import (
    PAD_RECORD_SIZE,
    SETTINGS_SIZE,
    Event,
    PadSpec,
    Pattern,
    PpakSpec,
    SceneSpec,
)


# ----- Helpers ---------------------------------------------------------------


def _open_ppak(data: bytes) -> tuple[dict, dict[str, bytes]]:
    """Return (meta_json, {tar_member_name: bytes})."""
    meta = None
    tar_members: dict[str, bytes] = {}
    with zipfile.ZipFile(io.BytesIO(data), "r") as zf:
        # Every entry must start with "/" — that's the device requirement.
        names = zf.namelist()
        for name in names:
            assert name.startswith("/"), f"ZIP entry without leading slash: {name!r}"
            if name == "/meta.json":
                meta = json.loads(zf.read(name).decode("utf-8"))
            elif name.startswith("/projects/") and name.endswith(".tar"):
                tar_bytes = zf.read(name)
                with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r:") as tf:
                    for m in tf.getmembers():
                        if not m.isfile():
                            continue
                        f = tf.extractfile(m)
                        if f is not None:
                            tar_members[m.name.lstrip("./").lstrip("/")] = f.read()
    if meta is None:
        raise AssertionError("no /meta.json in .ppak")
    return meta, tar_members


def _silent_wav(path: Path, *, samples: int = 1024) -> Path:
    """Write a tiny mono 44.1kHz 16-bit silent WAV. No external deps."""
    sr = 44100
    bits = 16
    channels = 1
    byte_rate = sr * channels * bits // 8
    block_align = channels * bits // 8
    data_bytes = bytes(samples * channels * (bits // 8))
    riff = b"RIFF"
    fmt = (
        b"fmt \x10\x00\x00\x00"
        + struct.pack("<HHIIHH", 1, channels, sr, byte_rate, block_align, bits)
    )
    data_chunk = b"data" + struct.pack("<I", len(data_bytes)) + data_bytes
    payload = b"WAVE" + fmt + data_chunk
    riff_size = len(payload)
    path.write_bytes(riff + struct.pack("<I", riff_size) + payload)
    return path


@pytest.fixture()
def template_ppak(tmp_path: Path) -> Path:
    """Synthesize a minimal reference template at ``tmp_path/template.ppak``."""
    return build_synthetic_template_ppak(tmp_path / "template.ppak", project_slot=1)


@pytest.fixture()
def silent_wav(tmp_path: Path) -> Path:
    return _silent_wav(tmp_path / "silent.wav")


# ----- Synthetic template tests ---------------------------------------------


def test_synthetic_template_has_expected_shape(template_ppak: Path):
    data = template_ppak.read_bytes()
    meta, members = _open_ppak(data)

    assert meta["pak_version"] == 1
    assert meta["pak_type"] == "user"
    assert meta["device_name"] == "EP-133"
    assert "generated_at" in meta

    # 48 pads + settings = 49 members
    assert "settings" in members
    assert len(members["settings"]) == SETTINGS_SIZE
    assert members["settings"] == bytes(SETTINGS_SIZE)
    for group in GROUPS:
        for pad in range(1, 13):
            key = f"pads/{group}/p{pad:02d}"
            assert key in members, f"missing pad: {key}"
            assert len(members[key]) == PAD_RECORD_SIZE
            assert members[key] == bytes(PAD_RECORD_SIZE)


# ----- End-to-end build tests ------------------------------------------------


def _minimal_spec(silent_wav_path: Path, project_slot: int = 2) -> PpakSpec:
    """1 scene, 1 pattern (group A), 1 pad (a-pad-3), 1 sample (slot 100)."""
    return PpakSpec(
        project_slot=project_slot,
        bpm=128.0,
        time_sig=(4, 4),
        patterns=[
            Pattern(
                group="a",
                index=1,
                bars=2,
                events=[
                    Event(
                        position_ticks=0,
                        pad=3,
                        note=60,
                        velocity=127,
                        duration_ticks=2 * 384,
                    )
                ],
            )
        ],
        scenes=[SceneSpec(a=1, b=0, c=0, d=0)],
        pads=[
            PadSpec(
                group="a",
                pad=3,
                sample_slot=100,
                play_mode="oneshot",
                time_stretch_bars=2,
            )
        ],
        sounds={100: silent_wav_path},
    )


def test_build_ppak_minimal_returns_bytes(template_ppak: Path, silent_wav: Path, tmp_path: Path):
    spec = _minimal_spec(silent_wav)
    data = build_ppak(spec, template_ppak, out_path=tmp_path / "out.ppak")
    assert isinstance(data, bytes)
    assert len(data) > 0
    assert (tmp_path / "out.ppak").read_bytes() == data


def test_build_ppak_zip_entries_have_leading_slash(
    template_ppak: Path, silent_wav: Path
):
    data = build_ppak(_minimal_spec(silent_wav), template_ppak)
    with zipfile.ZipFile(io.BytesIO(data), "r") as zf:
        for name in zf.namelist():
            assert name.startswith("/"), f"missing leading slash on entry {name!r}"


def test_build_ppak_inner_tar_is_uncompressed_posix(
    template_ppak: Path, silent_wav: Path
):
    data = build_ppak(_minimal_spec(silent_wav), template_ppak)
    with zipfile.ZipFile(io.BytesIO(data), "r") as zf:
        tar_bytes = zf.read("/projects/P02.tar")
    # Open the TAR — no compression suffix, must succeed with mode "r:" (no compression)
    with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r:") as tf:
        members = tf.getmembers()
    # Every member is a regular file in our writer.
    assert all(m.isfile() for m in members)


def test_build_ppak_includes_all_48_pad_files(template_ppak: Path, silent_wav: Path):
    data = build_ppak(_minimal_spec(silent_wav), template_ppak)
    _, members = _open_ppak(data)
    for group in GROUPS:
        for pad in range(1, 13):
            key = f"pads/{group}/p{pad:02d}"
            assert key in members
            assert len(members[key]) == PAD_RECORD_SIZE


def test_build_ppak_authored_pad_has_sample_slot(template_ppak: Path, silent_wav: Path):
    data = build_ppak(_minimal_spec(silent_wav), template_ppak)
    _, members = _open_ppak(data)
    pad_blob = members["pads/a/p03"]
    sample_slot = struct.unpack_from("<H", pad_blob, 1)[0]
    assert sample_slot == 100


def test_build_ppak_unassigned_pads_remain_zero(template_ppak: Path, silent_wav: Path):
    """Pads not in spec.pads keep the template (zero) bytes."""
    data = build_ppak(_minimal_spec(silent_wav), template_ppak)
    _, members = _open_ppak(data)
    # pads/a/p01 is not in our spec → still zero from synthesized template.
    assert members["pads/a/p01"] == bytes(PAD_RECORD_SIZE)


def test_build_ppak_pattern_layout(template_ppak: Path, silent_wav: Path):
    data = build_ppak(_minimal_spec(silent_wav), template_ppak)
    _, members = _open_ppak(data)
    pattern = members["patterns/a01"]
    # Header: [0x00, bars=2, count=1, 0x00]
    assert pattern[0] == 0x00
    assert pattern[1] == 2  # bars (NOT constant 0x01!)
    assert pattern[2] == 1
    assert pattern[3] == 0x00
    # Event: [pos=0(LE), (pad-1)*8=16, note=60, vel=127, dur=768(LE), 0x00]
    # — events use 0-indexed pad encoding; pad 3 → byte 0x10.
    assert pattern[4] == 0x00 and pattern[5] == 0x00
    assert pattern[6] == (3 - 1) * 8  # 0x10
    assert pattern[7] == 60
    assert pattern[8] == 127
    duration = struct.unpack_from("<H", pattern, 9)[0]
    assert duration == 768
    assert pattern[11] == 0x00


def test_build_ppak_scenes_layout(template_ppak: Path, silent_wav: Path):
    data = build_ppak(_minimal_spec(silent_wav), template_ppak)
    _, members = _open_ppak(data)
    scenes = members["scenes"]
    # Header bytes 5,6 = numerator, denominator.
    assert scenes[5] == 4
    assert scenes[6] == 4
    # First chunk at offset 7: [a=1, b=0, c=0, d=0, num=4, den=4]
    assert scenes[7:13] == bytes([1, 0, 0, 0, 4, 4])


def test_build_ppak_settings_bpm_patched(template_ppak: Path, silent_wav: Path):
    data = build_ppak(_minimal_spec(silent_wav), template_ppak)
    _, members = _open_ppak(data)
    settings = members["settings"]
    assert len(settings) == SETTINGS_SIZE
    bpm = struct.unpack_from("<f", settings, 4)[0]
    assert bpm == pytest.approx(128.0)


def test_build_ppak_bundles_sounds_at_expected_path(
    template_ppak: Path, silent_wav: Path
):
    data = build_ppak(_minimal_spec(silent_wav), template_ppak)
    with zipfile.ZipFile(io.BytesIO(data), "r") as zf:
        names = zf.namelist()
    # Device requires "/sounds/{slot} {slot}_{name}.wav" — see writer comment.
    assert any(n.startswith("/sounds/100 100_") and n.endswith(".wav") for n in names), names


def test_build_ppak_project_tar_path_matches_slot(
    template_ppak: Path, silent_wav: Path
):
    spec = _minimal_spec(silent_wav, project_slot=7)
    data = build_ppak(spec, template_ppak)
    with zipfile.ZipFile(io.BytesIO(data), "r") as zf:
        names = zf.namelist()
    assert "/projects/P07.tar" in names


def test_build_ppak_meta_overrides(template_ppak: Path, silent_wav: Path):
    data = build_ppak(
        _minimal_spec(silent_wav),
        template_ppak,
        author="alice",
        device_sku="TE032AS999",
    )
    meta, _ = _open_ppak(data)
    assert meta["author"] == "alice"
    assert meta["device_sku"] == "TE032AS999"
    assert meta["base_sku"] == "TE032AS999"


def test_build_ppak_rejects_missing_template(tmp_path: Path, silent_wav: Path):
    with pytest.raises(FileNotFoundError):
        build_ppak(_minimal_spec(silent_wav), tmp_path / "nonexistent.ppak")


def test_build_ppak_rejects_missing_sound(template_ppak: Path, tmp_path: Path):
    spec = PpakSpec(
        project_slot=1,
        bpm=120.0,
        time_sig=(4, 4),
        patterns=[],
        scenes=[],
        pads=[],
        sounds={100: tmp_path / "no-such.wav"},
    )
    with pytest.raises(FileNotFoundError, match="sample slot 100"):
        build_ppak(spec, template_ppak)


def test_build_ppak_rejects_invalid_project_slot(
    template_ppak: Path, silent_wav: Path
):
    spec = _minimal_spec(silent_wav)
    spec.project_slot = 0
    with pytest.raises(ValueError, match="project_slot"):
        build_ppak(spec, template_ppak)
    spec.project_slot = 10
    with pytest.raises(ValueError, match="project_slot"):
        build_ppak(spec, template_ppak)


def test_build_ppak_rejects_duplicate_pattern(template_ppak: Path, silent_wav: Path):
    spec = _minimal_spec(silent_wav)
    spec.patterns.append(Pattern(group="a", index=1, bars=1, events=[]))
    with pytest.raises(ValueError, match="duplicate pattern"):
        build_ppak(spec, template_ppak)


def test_build_ppak_rejects_duplicate_pad(template_ppak: Path, silent_wav: Path):
    spec = _minimal_spec(silent_wav)
    spec.pads.append(
        PadSpec(group="a", pad=3, sample_slot=200, play_mode="key", time_stretch_bars=1)
    )
    with pytest.raises(ValueError, match="duplicate pad"):
        build_ppak(spec, template_ppak)


def test_build_ppak_rejects_scene_pointing_at_undefined_pattern(
    template_ppak: Path, silent_wav: Path
):
    spec = _minimal_spec(silent_wav)
    spec.scenes = [SceneSpec(a=99, b=0, c=0, d=0)]
    with pytest.raises(ValueError, match="undefined pattern"):
        build_ppak(spec, template_ppak)


def test_build_ppak_round_trip_through_synthetic_template(tmp_path: Path):
    """Full loop: synth template → build_ppak → reparse + assert exact layout."""
    template = build_synthetic_template_ppak(tmp_path / "tpl.ppak", project_slot=3)
    silent = _silent_wav(tmp_path / "s.wav")

    # Two scenes, two patterns (different bars), two pads, two sounds.
    spec = PpakSpec(
        project_slot=3,
        bpm=140.5,
        time_sig=(4, 4),
        patterns=[
            Pattern(
                group="a", index=1, bars=1,
                events=[Event(0, 1, 60, 100, 384)]
            ),
            Pattern(
                group="b", index=1, bars=4,
                events=[Event(0, 5, 60, 90, 4 * 384)]
            ),
        ],
        scenes=[
            SceneSpec(a=1, b=1, c=0, d=0),
            SceneSpec(a=1, b=0, c=0, d=0),
        ],
        pads=[
            PadSpec("a", 1, sample_slot=101, play_mode="oneshot", time_stretch_bars=1),
            PadSpec("b", 5, sample_slot=102, play_mode="key", time_stretch_bars=4),
        ],
        sounds={101: silent, 102: silent},
    )

    data = build_ppak(spec, template)
    _, members = _open_ppak(data)

    # Pattern A — events use 0-indexed pad encoding: pad 1 → byte 0.
    pa = members["patterns/a01"]
    assert pa[1] == 1  # bars
    assert pa[2] == 1  # event count
    assert pa[6] == (1 - 1) * 8  # 0
    # Pattern B (bars=4) — pad 5 → byte 0x20.
    pb = members["patterns/b01"]
    assert pb[1] == 4
    assert pb[2] == 1
    assert pb[6] == (5 - 1) * 8  # 0x20

    # Scenes — 2 chunks
    sc = members["scenes"]
    assert sc[7:13] == bytes([1, 1, 0, 0, 4, 4])
    assert sc[13:19] == bytes([1, 0, 0, 0, 4, 4])

    # Settings BPM
    assert struct.unpack_from("<f", members["settings"], 4)[0] == pytest.approx(140.5)

    # Pad A1: sample_slot=101, play_mode=oneshot(0), bars=1(raw 0)
    pad_a1 = members["pads/a/p01"]
    assert struct.unpack_from("<H", pad_a1, 1)[0] == 101
    assert pad_a1[23] == 0
    assert pad_a1[25] == 0
    # Pad B5: sample_slot=102, play_mode=key(1), bars=4(raw 2)
    pad_b5 = members["pads/b/p05"]
    assert struct.unpack_from("<H", pad_b5, 1)[0] == 102
    assert pad_b5[23] == 1
    assert pad_b5[25] == 2

    # Sounds bundled — device requires "/sounds/{slot} {slot}_{name}.wav"
    # naming (literal space + descriptive suffix). Verified against a real
    # device backup; entries without the descriptive suffix are silently
    # ignored by the device → "restore complete with issues" + missing audio.
    with zipfile.ZipFile(io.BytesIO(data), "r") as zf:
        names = zf.namelist()
    assert any(n.startswith("/sounds/101 101_") and n.endswith(".wav") for n in names), names
    assert any(n.startswith("/sounds/102 102_") and n.endswith(".wav") for n in names), names
    assert "/projects/P03.tar" in names
