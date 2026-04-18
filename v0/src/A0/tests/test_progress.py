"""Tests for the progress.ndjson / artifacts / done.flag writers."""
from __future__ import annotations

import json

from v0.src.A0 import progress


def test_emit_appends_ndjson_line(tmp_path, monkeypatch):
    monkeypatch.setattr(progress.config, "A0_STATE_DIR", tmp_path)
    monkeypatch.setattr(progress.config, "STATE_PROGRESS_NDJSON",
                        tmp_path / "progress.ndjson")
    progress.emit("phase1", 25.0, "hello", model="ast")
    progress.emit("phase2", 75.0, "world", model="clap")
    lines = (tmp_path / "progress.ndjson").read_text().splitlines()
    assert len(lines) == 2
    rec1 = json.loads(lines[0])
    assert rec1["phase"] == "phase1"
    assert rec1["pct"] == 25.0
    assert rec1["message"] == "hello"
    assert rec1["model"] == "ast"
    rec2 = json.loads(lines[1])
    assert rec2["phase"] == "phase2"


def test_write_done_flag_json(tmp_path, monkeypatch):
    monkeypatch.setattr(progress.config, "A0_STATE_DIR", tmp_path)
    monkeypatch.setattr(progress.config, "STATE_DONE_FLAG",
                        tmp_path / "done.flag")
    progress.write_done_flag("feat/v0-A0-onnx",
                             ["v0/build/models/manifest.json"],
                             notes="test run")
    doc = json.loads((tmp_path / "done.flag").read_text())
    assert doc["branch"] == "feat/v0-A0-onnx"
    assert "completed_at" in doc
    assert doc["artifacts"] == ["v0/build/models/manifest.json"]
    assert doc["notes"] == "test run"


def test_write_blocker(tmp_path, monkeypatch):
    monkeypatch.setattr(progress.config, "A0_STATE_DIR", tmp_path)
    monkeypatch.setattr(progress.config, "STATE_BLOCKER_MD",
                        tmp_path / "blocker.md")
    progress.write_blocker("stft-failure", "body text here")
    contents = (tmp_path / "blocker.md").read_text()
    assert "A0 blocker — stft-failure" in contents
    assert "body text here" in contents


def test_timer_records_to_perf(tmp_path, monkeypatch):
    perf = tmp_path / "perf.json"
    with progress.Timer("stage-A", perf_path=perf, fixture="drum") as t:
        pass
    with progress.Timer("stage-B", perf_path=perf) as t:
        pass
    doc = json.loads(perf.read_text())
    stages = doc["stages"]
    assert len(stages) == 2
    assert stages[0]["stage"] == "stage-A"
    assert stages[0]["fixture"] == "drum"
    assert stages[1]["stage"] == "stage-B"
    assert all(s["seconds"] >= 0 for s in stages)
