"""build-deck CLI smoke + deck-plan loader tests."""

from __future__ import annotations

import json
import wave
from pathlib import Path

import pytest
from click.testing import CliRunner

from stemforge.cli import cli
from stemforge.exporters.ep133.deck_plan import (
    load_deck_plan,
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


def test_load_deck_plan_json(tmp_path: Path) -> None:
    plan = {"project": "x", "groups": {}}
    p = tmp_path / "deck.json"
    p.write_text(json.dumps(plan))
    assert load_deck_plan(p) == plan


def test_project_from_deck_plan_raw_path(tmp_path: Path) -> None:
    wav = tmp_path / "verse.wav"
    _write_wav(wav)
    plan = {
        "project": "test_deck",
        "project_slot": 8,
        "project_bpm": 92,
        "groups": {
            "A": {
                "format_profile": "vocal",
                "pads": [{"pad": 1, "path": str(wav), "source_bpm": 88}],
            }
        },
    }
    project, idx = project_from_deck_plan(plan, plan_dir=tmp_path)
    assert project.name == "test_deck"
    assert len(project.songs) == 1
    assert project.songs[0].bpm == 92
    assert project.songs[0].groups[0].group_id == "A"
    assert project.songs[0].groups[0].format_profile == "vocal"
    pad = project.songs[0].groups[0].pads[0]
    assert pad.pad_id == "1"
    assert pad.clip is not None
    assert pad.clip.path == str(wav.resolve())
    assert pad.clip.source_bpm == 88.0


def test_project_from_deck_plan_manifest_path(tmp_path: Path) -> None:
    wav = tmp_path / "song1" / "v.wav"
    _write_wav(wav)
    manifest = tmp_path / "song1" / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "session_tracks": {
                    "A": [
                        {
                            "slot": 0,
                            "file": str(wav),
                            "name": "verse_1",
                            "clip_length_sec": 0.2,
                            "bpm": 92.0,
                        }
                    ]
                },
                "bpm": 92.0,
            }
        )
    )
    plan = {
        "project": "manifest_test",
        "project_slot": 1,
        "groups": {
            "A": {
                "format_profile": "vocal",
                "pads": [{"pad": 1, "source": str(manifest), "clip": "name:verse_1"}],
            }
        },
    }
    project, idx = project_from_deck_plan(plan, plan_dir=tmp_path)
    assert manifest.resolve() in idx.manifests()
    pad = project.songs[0].groups[0].pads[0]
    assert pad.clip is not None
    assert pad.clip.path == str(wav.resolve())
    assert pad.clip.name == "verse_1"
    assert pad.clip.source_bpm == 92.0


def test_project_from_deck_plan_relative_paths(tmp_path: Path) -> None:
    wav = tmp_path / "verse.wav"
    _write_wav(wav)
    plan = {
        "groups": {
            "A": {
                "pads": [{"pad": 1, "path": "verse.wav"}],
            }
        }
    }
    project, _ = project_from_deck_plan(plan, plan_dir=tmp_path)
    pad = project.songs[0].groups[0].pads[0]
    assert pad.clip.path == str(wav.resolve())


def test_project_from_deck_plan_requires_path_or_source(tmp_path: Path) -> None:
    plan = {"groups": {"A": {"pads": [{"pad": 1}]}}}
    with pytest.raises(ValueError, match="path:.*source:"):
        project_from_deck_plan(plan, plan_dir=tmp_path)


def test_build_deck_cli_smoke(tmp_path: Path) -> None:
    """Minimal end-to-end: deck plan → .ppak written without exceptions."""
    wav = tmp_path / "verse.wav"
    _write_wav(wav, duration_sec=0.2)
    deck = {
        "project": "smoke",
        "project_slot": 1,
        "project_bpm": 92,
        "groups": {
            "A": {
                "format_profile": "vocal",
                "pads": [{"pad": 1, "path": str(wav), "source_bpm": 92}],
            }
        },
    }
    deck_path = tmp_path / "deck.json"
    deck_path.write_text(json.dumps(deck))

    out_path = tmp_path / "out.ppak"
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "build-deck",
            str(deck_path),
            "--out",
            str(out_path),
            "--no-write-spec",
        ],
    )
    assert result.exit_code == 0, result.output
    assert out_path.is_file()
    assert out_path.stat().st_size > 0


def test_build_deck_cli_writes_spec_by_default(tmp_path: Path) -> None:
    wav = tmp_path / "verse.wav"
    _write_wav(wav)
    deck = {
        "project": "spec_test",
        "project_slot": 1,
        "groups": {"A": {"pads": [{"pad": 1, "path": str(wav)}]}},
    }
    deck_path = tmp_path / "deck.json"
    deck_path.write_text(json.dumps(deck))

    out_path = tmp_path / "out.ppak"
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["build-deck", str(deck_path), "--out", str(out_path)],
    )
    assert result.exit_code == 0, result.output
    spec_path = out_path.with_suffix(".projectspec.json")
    assert spec_path.is_file()
    spec_data = json.loads(spec_path.read_text())
    assert spec_data["name"] == "spec_test"


def test_build_deck_cli_reports_memory_usage(tmp_path: Path) -> None:
    wav = tmp_path / "verse.wav"
    _write_wav(wav)
    deck = {
        "project": "mem_test",
        "project_slot": 1,
        "groups": {"A": {"format_profile": "vocal", "pads": [{"pad": 1, "path": str(wav)}]}},
    }
    deck_path = tmp_path / "deck.json"
    deck_path.write_text(json.dumps(deck))
    out_path = tmp_path / "out.ppak"

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["build-deck", str(deck_path), "--out", str(out_path), "--no-write-spec"],
    )
    assert result.exit_code == 0, result.output
    assert "MB" in result.output
    assert "headroom" in result.output
