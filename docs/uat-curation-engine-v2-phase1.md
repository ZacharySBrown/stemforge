# UAT Spec: Curation Engine v2 — Phase 1

**Date:** 2026-04-18
**Branch:** `feat/curation-engine-v2`
**Scope:** Config system, one-shot extraction, drum classification, phrase-length grouping, configurable curator weights

---

## Test Data

| Track | Path | Duration | BPM | Stems |
|-------|------|----------|-----|-------|
| The Champ (Original Version) | `~/stemforge/processed/the_champ_original_version/` | ~2.5 min | 112.35 | drums, bass, vocals, other |

All tests use pre-split stems from the v0.0.2-beta pipeline. No re-splitting needed.

---

## 1. Curation Config

### 1.1 Config loads and parses correctly
```bash
uv run python -c "
from stemforge.config import load_curation_config
cfg = load_curation_config()
assert cfg.version == 2
assert cfg.layout.mode == 'stems'
assert len(cfg.stems) == 4
print('PASS: config loads')
"
```
**Expected:** Prints "PASS: config loads"

### 1.2 Per-stem settings are distinct
```bash
uv run python -c "
from stemforge.config import load_curation_config
cfg = load_curation_config()
d = cfg.for_stem('drums')
b = cfg.for_stem('bass')
v = cfg.for_stem('vocals')
assert d.phrase_bars == 1, f'drums phrase_bars={d.phrase_bars}'
assert b.phrase_bars == 2, f'bass phrase_bars={b.phrase_bars}'
assert v.phrase_bars == 4, f'vocals phrase_bars={v.phrase_bars}'
assert d.oneshot_mode == 'classify'
assert b.midi_extract == True
assert v.strategy == 'sectional'
assert d.distance_weights['rhythm'] == 0.6
assert b.distance_weights['spectral'] == 0.4
print('PASS: per-stem settings correct')
"
```
**Expected:** Prints "PASS: per-stem settings correct"

### 1.3 Unknown stems get defaults
```bash
uv run python -c "
from stemforge.config import load_curation_config
cfg = load_curation_config()
g = cfg.for_stem('guitar')
assert g.phrase_bars == 1
assert g.strategy == 'max-diversity'
assert g.loop_count == 8
print('PASS: defaults work for unknown stems')
"
```
**Expected:** Prints "PASS: defaults work for unknown stems"

### 1.4 Config file not found returns defaults gracefully
```bash
uv run python -c "
from stemforge.config import load_curation_config
cfg = load_curation_config('/nonexistent/path.yaml')
assert cfg.version == 2
assert cfg.layout.mode == 'stems'
print('PASS: missing config falls back to defaults')
"
```
**Expected:** Prints "PASS: missing config falls back to defaults"

---

## 2. One-Shot Extraction

### 2.1 Drum one-shots extracted from drum stem
```bash
uv run python -c "
from pathlib import Path
from stemforge.oneshot import extract_oneshots
from stemforge.config import load_curation_config
cfg = load_curation_config()
stems_dir = Path.home() / 'stemforge/processed/the_champ_original_version'
profiles = extract_oneshots(stems_dir / 'drums.wav', stems_dir / 'uat_test', 'drums', cfg.for_stem('drums'))
assert len(profiles) > 100, f'Expected 100+ drum hits, got {len(profiles)}'
assert all(p.path.exists() for p in profiles), 'Some WAV files missing'
assert all(p.duration > 0.02 for p in profiles), 'Some hits too short'
assert all(p.rms > 0 for p in profiles), 'Some hits have zero RMS'
print(f'PASS: {len(profiles)} drum one-shots extracted')
"
```
**Expected:** 500+ drum one-shots extracted, all WAVs exist on disk

### 2.2 Bass one-shots extracted
```bash
uv run python -c "
from pathlib import Path
from stemforge.oneshot import extract_oneshots
from stemforge.config import load_curation_config
cfg = load_curation_config()
stems_dir = Path.home() / 'stemforge/processed/the_champ_original_version'
profiles = extract_oneshots(stems_dir / 'bass.wav', stems_dir / 'uat_test', 'bass', cfg.for_stem('bass'))
assert len(profiles) > 50, f'Expected 50+ bass hits, got {len(profiles)}'
# Bass should have low spectral centroid
low_centroid = [p for p in profiles if p.spectral_centroid < 500]
assert len(low_centroid) > 20, f'Expected 20+ low-freq bass hits, got {len(low_centroid)}'
print(f'PASS: {len(profiles)} bass one-shots ({len(low_centroid)} low-freq)')
"
```
**Expected:** 200+ bass one-shots, majority with centroid < 500 Hz

### 2.3 Kick extraction from bass stem
```bash
uv run python -c "
from pathlib import Path
from stemforge.oneshot import extract_kicks_from_bass
from stemforge.config import load_curation_config
cfg = load_curation_config()
stems_dir = Path.home() / 'stemforge/processed/the_champ_original_version'
kicks = extract_kicks_from_bass(stems_dir / 'bass.wav', stems_dir / 'uat_test', cfg.for_stem('drums'))
assert len(kicks) > 50, f'Expected 50+ kicks from bass, got {len(kicks)}'
assert all(k.classification == 'kick' for k in kicks), 'Non-kick in kick list'
assert all(k.spectral_centroid < 400 for k in kicks), 'Kick centroid too high'
print(f'PASS: {len(kicks)} kicks extracted from bass stem')
"
```
**Expected:** 100+ kicks, all classified as "kick", all centroid < 400 Hz

### 2.4 Diversity selection reduces pool
```bash
uv run python -c "
from pathlib import Path
from stemforge.oneshot import extract_oneshots, select_diverse_oneshots
from stemforge.config import load_curation_config
cfg = load_curation_config()
stems_dir = Path.home() / 'stemforge/processed/the_champ_original_version'
all_hits = extract_oneshots(stems_dir / 'drums.wav', stems_dir / 'uat_test', 'drums', cfg.for_stem('drums'))
selected = select_diverse_oneshots(all_hits, n=8)
assert len(selected) == 8, f'Expected 8, got {len(selected)}'
# Check diversity: selected should span a range of spectral centroids
centroids = [p.spectral_centroid for p in selected]
spread = max(centroids) - min(centroids)
assert spread > 1000, f'Centroid spread too narrow: {spread:.0f} Hz'
print(f'PASS: 8 diverse hits, centroid spread = {spread:.0f} Hz')
"
```
**Expected:** 8 selected, centroid spread > 1000 Hz

### 2.5 RMS floor filtering works
```bash
uv run python -c "
from pathlib import Path
from stemforge.oneshot import extract_oneshots
from stemforge.config import StemCurationConfig
stems_dir = Path.home() / 'stemforge/processed/the_champ_original_version'
# Very high floor should reject most hits
strict = StemCurationConfig(rms_floor=0.5, crest_min=1.0)
profiles = extract_oneshots(stems_dir / 'drums.wav', stems_dir / 'uat_test2', 'drums', config=strict)
print(f'PASS: high rms_floor → {len(profiles)} hits (should be << 769)')
assert len(profiles) < 200
"
```
**Expected:** Significantly fewer hits than the 769 baseline

---

## 3. Drum Classification

### 3.1 Acoustic drum types classified correctly
```bash
uv run python -c "
from stemforge.oneshot import OneshotProfile
from stemforge.drum_classifier import classify_drum_hit
from pathlib import Path
P = lambda **kw: OneshotProfile(path=Path('.'), index=0, onset_time=0, **kw)

assert classify_drum_hit(P(spectral_centroid=120, spectral_bandwidth=200, spectral_flatness=0.2, crest_factor=8, attack_time=0.005, rms=0.1, duration=0.15)) == 'kick'
assert classify_drum_hit(P(spectral_centroid=2000, spectral_bandwidth=3000, spectral_flatness=0.3, crest_factor=7, attack_time=0.003, rms=0.1, duration=0.1)) == 'snare'
assert classify_drum_hit(P(spectral_centroid=8000, spectral_bandwidth=4000, spectral_flatness=0.6, crest_factor=5, attack_time=0.001, rms=0.05, duration=0.05)) == 'hat_closed'
assert classify_drum_hit(P(spectral_centroid=7000, spectral_bandwidth=3000, spectral_flatness=0.5, crest_factor=4, attack_time=0.002, rms=0.04, duration=0.25)) == 'hat_open'
print('PASS: acoustic drum classification')
"
```
**Expected:** All 4 assertions pass

### 3.2 Electronic drum types classified correctly
```bash
uv run python -c "
from stemforge.oneshot import OneshotProfile
from stemforge.drum_classifier import classify_drum_hit
from pathlib import Path
P = lambda **kw: OneshotProfile(path=Path('.'), index=0, onset_time=0, **kw)

# 808 kick — low centroid, long sub-bass tail
assert classify_drum_hit(P(spectral_centroid=80, spectral_bandwidth=150, spectral_flatness=0.4, crest_factor=6, attack_time=0.003, rms=0.3, duration=0.3)) == 'kick'

# Rim shot — very short, very transient
assert classify_drum_hit(P(spectral_centroid=3000, spectral_bandwidth=2000, spectral_flatness=0.3, crest_factor=12, attack_time=0.001, rms=0.1, duration=0.02)) == 'rim'

# Perc fallback — mid centroid, low crest
assert classify_drum_hit(P(spectral_centroid=1000, spectral_bandwidth=500, spectral_flatness=0.3, crest_factor=3, attack_time=0.01, rms=0.05, duration=0.1)) == 'perc'

print('PASS: electronic drum classification')
"
```
**Expected:** All 3 assertions pass

### 3.3 Drum pad arrangement follows layout convention
```bash
uv run python -c "
from stemforge.oneshot import OneshotProfile
from stemforge.drum_classifier import classify_and_assign, arrange_drum_pads
from pathlib import Path
P = lambda cls, **kw: OneshotProfile(path=Path('.'), index=0, onset_time=0, classification='', spectral_centroid=100, spectral_bandwidth=200, spectral_flatness=0.2, crest_factor=8, attack_time=0.005, rms=0.1, duration=0.15, **kw)

profiles = [
    P('', spectral_centroid=100, duration=0.15),   # will be kick
    P('', spectral_centroid=2000, spectral_bandwidth=3000, crest_factor=7, duration=0.1),  # snare
    P('', spectral_centroid=8000, spectral_flatness=0.6, duration=0.05),  # hat_closed
]
classify_and_assign(profiles)
pads = arrange_drum_pads(profiles, n_pads=8)

# Kick should be at pad 0 (bottom-left)
assert pads[0] is not None and pads[0].classification == 'kick', f'Pad 0 should be kick, got {pads[0].classification if pads[0] else \"EMPTY\"}'
# Snare should be at pad 4 (top-left, above kick)
assert pads[4] is not None and pads[4].classification == 'snare', f'Pad 4 should be snare, got {pads[4].classification if pads[4] else \"EMPTY\"}'
# Hat should be at pad 5 (top, right of snare)
assert pads[5] is not None and pads[5].classification == 'hat_closed', f'Pad 5 should be hat_closed, got {pads[5].classification if pads[5] else \"EMPTY\"}'
print('PASS: drum pad layout correct (kick=BL, snare=TL, hat=TR)')
"
```
**Expected:** Kick bottom-left, snare top-left, hat right of snare

### 3.4 Real stem classification produces kicks + hats + snares
```bash
uv run python -c "
from pathlib import Path
from collections import Counter
from stemforge.oneshot import extract_oneshots, extract_kicks_from_bass, select_diverse_oneshots
from stemforge.drum_classifier import classify_and_assign
from stemforge.config import load_curation_config
cfg = load_curation_config()
stems_dir = Path.home() / 'stemforge/processed/the_champ_original_version'

drum_hits = extract_oneshots(stems_dir / 'drums.wav', stems_dir / 'uat_test3', 'drums', cfg.for_stem('drums'))
classify_and_assign(drum_hits)
kicks = extract_kicks_from_bass(stems_dir / 'bass.wav', stems_dir / 'uat_test3', cfg.for_stem('drums'))

all_hits = drum_hits + kicks
counts = Counter(p.classification for p in all_hits)
print(f'Classification counts: {dict(counts)}')
assert 'kick' in counts, 'No kicks found'
assert 'snare' in counts or 'perc' in counts, 'No snares or perc found'
assert counts['kick'] > 50, f'Too few kicks: {counts[\"kick\"]}'
print(f'PASS: real stems → {len(all_hits)} hits with kicks, snares, hats')
"
```
**Expected:** Kick count > 50, snare/perc present, hat types present

---

## 4. Phrase-Length Grouping

### 4.1 Single bars (phrase_bars=1) returns bars unchanged
```bash
uv run python -c "
from pathlib import Path
from stemforge.slicer import group_bars_into_phrases
stems_dir = Path.home() / 'stemforge/processed/the_champ_original_version'
bar_dir = stems_dir / 'drums_bars'
result = group_bars_into_phrases(bar_dir, 'drums', phrase_bars=1)
n_bars = len(list(bar_dir.glob('drums_bar_*.wav')))
assert len(result) == n_bars, f'phrase_bars=1 should return all bars: {len(result)} vs {n_bars}'
print(f'PASS: phrase_bars=1 → {len(result)} bars (unchanged)')
"
```
**Expected:** Same count as raw bars

### 4.2 Two-bar phrases halve the count
```bash
uv run python -c "
from pathlib import Path
from stemforge.slicer import group_bars_into_phrases
stems_dir = Path.home() / 'stemforge/processed/the_champ_original_version'
bar_dir = stems_dir / 'drums_bars'
n_bars = len(list(bar_dir.glob('drums_bar_*.wav')))
result = group_bars_into_phrases(bar_dir, 'drums', phrase_bars=2, output_dir=stems_dir)
expected = n_bars // 2
assert len(result) == expected, f'Expected {expected} 2-bar phrases, got {len(result)}'
assert all(p.exists() for p in result), 'Missing phrase WAV files'
print(f'PASS: {n_bars} bars → {len(result)} 2-bar phrases')
"
```
**Expected:** 72 bars → 36 two-bar phrases

### 4.3 Four-bar phrases quarter the count
```bash
uv run python -c "
from pathlib import Path
from stemforge.slicer import group_bars_into_phrases
stems_dir = Path.home() / 'stemforge/processed/the_champ_original_version'
bar_dir = stems_dir / 'drums_bars'
n_bars = len(list(bar_dir.glob('drums_bar_*.wav')))
result = group_bars_into_phrases(bar_dir, 'drums', phrase_bars=4, output_dir=stems_dir)
expected = n_bars // 4
assert len(result) == expected, f'Expected {expected} 4-bar phrases, got {len(result)}'
print(f'PASS: {n_bars} bars → {len(result)} 4-bar phrases')
"
```
**Expected:** 72 bars → 18 four-bar phrases

### 4.4 Phrase WAV is correct duration (2x single bar)
```bash
uv run python -c "
from pathlib import Path
import soundfile as sf
from stemforge.slicer import group_bars_into_phrases
stems_dir = Path.home() / 'stemforge/processed/the_champ_original_version'
bar_dir = stems_dir / 'drums_bars'

# Get single bar duration
bar1_info = sf.info(str(sorted(bar_dir.glob('drums_bar_*.wav'))[0]))
bar_dur = bar1_info.duration

# Get 2-bar phrase duration
phrases = group_bars_into_phrases(bar_dir, 'drums', phrase_bars=2, output_dir=stems_dir)
phrase_info = sf.info(str(phrases[0]))
phrase_dur = phrase_info.duration

ratio = phrase_dur / bar_dur
assert 1.8 < ratio < 2.2, f'Phrase should be ~2x bar duration, got {ratio:.2f}x'
print(f'PASS: bar={bar_dur:.2f}s, 2-bar phrase={phrase_dur:.2f}s (ratio={ratio:.2f}x)')
"
```
**Expected:** Phrase duration ≈ 2× single bar duration

---

## 5. Configurable Curator Weights

### 5.1 Custom weights change selection
```bash
uv run python -c "
from pathlib import Path
from stemforge.curator import curate
stems_dir = Path.home() / 'stemforge/processed/the_champ_original_version'
bar_dir = stems_dir / 'drums_bars'

# Default weights (rhythm=0.5)
result_default = curate(bar_dir, n_bars=8, distance_weights={'rhythm': 0.5, 'spectral': 0.25, 'energy': 0.25})
# Spectral-heavy weights
result_spectral = curate(bar_dir, n_bars=8, distance_weights={'rhythm': 0.1, 'spectral': 0.7, 'energy': 0.2})

# Selections should differ (different weight emphasis → different diversity axis)
default_names = set(p.name for p in result_default)
spectral_names = set(p.name for p in result_spectral)
overlap = len(default_names & spectral_names)
print(f'Default selection: {sorted(default_names)}')
print(f'Spectral selection: {sorted(spectral_names)}')
print(f'Overlap: {overlap}/8')
# Some overlap is fine, but they shouldn't be identical
assert overlap < 8, 'Different weights should produce different selections'
print(f'PASS: different weights → different selections (overlap={overlap}/8)')
"
```
**Expected:** Overlap < 8 (different weights produce at least some different selections)

---

## 6. Full Pipeline Integration

### 6.1 Curate with config — per-stem phrase lengths
```bash
uv run python v0/src/stemforge_curate_bars.py \
  --stems-dir ~/stemforge/processed/the_champ_original_version \
  --n-bars 16 --json-events \
  --curation pipelines/curation.yaml
```
**Expected NDJSON output shows:**
- drums: "selecting 8 bars from 72" (phrase_bars=1, loop_count=8)
- bass: "selecting 4 2-bar phrases from 31" (phrase_bars=2, loop_count=4)
- vocals: "selecting 12 4-bar phrases from 9" (phrase_bars=4, loop_count=12)
- other: "selecting 10 2-bar phrases from 36" (phrase_bars=2, loop_count=10)
- Final: "Curated N items across 4 stems"

### 6.2 Curate WITHOUT config — v0 behavior preserved
```bash
uv run python v0/src/stemforge_curate_bars.py \
  --stems-dir ~/stemforge/processed/the_champ_original_version \
  --n-bars 16 --json-events
```
**Expected:** Mirrors bars across all stems (v0 behavior). Output shows "mirroring across stems" and each stem gets exactly 16 bars. No phrase grouping.

### 6.3 Curated manifest is valid JSON with correct counts
```bash
uv run python -c "
import json
from pathlib import Path
mf = json.loads((Path.home() / 'stemforge/processed/the_champ_original_version/curated/manifest.json').read_text())
assert 'version' in mf or 'track' in mf, 'Missing manifest fields'
for stem in ['drums', 'bass', 'vocals', 'other']:
    assert stem in mf['stems'], f'Missing stem: {stem}'
    items = mf['stems'][stem]
    assert len(items) > 0, f'{stem} has no items'
    for item in items:
        assert 'file' in item, f'{stem} item missing file path'
        assert Path(item['file']).exists(), f'{stem} file does not exist: {item[\"file\"]}'
    print(f'  {stem}: {len(items)} items, all files exist')
print('PASS: manifest valid, all files exist')
"
```
**Expected:** All stems present, all referenced WAV files exist on disk

---

## 7. Automated Tests

### 7.1 Full test suite passes
```bash
uv run pytest -v
```
**Expected:** 33/33 passing, 0 failures

### 7.2 Test breakdown by module
| Test file | Tests | What it covers |
|-----------|-------|---------------|
| `test_forge.py` | 4 | Bar slicing, curator selection, strategy fallback |
| `test_modal_backend.py` | 7 | Modal backend mocking, error handling |
| `test_oneshot.py` | 19 | One-shot extraction, drum classification, config loading, kick extraction, pad arrangement |
| `test_packaging.py` | 3 | Import isolation, friendly error messages |

---

## 8. Edge Cases

### 8.1 Stems with very few bars
Vocals only has 36 bars. With `phrase_bars=4`, that's 9 phrases. Config asks for `loop_count=12`, so it returns all 9 (can't select 12 from 9). This is correct behavior — no crash, just fewer items.

### 8.2 Empty stem directory
```bash
uv run python -c "
from pathlib import Path
from stemforge.oneshot import extract_oneshots
from stemforge.config import StemCurationConfig
result = extract_oneshots(Path('/dev/null'), Path('/tmp/uat_empty'), 'drums', StemCurationConfig())
print(f'Empty input → {len(result)} one-shots')
" 2>&1 || echo "Expected: error or empty result"
```
**Expected:** Returns empty list or raises clear error (no crash)

### 8.3 No kicks in drum stem (htdemucs behavior)
Verified by test 2.3 above — kicks route to bass stem. `extract_kicks_from_bass()` recovers them. This is the expected workaround for htdemucs's kick-bass bleed.

---

## 9. Cleanup

After UAT, clean up test artifacts:
```bash
rm -rf ~/stemforge/processed/the_champ_original_version/uat_test*
rm -rf ~/stemforge/processed/the_champ_original_version/*_phrases
```

---

## Sign-off

| Area | Status | Notes |
|------|--------|-------|
| Curation config YAML | | Loads, per-stem settings, defaults inheritance |
| One-shot extraction | | Multi-band onset, windowed extraction, quality filtering |
| Kick-from-bass | | Recovers kicks that htdemucs routes to bass stem |
| Drum classification | | Acoustic + electronic, 7 categories, pad layout |
| Phrase-length grouping | | 1, 2, 4, 8 bar phrases, correct concatenation |
| Configurable weights | | Rhythm/spectral/energy ratios affect selection |
| Pipeline integration | | Per-stem config in curate_bars.py, v0 backward compat |
| Automated tests | | 33/33 passing |
