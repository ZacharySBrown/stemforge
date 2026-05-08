"""Tests for `stemforge_curate_bars._load_stems_manifest_tempo` +
`_synthesize_beat_grid` (2026-05-06 fix).

Curation must use the same beat detection as `stemforge split`/`re-anchor`.
The script's helpers, loaded via importlib (since v0/src/ is not a package),
are what we audit here. End-to-end behavior against the real script is
covered by manual re-runs documented in the PR.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent
CURATE_BARS_PATH = REPO_ROOT / "v0" / "src" / "stemforge_curate_bars.py"


@pytest.fixture(scope="module")
def curate_bars():
    """Load the curate_bars script as a module via importlib."""
    spec = importlib.util.spec_from_file_location("stemforge_curate_bars", CURATE_BARS_PATH)
    assert spec is not None
    assert spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── _load_stems_manifest_tempo ───────────────────────────────────────────────


def test_load_tempo_from_well_formed_stems_manifest(curate_bars, tmp_path: Path):
    (tmp_path / "stems.json").write_text(
        json.dumps(
            {
                "track_name": "x",
                "bpm": 125.0,
                "tempo": {
                    "source": "user-override",
                    "first_downbeat_sec": 0.282656,
                    "confidence": "high",
                },
            }
        )
    )
    out = curate_bars._load_stems_manifest_tempo(tmp_path)
    assert out == {
        "bpm": 125.0,
        "first_downbeat_sec": 0.282656,
        "source": "user-override",
    }


def test_load_tempo_returns_none_when_manifest_missing(curate_bars, tmp_path: Path):
    assert curate_bars._load_stems_manifest_tempo(tmp_path) is None


def test_load_tempo_returns_none_on_malformed_json(curate_bars, tmp_path: Path):
    (tmp_path / "stems.json").write_text("{not valid json")
    assert curate_bars._load_stems_manifest_tempo(tmp_path) is None


def test_load_tempo_returns_none_when_bpm_missing(curate_bars, tmp_path: Path):
    (tmp_path / "stems.json").write_text(json.dumps({"track_name": "x", "tempo": {}}))
    assert curate_bars._load_stems_manifest_tempo(tmp_path) is None


def test_load_tempo_defaults_first_downbeat_to_zero(curate_bars, tmp_path: Path):
    (tmp_path / "stems.json").write_text(json.dumps({"bpm": 120.0, "tempo": {}}))
    out = curate_bars._load_stems_manifest_tempo(tmp_path)
    assert out is not None
    assert out["bpm"] == 120.0
    assert out["first_downbeat_sec"] == 0.0


def test_load_tempo_falls_back_through_source_field(curate_bars, tmp_path: Path):
    (tmp_path / "stems.json").write_text(json.dumps({"bpm": 90.0, "backend": "demucs"}))
    out = curate_bars._load_stems_manifest_tempo(tmp_path)
    assert out is not None
    assert out["source"] == "demucs"


# ── _synthesize_beat_grid ────────────────────────────────────────────────────


def test_synthesize_beat_grid_first_downbeat_zero(curate_bars):
    # 120 BPM, 4 beats/bar, 16 sec → 32 beats, 8 downbeats.
    beats, downbeats = curate_bars._synthesize_beat_grid(
        bpm=120.0,
        first_downbeat_sec=0.0,
        duration_sec=16.0,
        time_sig=4,
    )
    assert beats[0] == pytest.approx(0.0)
    assert np.diff(beats) == pytest.approx(np.full(len(beats) - 1, 0.5))
    assert downbeats[0] == pytest.approx(0.0)
    assert np.diff(downbeats) == pytest.approx(np.full(len(downbeats) - 1, 2.0))


def test_synthesize_beat_grid_with_first_downbeat_offset(curate_bars):
    # 125 BPM (0.48 s/beat), first_downbeat=0.282656, 16 sec.
    beats, downbeats = curate_bars._synthesize_beat_grid(
        bpm=125.0,
        first_downbeat_sec=0.282656,
        duration_sec=16.0,
        time_sig=4,
    )
    # The first downbeat must be present in `downbeats` exactly (anchoring
    # the grid).
    assert any(abs(d - 0.282656) < 1e-9 for d in downbeats)
    # Beat period = 60/125 = 0.48s.
    assert np.allclose(np.diff(beats), 0.48, atol=1e-9)


def test_synthesize_beat_grid_extrapolates_beats_before_downbeat(curate_bars):
    # first_downbeat=2.5s should yield beats at 2.5, 2.0, 1.5, 1.0, 0.5 (and 0.0 if exact).
    beats, downbeats = curate_bars._synthesize_beat_grid(
        bpm=120.0,  # 0.5 s/beat
        first_downbeat_sec=2.5,
        duration_sec=10.0,
        time_sig=4,
    )
    # Should include beats below first_downbeat.
    assert beats[0] < 2.5
    # First downbeat appears in the downbeats list.
    assert any(abs(d - 2.5) < 1e-9 for d in downbeats)


def test_synthesize_beat_grid_zero_bpm_raises(curate_bars):
    with pytest.raises(ValueError, match="bpm"):
        curate_bars._synthesize_beat_grid(
            bpm=0.0, first_downbeat_sec=0.0, duration_sec=10.0, time_sig=4
        )


def test_synthesize_beat_grid_zero_duration_raises(curate_bars):
    with pytest.raises(ValueError, match="duration_sec"):
        curate_bars._synthesize_beat_grid(
            bpm=120.0, first_downbeat_sec=0.0, duration_sec=0.0, time_sig=4
        )


# ── Acceptance regression sentinel ───────────────────────────────────────────


def test_believer_regression_anchor(curate_bars, tmp_path: Path):
    # Believer's exact tempo block from stems.json after the user's
    # re-anchor. Curate must read 125.0 / 0.282656, not re-detect.
    (tmp_path / "stems.json").write_text(
        json.dumps(
            {
                "track_name": "believer",
                "bpm": 125.0,
                "tempo": {
                    "source": "user-override",
                    "first_downbeat_sec": 0.282656,
                    "confidence": "high",
                    "warning": "re-anchored from bpm=125.0 first_downbeat=0.3s",
                },
            }
        )
    )
    out = curate_bars._load_stems_manifest_tempo(tmp_path)
    assert out is not None
    assert out["bpm"] == 125.0  # NOT 126.05 (the librosa drift the bug caused)
    assert out["first_downbeat_sec"] == 0.282656
