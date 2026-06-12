# Manifest Shape Bugs — Auto-Curate Mode

Found 2026-05-15 by running `stemforge forge` on Definition (auto-curate, rhythm-taxonomy, n-bars=14).

Tempo detection and pipeline execution are clean. All three issues are in the **new-shape manifest writers** (`stemforge/forge/manifest_io.py`).

---

## Bug 1 (HIGH): Auto-curation `duration_bars` wrong for single-bar curated entries

**Symptom:** Every clip in `auto_curation_manifest.json` has `duration_bars: 14` and sequential `source_bar_range` values (`[0,14]`, `[14,28]`, …) instead of `duration_bars: 1` with correct per-bar source indices.

**File:** `stemforge/forge/manifest_io.py`, function `_legacy_extract`, line 352 + 371-373.

```python
n_bars = int(data.get("n_bars", 1)) or 1          # line 352 — reads 14
# ...
duration_bars = int(entry.get("duration_bars", n_bars))  # line 371 — defaults to 14
start_bar = (position - 1) * duration_bars                # line 372 — 0, 14, 28, …
end_bar = start_bar + duration_bars                       # line 373 — 14, 28, 42, …
```

**Root cause:** `n_bars` in the legacy curated dict means "total bars curated" (the `--n-bars` CLI arg). `_legacy_extract` uses it as the per-entry default for `duration_bars`. For auto-curate mode each entry is 1 bar, so this inflates every clip by 14x.

**Impact:** Any downstream loader reading `duration_bars` from `auto_curation_manifest.json` will create 14-bar clips instead of 1-bar clips. The M4L configurator device consumes this manifest.

**Fix options:**
1. Write `"duration_bars": 1` in each curated entry at the forge CLI write site (around `cli.py:1800`). Cleanest — no `_legacy_extract` change needed.
2. Change the default in `_legacy_extract` from `n_bars` to `1`. Riskier — production-mode curated manifests may rely on the current behavior.
3. Have `build_from_curated_dict` pass a hint so `_legacy_extract` knows it's single-bar entries.

---

## Bug 2 (MEDIUM): Arrangement `duration_sec` includes prechop padding

**Symptom:** `arrangement_manifest.json` chunks have `duration_sec: 16.02` for entries tagged `duration_bars: 4`. At 89.98 BPM, 4 bars = ~10.67s. The extra ~5.35s is prechop pre/post padding.

**File:** `stemforge/forge/manifest_io.py`, function `build_arrangement_from_prechop`, line 552.

```python
duration_sec = float(raw.get("total_sec") or (bars * bar_period_sec))
```

**Root cause:** Prechop's `total_sec` includes padding bars (for clean crossfades). The arrangement schema's `duration_bars` only counts musical content. A consumer using `duration_sec` to set a clip endpoint will overshoot; one using `duration_bars * bar_period` will be correct but inconsistent with `duration_sec`.

**Fix:** Compute `duration_sec` from bars + BPM instead of using `total_sec`:
```python
duration_sec = bars * bar_period_sec
```

---

## Bug 3 (LOW): Arrangement duplicate `bar_position=0` for pre-roll

**Symptom:** Chunks 001 and 002 both have `bar_position: 0, source_position_sec: 8.94`. Chunk 001 is pre-roll audio (before the first downbeat at 8.94s), chunk 002 is the actual first musical bar.

**File:** `stemforge/forge/manifest_io.py`, function `build_arrangement_from_prechop`, lines 549-551.

```python
offset_from_bar_1 = max(0, chunk_index - musical_bar_1)  # chunk 1: max(0, 1-2)=0
bar_position = offset_from_bar_1 * bars                   # 0
source_position_sec = first_downbeat_sec + 0 * ...        # 8.94
```

**Root cause:** Pre-roll chunks (chunk_index < musical_bar_1) clamp to offset 0. The docstring (line 499) says they should get `source_position_sec = 0`, but the formula gives `first_downbeat_sec`. Two chunks map to the same grid position with the same source timestamp, which is logically wrong — the pre-roll audio starts before 8.94s, not at it.

**Fix:** Special-case pre-roll chunks:
```python
if chunk_index < musical_bar_1:
    bar_position = 0
    source_position_sec = 0.0  # matches docstring intent
else:
    ...
```

---

## Validation data (Definition, auto-curate)

| Field | Detected | Truth | Error | Tolerance | Result |
|-------|----------|-------|-------|-----------|--------|
| BPM | 89.98 | 89.88 | 0.10 | 0.15 | PASS |
| first_downbeat_sec | 8.94 | 8.934 | 0.006s | 0.05s | PASS |

Legacy `curated/manifest.json` is correct (14 diverse bar indices from rhythm-taxonomy). All bugs are in the new-shape writer path only.
