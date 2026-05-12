"""Pydantic round-trips and negative-control cases for configurator schemas."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from stemforge.configurator.schemas import (
    AssignPadRequest,
    ClearPadRequest,
    CommitRequest,
    ExportRequest,
    IntentResponse,
    LoadManifestRequest,
    RecomputeRequest,
    SetGroupFormatRequest,
)
from stemforge.scene_model import Project


def test_load_manifest_request_roundtrip():
    req = LoadManifestRequest(manifest_path="/tmp/x.json", bpm=100.0)
    again = LoadManifestRequest.model_validate_json(req.model_dump_json())
    assert again.manifest_path == req.manifest_path
    assert again.bpm == 100.0


def test_load_manifest_request_rejects_extra_fields():
    with pytest.raises(ValidationError):
        LoadManifestRequest.model_validate({"manifest_path": "/tmp/x.json", "bogus": 1})


def test_commit_request_accepts_either_payload_source():
    a = CommitRequest(session_tracks={"A": []})
    b = CommitRequest(manifest_path="/tmp/x.json")
    c = CommitRequest()  # both None — handler enforces, not schema
    assert a.session_tracks == {"A": []}
    assert b.manifest_path is not None
    assert c.session_tracks is None and c.manifest_path is None


def test_assign_pad_request_validates_pad_range():
    AssignPadRequest(group="A", pad=1, clip_id="abc")
    AssignPadRequest(group="D", pad=12, clip_id="abc")
    with pytest.raises(ValidationError):
        AssignPadRequest(group="A", pad=0, clip_id="abc")
    with pytest.raises(ValidationError):
        AssignPadRequest(group="A", pad=13, clip_id="abc")
    with pytest.raises(ValidationError):
        AssignPadRequest(group="E", pad=1, clip_id="abc")  # type: ignore[arg-type]


def test_clear_pad_request_roundtrip():
    req = ClearPadRequest(group="B", pad=4)
    assert ClearPadRequest.model_validate_json(req.model_dump_json()) == req


def test_set_group_format_request_constraints():
    SetGroupFormatRequest(group="A", format="vocal")
    SetGroupFormatRequest(group="D", format="preserve_source")
    with pytest.raises(ValidationError):
        SetGroupFormatRequest(group="A", format="bogus")  # type: ignore[arg-type]


def test_recompute_request_rejects_unknown_fields():
    RecomputeRequest()
    with pytest.raises(ValidationError):
        RecomputeRequest.model_validate({"scope": "all"})


def test_export_request_validates_target_and_slot():
    req = ExportRequest(target="ep133", out_path="/tmp/out.ppak", project_slot=8)
    assert req.project_slot == 8
    with pytest.raises(ValidationError):
        ExportRequest(target="koala", out_path="/tmp/x")  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        ExportRequest(target="ep133", out_path="/tmp/x", project_slot=10)


def test_intent_response_default_shape():
    r = IntentResponse(ok=True, state=Project())
    assert r.warnings == [] and r.errors == []
    j = r.model_dump_json()
    assert '"ok":true' in j


def test_intent_response_error_path():
    r = IntentResponse(ok=False, state=None, errors=["bad"])
    assert r.ok is False
    assert r.state is None
    assert r.errors == ["bad"]
