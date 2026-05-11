"""deck-from-manifest auto-generator tests."""

from __future__ import annotations

import json
import wave
from pathlib import Path

import yaml
from click.testing import CliRunner

from stemforge.cli import cli
from stemforge.exporters.ep133.deck_autogen import (
    DEFAULT_FORMAT_PROFILE,
    deck_from_manifest,
    to_yaml_string,
)
from stemforge.exporters.ep133.deck_plan import (
    project_from_deck_plan,
)


def _write_wav(path: Path, *, duration_sec: float = 0.2) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    n = int(duration_sec * 22050)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(22050)
        wf.writeframes(b"\x00\x00" * n)


def _build_manifest(
    tmp_path: Path,
    *,
    counts_per_group: dict[str, int],
    bpm: float = 92.0,
) -> Path:
    """Write a curated manifest with N entries per group + WAVs on disk."""
    session_tracks: dict[str, list[dict]] = {}
    for group, n in counts_per_group.items():
        entries = []
        for slot in range(n):
            wav = tmp_path / group.lower() / f"clip_{slot:02d}.wav"
            _write_wav(wav)
            entries.append(
                {
                    "slot": slot,
                    "file": str(wav),
                    "name": f"{group.lower()}_clip_{slot:02d}",
                    "clip_length_sec": 0.2,
                    "bpm": bpm,
                }
            )
        session_tracks[group] = entries
    manifest_dir = tmp_path / "curated"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = manifest_dir / "manifest.json"
    manifest_path.write_text(json.dumps({"session_tracks": session_tracks, "bpm": bpm}))
    return manifest_path


def test_default_format_profiles() -> None:
    assert DEFAULT_FORMAT_PROFILE == {
        "A": "vocal",
        "B": "vocal",
        "C": "drum",
        "D": "texture",
    }


def test_drum_profile_defaults_locked() -> None:
    """Drum profile must default to play_mode=key with the matching
    envelope.release=15 pairing. Locked in 2026-05-09 after hardware
    validation; reverting either field re-introduces the silent-fallback
    bug. See feedback_drum_profile_defaults.md.
    """
    from stemforge.exporters.ep133.deck_autogen import DEFAULT_PLAY_MODE
    from stemforge.exporters.ep133.song_format import PLAY_MODE_RELEASE_PAIR
    from stemforge.exporters.ep133.wav_format import _PLAYMODE_RELEASE_PAIR

    # Drum-profile pads default to key (hold-to-play).
    assert DEFAULT_PLAY_MODE["drum"] == "key", (
        "drum profile must default to key play_mode — see "
        "feedback_drum_profile_defaults.md before changing"
    )

    # Pad-record byte 20 ↔ byte 23 pairing.
    assert PLAY_MODE_RELEASE_PAIR["key"] == 0x0F
    assert PLAY_MODE_RELEASE_PAIR["oneshot"] == 0xFF

    # WAV TNGE metadata must use the same pairing or the device's coupled
    # fields drift between slot library and pad record.
    assert _PLAYMODE_RELEASE_PAIR["key"] == 15
    assert _PLAYMODE_RELEASE_PAIR["oneshot"] == 255


def test_simple_4_groups_under_cap(tmp_path: Path) -> None:
    manifest_path = _build_manifest(
        tmp_path,
        counts_per_group={"A": 5, "B": 3, "C": 4, "D": 2},
    )
    manifest = json.loads(manifest_path.read_text())
    plan = deck_from_manifest(
        manifest,
        manifest_path,
        project_name="test",
        project_slot=8,
    )
    assert plan["project"] == "test"
    assert plan["project_slot"] == 8
    assert plan["project_bpm"] == 92.0
    for g, count in {"A": 5, "B": 3, "C": 4, "D": 2}.items():
        assert len(plan["groups"][g]["pads"]) == count
        assert plan["groups"][g]["format_profile"] == DEFAULT_FORMAT_PROFILE[g]


def test_14_vocal_loops_spill_a_to_b(tmp_path: Path) -> None:
    """The user's actual case: 14 vocal loops on track A in Live."""
    manifest_path = _build_manifest(tmp_path, counts_per_group={"A": 14})
    manifest = json.loads(manifest_path.read_text())
    plan = deck_from_manifest(manifest, manifest_path, project_name="hip_hop")
    assert len(plan["groups"]["A"]["pads"]) == 12
    assert len(plan["groups"]["B"]["pads"]) == 2
    # Spilled vocals should still resolve through their original group A
    # entries — the deck plan's `group:` field carries that.
    spilled = plan["groups"]["B"]["pads"]
    for row in spilled:
        assert row["group"] == "A"
        assert row["clip"].startswith("slot:")
    # And the format profile should still be vocal on B (matches default).
    assert plan["groups"]["B"]["format_profile"] == "vocal"


def test_full_house_48_clips_no_spill(tmp_path: Path) -> None:
    """12 clips per group → no spillover, all 48 mapped."""
    manifest_path = _build_manifest(tmp_path, counts_per_group={"A": 12, "B": 12, "C": 12, "D": 12})
    manifest = json.loads(manifest_path.read_text())
    plan = deck_from_manifest(manifest, manifest_path, project_name="full")
    for g in ("A", "B", "C", "D"):
        assert len(plan["groups"][g]["pads"]) == 12
    # No row should have a non-self origin_group when the layout fits.
    for g in ("A", "B", "C", "D"):
        for row in plan["groups"][g]["pads"]:
            assert row["group"] == g


def test_overflow_past_d_drops(tmp_path: Path) -> None:
    """50 clips on A would spill to B/C/D; >48 drops the tail."""
    manifest_path = _build_manifest(tmp_path, counts_per_group={"A": 50})
    manifest = json.loads(manifest_path.read_text())
    plan = deck_from_manifest(manifest, manifest_path, project_name="overflow")
    total_pads = sum(len(plan["groups"].get(g, {}).get("pads", [])) for g in "ABCD")
    assert total_pads == 48  # all four groups full
    # The CLI surfaces the truncation; the model just caps at 48.


def test_empty_groups_omitted_from_output(tmp_path: Path) -> None:
    manifest_path = _build_manifest(tmp_path, counts_per_group={"A": 3})
    manifest = json.loads(manifest_path.read_text())
    plan = deck_from_manifest(manifest, manifest_path, project_name="sparse")
    assert "A" in plan["groups"]
    assert "B" not in plan["groups"]
    assert "C" not in plan["groups"]
    assert "D" not in plan["groups"]


def test_project_bpm_falls_back_when_manifest_silent(tmp_path: Path) -> None:
    manifest_path = tmp_path / "m.json"
    manifest_path.write_text(json.dumps({"session_tracks": {}}))
    plan = deck_from_manifest({"session_tracks": {}}, manifest_path, project_name="x")
    assert plan["project_bpm"] == 92.0


def test_yaml_serialization_round_trips(tmp_path: Path) -> None:
    manifest_path = _build_manifest(tmp_path, counts_per_group={"A": 2, "C": 3})
    manifest = json.loads(manifest_path.read_text())
    plan = deck_from_manifest(manifest, manifest_path, project_name="rt")
    text = to_yaml_string(plan)
    parsed = yaml.safe_load(text)
    assert parsed == plan


def test_autogen_plan_feeds_build_deck_resolver(tmp_path: Path) -> None:
    """End-to-end: auto-gen → project_from_deck_plan resolves the clips."""
    manifest_path = _build_manifest(tmp_path, counts_per_group={"A": 3, "C": 2})
    manifest = json.loads(manifest_path.read_text())
    plan = deck_from_manifest(manifest, manifest_path, project_name="end_to_end")
    # The plan dir is the manifest's parent dir for relative resolution.
    project, idx = project_from_deck_plan(plan, plan_dir=manifest_path.parent)
    assert len(project.songs) == 1
    groups = {g.group_id: g for g in project.songs[0].groups}
    assert len(groups["A"].pads) == 3
    assert len(groups["C"].pads) == 2
    # Format profiles propagate.
    assert groups["A"].format_profile == "vocal"
    assert groups["C"].format_profile == "drum"


def test_autogen_with_spillover_resolves_to_real_files(tmp_path: Path) -> None:
    """Spilled vocals from A → B should still resolve through manifest's
    session_tracks[A] entries via the `group:` field on the deck row."""
    manifest_path = _build_manifest(tmp_path, counts_per_group={"A": 14})
    manifest = json.loads(manifest_path.read_text())
    plan = deck_from_manifest(manifest, manifest_path, project_name="spill")
    project, _ = project_from_deck_plan(plan, plan_dir=manifest_path.parent)
    groups = {g.group_id: g for g in project.songs[0].groups}
    # All 14 vocals appear as pads — 12 on A, 2 on B.
    a_pads = groups["A"].pads
    b_pads = groups["B"].pads
    assert len(a_pads) == 12
    assert len(b_pads) == 2
    # Every pad should have a real path that exists.
    for pad in a_pads + b_pads:
        assert pad.clip is not None
        assert pad.clip.path is not None
        assert Path(pad.clip.path).is_file()


def test_cli_smoke(tmp_path: Path) -> None:
    manifest_path = _build_manifest(tmp_path, counts_per_group={"A": 3, "C": 2})
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "deck-from-manifest",
            str(manifest_path),
            "--project",
            "test_deck",
            "--project-slot",
            "8",
        ],
    )
    assert result.exit_code == 0, result.output
    out_path = manifest_path.parent / "deck.yaml"
    assert out_path.is_file()
    parsed = yaml.safe_load(out_path.read_text())
    assert parsed["project"] == "test_deck"
    assert parsed["project_slot"] == 8


def test_cli_reports_spill_for_14_vocals(tmp_path: Path) -> None:
    manifest_path = _build_manifest(tmp_path, counts_per_group={"A": 14})
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["deck-from-manifest", str(manifest_path), "--project", "spill_test"],
    )
    assert result.exit_code == 0, result.output
    # Console output should show the A=12, B=2 split.
    assert "Group A" in result.output
    assert "Group B" in result.output


def test_cli_json_format(tmp_path: Path) -> None:
    manifest_path = _build_manifest(tmp_path, counts_per_group={"A": 2})
    out_path = tmp_path / "deck.json"
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "deck-from-manifest",
            str(manifest_path),
            "--out",
            str(out_path),
            "--format",
            "json",
            "--project",
            "j",
        ],
    )
    assert result.exit_code == 0, result.output
    assert out_path.is_file()
    parsed = json.loads(out_path.read_text())
    assert parsed["project"] == "j"


def test_cli_overflow_past_48_warns(tmp_path: Path) -> None:
    manifest_path = _build_manifest(tmp_path, counts_per_group={"A": 60})
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["deck-from-manifest", str(manifest_path), "--project", "x"],
    )
    assert result.exit_code == 0, result.output
    assert "Dropped" in result.output


def test_default_project_name_from_curated_parent(tmp_path: Path) -> None:
    """`02_benjamins/curated/manifest.json` → project name `02_benjamins`."""
    manifest_dir = tmp_path / "02_benjamins" / "curated"
    manifest_dir.mkdir(parents=True)
    manifest_path = manifest_dir / "manifest.json"
    manifest_path.write_text(json.dumps({"session_tracks": {"A": []}, "bpm": 92}))
    runner = CliRunner()
    result = runner.invoke(cli, ["deck-from-manifest", str(manifest_path)])
    assert result.exit_code == 0, result.output
    out = yaml.safe_load((manifest_dir / "deck.yaml").read_text())
    assert out["project"] == "02_benjamins"
