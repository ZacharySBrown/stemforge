"""Feed NDJSON lines into the bridge JS and verify Max.outlet() receives
the correct per-event arguments.

We stub node's require('max-api') with a fake that records outlet() calls,
then import the bridge module under Node and exercise its internal
__test__.parseAndEmit. The test requires `node` on PATH (already required
by the bridge at runtime).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[3]
BRIDGE = REPO_ROOT / "v0" / "src" / "m4l-js" / "stemforge_bridge.v0.js"

HARNESS_JS = r"""
// Injected Node harness. Shims require('max-api') with a recorder, then
// loads the bridge and feeds it a sequence of NDJSON lines. Prints JSON
// array of outlet calls on stdout.

const Module = require('module');
const path = require('path');

const calls = [];
const maxApiStub = {
    outlet: (...args) => { calls.push(args); },
    post: () => {},
    POST_LEVELS: { ERROR: 2, WARN: 1 },
    addHandler: () => {},
};

// Intercept require('max-api') with a stub. All other requires pass through.
const origResolve = Module._resolveFilename;
Module._resolveFilename = function (request, parent, ...rest) {
    if (request === 'max-api') return 'max-api-stub';
    return origResolve.call(this, request, parent, ...rest);
};
const origLoad = Module._load;
Module._load = function (request, parent, ...rest) {
    if (request === 'max-api') return maxApiStub;
    return origLoad.call(this, request, parent, ...rest);
};

const bridgePath = process.argv[2];
const linesJson = process.argv[3];
const lines = JSON.parse(linesJson);

const bridge = require(bridgePath);
const t = bridge.__test__;
for (const line of lines) { t.parseAndEmit(line); }

process.stdout.write(JSON.stringify(calls));
"""


def _node_available() -> bool:
    return shutil.which("node") is not None


def _run_bridge(lines: list[str]) -> list[list]:
    """Send NDJSON lines through the bridge's parseAndEmit, return outlet calls."""
    harness_path = HERE / "_bridge_harness_tmp.js"
    harness_path.write_text(HARNESS_JS)
    try:
        result = subprocess.run(
            ["node", str(harness_path), str(BRIDGE), json.dumps(lines)],
            capture_output=True,
            text=True,
            timeout=20,
            env={**os.environ, "NODE_PATH": ""},
        )
    finally:
        harness_path.unlink(missing_ok=True)
    if result.returncode != 0:
        raise RuntimeError(f"harness failed: {result.stderr}\n{result.stdout}")
    return json.loads(result.stdout)


@pytest.mark.skipif(not _node_available(), reason="node not installed")
def test_progress_event_emits_pct_and_phase():
    calls = _run_bridge([json.dumps({
        "event": "progress", "phase": "splitting", "pct": 42
    })])
    assert calls == [["progress", 42, "splitting"]]


@pytest.mark.skipif(not _node_available(), reason="node not installed")
def test_stem_event_emits_name_and_path():
    calls = _run_bridge([json.dumps({
        "event": "stem", "name": "drums",
        "path": "/tmp/drums.wav", "size_bytes": 1234
    })])
    assert calls == [["stem", "drums", "/tmp/drums.wav", 1234]]


@pytest.mark.skipif(not _node_available(), reason="node not installed")
def test_bpm_event_emits_value():
    calls = _run_bridge([json.dumps({
        "event": "bpm", "bpm": 128.5, "beat_count": 512
    })])
    assert calls == [["bpm", 128.5, 512]]


@pytest.mark.skipif(not _node_available(), reason="node not installed")
def test_slice_dir_event_emits_triple():
    calls = _run_bridge([json.dumps({
        "event": "slice_dir", "stem": "drums",
        "dir": "/tmp/drums_beats", "count": 32
    })])
    assert calls == [["slice_dir", "drums", "/tmp/drums_beats", 32]]


@pytest.mark.skipif(not _node_available(), reason="node not installed")
def test_complete_event_emits_manifest():
    calls = _run_bridge([json.dumps({
        "event": "complete", "manifest": "/tmp/stems.json",
        "bpm": 120, "stem_count": 4
    })])
    assert calls == [["complete", "/tmp/stems.json", 120, 4]]


@pytest.mark.skipif(not _node_available(), reason="node not installed")
def test_error_event_emits_phase_and_message():
    calls = _run_bridge([json.dumps({
        "event": "error", "phase": "splitting", "message": "ORT crash"
    })])
    assert calls == [["error", "splitting", "ORT crash"]]


@pytest.mark.skipif(not _node_available(), reason="node not installed")
def test_malformed_line_is_silently_dropped():
    calls = _run_bridge(["not json at all", "", "{ bogus"])
    assert calls == []


@pytest.mark.skipif(not _node_available(), reason="node not installed")
def test_unknown_event_is_dropped():
    calls = _run_bridge([json.dumps({"event": "gossip", "rumor": "spicy"})])
    assert calls == []


@pytest.mark.skipif(not _node_available(), reason="node not installed")
def test_started_event_surfaces_as_progress_zero():
    calls = _run_bridge([json.dumps({
        "event": "started", "track": "t", "audio": "/a.wav", "output_dir": "/o"
    })])
    assert calls == [["progress", 0, "starting"]]


@pytest.mark.skipif(not _node_available(), reason="node not installed")
def test_stream_of_events_preserves_order():
    lines = [
        json.dumps({"event": "progress", "phase": "loading_model", "pct": 5}),
        json.dumps({"event": "progress", "phase": "splitting", "pct": 50}),
        json.dumps({"event": "bpm", "bpm": 128, "beat_count": 256}),
        json.dumps({"event": "complete", "manifest": "/m.json",
                    "bpm": 128, "stem_count": 4}),
    ]
    calls = _run_bridge(lines)
    assert [c[0] for c in calls] == ["progress", "progress", "bpm", "complete"]
