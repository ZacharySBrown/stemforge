"""Integration tests for ``stemforge-native`` (Track A output).

These tests run the binary against a committed test fixture
(``v0/tests/fixtures/short_loop.wav``). They verify:

1. The binary exits clean and self-reports a version.
2. ``--json-events`` emits NDJSON that validates against
   ``v0/interfaces/ndjson.schema.json``.
3. Event-stream invariants hold (start/complete framing, BPM, stems).
4. ``stems.json`` manifest is produced and structurally matches the golden
   template captured from the A-validator reference run.
5. The binary is self-contained (runs with a minimal $PATH).

All tests skip cleanly if the binary is not resolvable — A gates G at runtime.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

TIMEOUT_SEC = 600  # Demucs on CPU takes ~20s per 10s of audio; leave headroom.


# ── helpers ────────────────────────────────────────────────────────────────

def _run_split(binary: Path, wav: Path, out: Path, json_events: bool = True) -> subprocess.CompletedProcess:
    # CLI flag is --out (see v0/src/A/cli/main.cpp).
    cmd = [str(binary), "split", str(wav), "--out", str(out)]
    if json_events:
        cmd.append("--json-events")
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=TIMEOUT_SEC,
    )


def _parse_ndjson(stdout: str) -> list[dict]:
    events = []
    for i, line in enumerate(stdout.splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError as e:
            pytest.fail(f"stdout line {i} is not valid JSON: {e!r}: {line!r}")
    return events


def _type_name(v) -> str:
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, int):
        return "int"
    if isinstance(v, float):
        return "float"
    if isinstance(v, str):
        return "string"
    if isinstance(v, list):
        return "array"
    if isinstance(v, dict):
        return "object"
    if v is None:
        return "null"
    return type(v).__name__


# ── tests ──────────────────────────────────────────────────────────────────

def test_binary_version(binary_path: Path) -> None:
    """Binary supports --version and exits 0."""
    proc = subprocess.run(
        [str(binary_path), "--version"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, f"stderr={proc.stderr!r}"
    assert (proc.stdout.strip() or proc.stderr.strip()), "no version output"


def test_binary_emits_valid_ndjson(
    binary_path: Path,
    test_wav: Path,
    ndjson_schema: dict,
    tmp_path: Path,
) -> None:
    """--json-events produces NDJSON validating against the schema."""
    jsonschema = pytest.importorskip("jsonschema")

    proc = _run_split(binary_path, test_wav, tmp_path)
    assert proc.returncode == 0, f"binary failed: stderr={proc.stderr!r}"

    events = _parse_ndjson(proc.stdout)
    assert events, "no NDJSON events emitted on stdout"

    validator = jsonschema.Draft7Validator(ndjson_schema)
    for i, evt in enumerate(events):
        errors = list(validator.iter_errors(evt))
        assert not errors, (
            f"event #{i} ({evt.get('event')!r}) failed schema: "
            f"{[e.message for e in errors]}"
        )


def test_binary_ndjson_invariants(
    binary_path: Path,
    test_wav: Path,
    tmp_path: Path,
) -> None:
    """First event is `started`, last is `complete`, bpm + stems present."""
    proc = _run_split(binary_path, test_wav, tmp_path)
    assert proc.returncode == 0, proc.stderr

    events = _parse_ndjson(proc.stdout)
    assert events, "no events"

    assert events[0].get("event") == "started", f"first event: {events[0]!r}"
    assert events[-1].get("event") == "complete", f"last event: {events[-1]!r}"

    bpm_events = [e for e in events if e.get("event") == "bpm"]
    assert bpm_events, "no bpm event emitted"

    # Every stem referenced in the 'complete' event should have had a 'stem'
    # event. Minimum: at least one stem event, and per-stem coverage.
    stem_events = [e for e in events if e.get("event") == "stem"]
    assert stem_events, "no stem events emitted"

    complete = events[-1]
    stem_count = complete.get("stem_count")
    if isinstance(stem_count, int):
        assert len(stem_events) >= stem_count, (
            f"stem events ({len(stem_events)}) < stem_count ({stem_count})"
        )


def test_binary_produces_manifest(
    binary_path: Path,
    test_wav: Path,
    tmp_path: Path,
) -> None:
    """stems.json manifest exists, valid JSON, has bpm > 0 and stems dict."""
    proc = _run_split(binary_path, test_wav, tmp_path, json_events=False)
    assert proc.returncode == 0, proc.stderr

    # Convention: output/<stem>/stems.json (A-validator confirmed).
    track_name = test_wav.stem
    manifest = tmp_path / track_name / "stems.json"
    assert manifest.exists(), f"manifest not found at {manifest}"

    data = json.loads(manifest.read_text())
    assert isinstance(data, dict), "manifest root must be an object"
    assert "bpm" in data and isinstance(data["bpm"], (int, float)), "missing numeric bpm"
    assert data["bpm"] > 0, f"non-positive bpm: {data['bpm']}"
    # Per sf_manifest.hpp, stems is an array of StemEntry objects (not a dict).
    assert "stems" in data, "missing stems field"
    assert isinstance(data["stems"], list), (
        f"stems must be an array (per sf_manifest.hpp); got {type(data['stems']).__name__}"
    )
    assert data["stems"], "stems array is empty"


def test_binary_manifest_schema_compat(
    binary_path: Path,
    test_wav: Path,
    tmp_path: Path,
    expected_stems_schema: dict,
) -> None:
    """Manifest field names + types match the golden template.

    Values are NOT compared (BPM detection is stochastic; stem paths are
    per-run absolute paths). We compare the *shape*: keys present + leaf
    types matching the sentinel strings in the template.
    """
    proc = _run_split(binary_path, test_wav, tmp_path, json_events=False)
    assert proc.returncode == 0, proc.stderr

    track_name = test_wav.stem
    manifest_path = tmp_path / track_name / "stems.json"
    assert manifest_path.exists()
    data = json.loads(manifest_path.read_text())

    def _check(actual, expected, path: str = "$") -> None:
        if isinstance(expected, str) and expected.startswith("<") and expected.endswith(">"):
            expected_type = expected.strip("<>")
            actual_type = _type_name(actual)
            # int is a valid float in JSON numerics
            if expected_type == "float" and actual_type == "int":
                return
            if expected_type == "number" and actual_type in ("int", "float"):
                return
            assert actual_type == expected_type, (
                f"type mismatch at {path}: expected {expected_type}, got {actual_type}"
            )
            return
        if isinstance(expected, dict):
            assert isinstance(actual, dict), f"expected object at {path}, got {_type_name(actual)}"
            for key, sub_expected in expected.items():
                if key.startswith("_"):
                    # Template-local annotation (e.g. _comment). Skip.
                    continue
                if key == "*":
                    # Wildcard: every value in actual must match sub_expected shape.
                    for k, v in actual.items():
                        _check(v, sub_expected, f"{path}.{k}")
                else:
                    assert key in actual, f"missing key at {path}: {key!r}"
                    _check(actual[key], sub_expected, f"{path}.{key}")
            return
        if isinstance(expected, list):
            assert isinstance(actual, list), f"expected array at {path}"
            if expected:
                for i, item in enumerate(actual):
                    _check(item, expected[0], f"{path}[{i}]")
            return
        # Literal value (rare — only for enums). Compare by equality.
        assert actual == expected, f"value mismatch at {path}: {actual!r} != {expected!r}"

    _check(data, expected_stems_schema)


def test_binary_self_contained(binary_path: Path) -> None:
    """Binary runs with a minimal PATH (no venv, no project env bleed)."""
    env = {
        "PATH": "/usr/bin:/bin",
        "HOME": os.environ.get("HOME", "/tmp"),
    }
    proc = subprocess.run(
        [str(binary_path), "--version"],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, (
        f"self-contained check failed: rc={proc.returncode} stderr={proc.stderr!r}"
    )
