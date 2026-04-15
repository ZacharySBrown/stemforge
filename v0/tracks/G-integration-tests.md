# Track G — End-to-End Integration Tests

## Goal

Automated test suite that verifies v0 works without a human opening Ableton. Where Ableton cannot be scripted headlessly, verify structural correctness of artifacts instead.

## Scope

Three testable layers. A fourth (full GUI run) is a one-time manual acceptance, documented but not automated.

| Layer | Automated? | Tool |
|---|---|---|
| 1. Binary NDJSON contract | Yes | pytest + subprocess |
| 2. .amxd structural validity | Yes | pytest + zip/json parsing |
| 3. .als structural validity | Yes | pytest + lxml |
| 4. Full Ableton session | No | human acceptance, one-time per release |

## Inputs

- `v0/build/stemforge-native` (from A)
- `v0/build/StemForge.amxd` (from C)
- `v0/build/StemForge.als` (from D)
- `v0/interfaces/ndjson.schema.json`
- `v0/interfaces/tracks.yaml`
- A test WAV fixture

## Outputs

- `v0/tests/test_binary.py`
- `v0/tests/test_amxd.py`
- `v0/tests/test_als.py`
- `v0/tests/conftest.py` — fixtures: path resolution, temp dirs
- `v0/tests/fixtures/short_loop.wav` — 5-second loop at 120 BPM (generated, not copyrighted)
- `v0/tests/fixtures/expected_stems.json` — golden manifest for regression
- `v0/tests/validate-ndjson.py` — standalone CLI for schema validation (reused from Track A)
- `v0/state/G/done.flag`

## Test Details

### test_binary.py

```python
import json, subprocess, jsonschema
from pathlib import Path

def test_binary_emits_valid_ndjson(tmp_path, binary_path, schema, test_wav):
    proc = subprocess.run(
        [str(binary_path), 'split', str(test_wav),
         '--json-events', '--output', str(tmp_path)],
        capture_output=True, text=True, timeout=300,
    )
    assert proc.returncode == 0, proc.stderr
    events = [json.loads(l) for l in proc.stdout.splitlines() if l.strip()]
    for evt in events:
        jsonschema.validate(evt, schema)

    # Invariants
    assert events[0]['event'] == 'started'
    assert any(e['event'] == 'bpm' for e in events)
    assert events[-1]['event'] == 'complete'

def test_binary_produces_manifest(tmp_path, binary_path, test_wav):
    subprocess.run([str(binary_path), 'split', str(test_wav), '--output', str(tmp_path)], check=True)
    manifest = tmp_path / 'short_loop' / 'stems.json'
    assert manifest.exists()
    data = json.loads(manifest.read_text())
    assert data['bpm'] > 0
    assert 'stems' in data

def test_binary_self_contained(binary_path):
    # Binary runs without Python, without PATH pointing at any venv
    env = {'PATH': '/usr/bin:/bin', 'HOME': os.environ['HOME']}
    proc = subprocess.run([str(binary_path), '--version'], env=env, capture_output=True)
    assert proc.returncode == 0
```

### test_amxd.py

```python
def test_amxd_is_valid_bundle(amxd_path):
    # Depending on C's chosen path, either it's a zip-like container with
    # patch.json + metadata, or a .maxpat-style binary.
    # Validate the minimum: file exists, non-zero size, first bytes are
    # the expected magic.
    assert amxd_path.exists()
    assert amxd_path.stat().st_size > 1024
    magic = amxd_path.read_bytes()[:8]
    # Max .amxd magic header — verify per C's chosen path

def test_amxd_references_bridge_js(amxd_path):
    # Extract inline patch JSON, confirm it contains a node.script
    # reference to stemforge_bridge.v0.js
    patch = extract_maxpat(amxd_path)
    assert 'stemforge_bridge.v0.js' in json.dumps(patch)

def test_amxd_ui_matches_device_yaml(amxd_path, device_yaml):
    patch = extract_maxpat(amxd_path)
    ui_ids = {box['id'] for box in walk_boxes(patch)}
    for expected in device_yaml['ui']['elements']:
        assert expected['id'] in ui_ids
```

### test_als.py

```python
import gzip, lxml.etree as ET

def test_als_is_gzip_xml(als_path):
    with gzip.open(als_path) as f:
        tree = ET.parse(f)
    assert tree.getroot().tag == 'Ableton'

def test_als_has_expected_tracks(als_path, tracks_yaml):
    with gzip.open(als_path) as f:
        tree = ET.parse(f)
    names = [n.get('Value') for n in tree.findall('.//Track//Name/EffectiveName')]
    for track in tracks_yaml['tracks']:
        assert track['name'] in names

def test_als_device_chains(als_path, tracks_yaml):
    # For each track, verify the device count and first device type match
    # spot-check: SF | Drums Raw → first device is Compressor
    ...
```

### test_install_layout.py (optional — runs in CI post-install)

```python
def test_pkg_installs_to_expected_paths():
    # Only runs if PKG_INSTALLED=1 env var set (CI integration job)
    assert Path('/usr/local/bin/stemforge-native').exists()
    ...
```

## Fixture: short_loop.wav

Generate programmatically — no copyright issue:

```python
# v0/tests/fixtures/generate_loop.py
import numpy as np, soundfile as sf
sr = 44100
bpm = 120
beat_sec = 60/bpm
dur = 8 * beat_sec  # 8 beats = 2 bars at 120 BPM
t = np.linspace(0, dur, int(sr*dur), endpoint=False)
# Simple kick on every beat + hat offbeats
kick = sum(np.sin(2*np.pi*60*t) * np.exp(-5*(t - i*beat_sec)) * (t >= i*beat_sec) * (t < i*beat_sec + 0.2) for i in range(8))
hat  = sum(np.random.randn(len(t)) * 0.2 * np.exp(-30*(t - (i+0.5)*beat_sec)) * (t >= (i+0.5)*beat_sec) * (t < (i+0.5)*beat_sec + 0.05) for i in range(8))
sig = kick + hat
sig = sig / np.max(np.abs(sig))
sf.write('short_loop.wav', sig.astype(np.float32), sr)
```

## Acceptance

- `pytest v0/tests/` passes on a machine with the three build artifacts present.
- CI runs G after the release workflow and blocks publish if tests fail.
- `test_binary_self_contained` confirms the binary works without any Python.

## Subagent Brief

You are implementing Track G. Dependencies: A, C, D `done.flag` all present.

**Block on predecessors, then read:**
- `v0/PLAN.md`, `v0/SHARED.md`
- All `v0/interfaces/*`
- `v0/build/{stemforge-native,StemForge.amxd,StemForge.als}`

**Produce:** everything in Outputs.

**Boundaries:**
- Pytest only — no other runners.
- No reliance on Ableton, no reliance on network.
- Fixture WAV generated at test-time or committed (≤ 1MB).

Write `v0/state/G/done.flag` when all tests pass against the current build artifacts.
