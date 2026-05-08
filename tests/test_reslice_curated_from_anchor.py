"""Tests for `stemforge_curate_bars.reslice_curated_from_anchor`.

This is the helper that `stemforge re-anchor` calls automatically (and
that `stemforge reslice-curated` exposes manually) to keep curated bar
loops in sync with `stems.json` after a user re-anchor.

What we verify:
1. Loop WAVs are rewritten at the new bar duration when BPM changes.
2. The source-stem read offset honours the new `first_downbeat_sec`,
   so a re-anchor that shifts the bar grid actually shifts which audio
   ends up in the loop file.
3. The manifest's clip / warp_markers / loop blocks reflect the new
   bar duration; `bpm` field updated.
4. One-shots are NOT rewritten (peak-anchored, grid-independent).
5. User-committed `offsets` are preserved.
6. Errors are clean: missing stems.json, missing manifest, no tempo
   block.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf


REPO_ROOT = Path(__file__).resolve().parent.parent
CURATE_BARS_PATH = REPO_ROOT / "v0" / "src" / "stemforge_curate_bars.py"


@pytest.fixture(scope="module")
def curate_bars():
    spec = importlib.util.spec_from_file_location("stemforge_curate_bars", CURATE_BARS_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── Test helpers ─────────────────────────────────────────────────────────────


def _write_marked_stem(path: Path, sr: int, duration_sec: float, marker_period_sec: float) -> None:
    """Render a stem WAV that's silent except for a short impulse every
    `marker_period_sec`. Used to verify which time region of the source
    stem ends up in a re-sliced bar.
    """
    n = int(round(duration_sec * sr))
    audio = np.zeros((n, 2), dtype=np.float32)
    period_n = max(1, int(round(marker_period_sec * sr)))
    pulse_len = max(1, int(round(0.005 * sr)))  # 5 ms pulse
    pos = 0
    while pos + pulse_len <= n:
        audio[pos : pos + pulse_len, :] = 0.5
        pos += period_n
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(path), audio, sr, subtype="PCM_24")


def _build_curated_track(
    track_dir: Path,
    *,
    bpm: float,
    first_downbeat_sec: float,
    bars: int = 32,
    pad_bars: float = 0.5,
    selected_bar_indices: list[int] | None = None,
    sr: int = 44100,
) -> dict:
    """Synthesize a `stems_dir` with stems.json + curated/manifest.json
    that looks like what `stemforge_curate_bars.run` would have produced.

    Returns the parsed manifest for inspection.
    """
    if selected_bar_indices is None:
        selected_bar_indices = [3, 8, 12]

    bar_duration = 60.0 / bpm * 4
    duration_sec = first_downbeat_sec + bars * bar_duration + 1.0

    # Source stem WAVs — a kick once per beat so we can identify time
    # regions by counting impulses in the resliced bar.
    track_dir.mkdir(parents=True, exist_ok=True)
    stems = ["drums", "bass", "vocals", "other"]
    for s in stems:
        _write_marked_stem(track_dir / f"{s}.wav", sr, duration_sec, marker_period_sec=60.0 / bpm)

    # stems.json with tempo block
    stems_json = {
        "track_name": "test",
        "source_file": str(track_dir / "source.wav"),
        "backend": "demucs",
        "pipeline": "default",
        "bpm": bpm,
        "beat_count": int(duration_sec * bpm / 60.0),
        "stems": [
            {"name": s, "wav_path": str(track_dir / f"{s}.wav"), "beat_count": 0} for s in stems
        ],
        "tempo": {
            "source": "user-override",
            "first_downbeat_sec": first_downbeat_sec,
            "confidence": "high",
            "n_downbeats": bars,
            "all_estimates": [],
        },
    }
    (track_dir / "stems.json").write_text(json.dumps(stems_json))

    # curated/<stem>/bar_NNN.wav files — sliced at the OLD anchor.
    curated_dir = track_dir / "curated"
    curated_dir.mkdir(exist_ok=True)
    manifest_stems: dict[str, dict] = {}
    for s in stems:
        stem_curated = curated_dir / s
        stem_curated.mkdir(exist_ok=True)
        loops = []
        for pos, bar_idx in enumerate(selected_bar_indices, start=1):
            # Pretend the original curate ran at the same anchor — write
            # whatever audio (we'll verify it gets REWRITTEN by reslice).
            dst = stem_curated / f"bar_{pos:03d}.wav"
            # Token placeholder content: 1 sec of zeros at the wrong duration.
            sf.write(str(dst), np.zeros((sr, 2), dtype=np.float32), sr, subtype="PCM_24")
            inner_start = pad_bars * bar_duration
            inner_end = inner_start + bar_duration
            padded_end = (2 * pad_bars + 1.0) * bar_duration
            loops.append(
                {
                    "position": pos,
                    "source_bar_index": bar_idx,
                    "phrase_bars": 1,
                    "file": str(dst),
                    "clip": {
                        "raw_start_sec": inner_start,
                        "raw_end_sec": inner_end,
                        "padded_start_sec": 0.0,
                        "padded_end_sec": padded_end,
                        "pad_bars": pad_bars,
                        "wide_window": False,
                    },
                    "warp_markers": [
                        {"time_sec": 0.0, "beat_pos": 0.0, "type": "start"},
                        {
                            "time_sec": padded_end,
                            "beat_pos": (2 * pad_bars + 1.0) * 4,
                            "type": "end",
                        },
                    ],
                    "loop": {
                        "enabled": True,
                        "loop_start_sec": inner_start,
                        "loop_end_sec": inner_end,
                        "loop_mode": "none",
                    },
                    "offsets": {
                        "committed": False,
                        "start_offset_sec": 0.0,
                        "end_offset_sec": 0.0,
                        "note": "",
                    },
                }
            )
        # One synthetic one-shot for the drums stem (must NOT be touched).
        oneshots = []
        if s == "drums":
            os_dir = stem_curated / "oneshots"
            os_dir.mkdir(exist_ok=True)
            os_path = os_dir / "os_001.wav"
            sf.write(str(os_path), np.zeros((1024, 2), dtype=np.float32), sr, subtype="PCM_24")
            oneshots.append(
                {
                    "position": 1,
                    "file": str(os_path),
                    "classification": "kick",
                    "clip": {
                        "raw_start_sec": 0.0,
                        "raw_end_sec": 0.0232,
                        "padded_start_sec": 0.0,
                        "padded_end_sec": 0.0232,
                        "pad_bars": 0.0,
                        "wide_window": False,
                    },
                    "warp_markers": [
                        {"time_sec": 0.0, "beat_pos": 0.0, "type": "start"},
                        {"time_sec": 0.0232, "beat_pos": 0.05, "type": "end"},
                    ],
                    "loop": {
                        "enabled": False,
                        "loop_start_sec": 0.0,
                        "loop_end_sec": 0.0232,
                        "loop_mode": "none",
                    },
                    "offsets": {
                        "committed": False,
                        "start_offset_sec": 0.0,
                        "end_offset_sec": 0.0,
                        "note": "",
                    },
                }
            )
        manifest_stems[s] = {"loops": loops, "oneshots": oneshots}

    manifest = {
        "version": 2,
        "track": "test",
        "source_dir": str(track_dir),
        "strategy": "max-diversity",
        "n_bars": len(selected_bar_indices),
        "bpm": bpm,
        "beat_count": int(duration_sec * bpm / 60.0),
        "time_signature_numerator": 4,
        "layout_mode": "production",
        "stems": manifest_stems,
        "processing_config": {},
    }
    (curated_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return manifest


# ── Tests ────────────────────────────────────────────────────────────────────


def test_reslice_rewrites_loop_wavs_at_new_bar_duration(curate_bars, tmp_path: Path):
    """BPM 120 → 90: each loop WAV should change duration from 4*bar120 to 4*bar90."""
    track_dir = tmp_path / "track"
    _build_curated_track(track_dir, bpm=120.0, first_downbeat_sec=0.0, selected_bar_indices=[3, 8])

    # Now simulate a re-anchor: rewrite stems.json with new bpm
    stems_json = json.loads((track_dir / "stems.json").read_text())
    stems_json["bpm"] = 90.0
    stems_json["tempo"]["first_downbeat_sec"] = 0.0
    (track_dir / "stems.json").write_text(json.dumps(stems_json))

    curate_bars.reslice_curated_from_anchor(stems_dir=track_dir, json_events=False)

    # Inner exact-bar duration at 90 BPM = 60/90 * 4 = 2.667s
    # With pad_bars=0.5 each side, padded WAV = 2 * (60/90 * 4 * 0.5) + 60/90*4
    #                                         = 60/90 * 4 * 2 = 5.333s
    expected_padded = 2.0 * 60.0 / 90.0 * 4
    bar_001 = track_dir / "curated" / "drums" / "bar_001.wav"
    info = sf.info(str(bar_001))
    actual_dur = info.frames / info.samplerate
    assert abs(actual_dur - expected_padded) < 0.005, (
        f"bar_001.wav should be {expected_padded:.4f}s at 90 BPM, got {actual_dur:.4f}s"
    )


def test_reslice_updates_manifest_clip_blocks(curate_bars, tmp_path: Path):
    track_dir = tmp_path / "track"
    _build_curated_track(track_dir, bpm=120.0, first_downbeat_sec=0.0, pad_bars=0.5)

    stems_json = json.loads((track_dir / "stems.json").read_text())
    stems_json["bpm"] = 100.0
    (track_dir / "stems.json").write_text(json.dumps(stems_json))

    curate_bars.reslice_curated_from_anchor(stems_dir=track_dir, json_events=False)

    mf = json.loads((track_dir / "curated" / "manifest.json").read_text())
    assert mf["bpm"] == 100.0
    new_bar_dur = 60.0 / 100.0 * 4

    for stem_block in mf["stems"].values():
        for loop in stem_block["loops"]:
            clip = loop["clip"]
            # raw region = 1 bar at 100 BPM
            assert abs((clip["raw_end_sec"] - clip["raw_start_sec"]) - new_bar_dur) < 0.01
            # padded = 2*0.5*bar + 1 bar = 2 bars at new duration
            expected_padded_end = 2.0 * new_bar_dur
            assert abs(clip["padded_end_sec"] - expected_padded_end) < 0.01
            # warp_markers' end time matches the new padded duration
            end_marker = loop["warp_markers"][-1]
            assert abs(end_marker["time_sec"] - expected_padded_end) < 0.01


def test_reslice_honors_new_first_downbeat(curate_bars, tmp_path: Path):
    """If first_downbeat shifts by N seconds, the audio inside the loop
    file shifts by N seconds in the source stem.
    """
    track_dir = tmp_path / "track"
    sr = 44100
    bpm = 120.0
    bar_duration = 60.0 / bpm * 4

    # Build a track with first_downbeat = 0
    _build_curated_track(
        track_dir,
        bpm=bpm,
        first_downbeat_sec=0.0,
        selected_bar_indices=[3],
        pad_bars=0.0,  # no pad — easier to compare exact regions
        sr=sr,
    )
    # Simulate a re-anchor that pushes first_downbeat to 0.25s.
    stems_json = json.loads((track_dir / "stems.json").read_text())
    new_first_dn = 0.25
    stems_json["tempo"]["first_downbeat_sec"] = new_first_dn
    (track_dir / "stems.json").write_text(json.dumps(stems_json))

    # Read what bar 3 of drums.wav contains BEFORE reslice (offset 0.25s into
    # the bar 3 region, since the new anchor pushes the grid forward)
    drums_wav, _ = sf.read(str(track_dir / "drums.wav"))
    # New bar 3 should start at: 0.25 + (3-1)*bar_duration = 0.25 + 2.0*2 = 4.25s
    expected_start_sample = int(round((new_first_dn + 2 * bar_duration) * sr))

    curate_bars.reslice_curated_from_anchor(stems_dir=track_dir, json_events=False)

    bar_001 = track_dir / "curated" / "drums" / "bar_001.wav"
    bar_audio, _ = sf.read(str(bar_001))
    # bar_audio should equal drums_wav at [expected_start_sample : expected_start_sample + bar_duration*sr]
    expected_end_sample = expected_start_sample + int(round(bar_duration * sr))
    expected = drums_wav[expected_start_sample:expected_end_sample]
    # Allow off-by-one frame from rounding.
    assert (
        bar_audio.shape[0] == expected.shape[0] or abs(bar_audio.shape[0] - expected.shape[0]) <= 1
    )
    n = min(bar_audio.shape[0], expected.shape[0])
    np.testing.assert_allclose(bar_audio[:n], expected[:n], atol=1e-3)


def test_reslice_does_not_touch_oneshots(curate_bars, tmp_path: Path):
    track_dir = tmp_path / "track"
    _build_curated_track(track_dir, bpm=120.0, first_downbeat_sec=0.0)

    os_path = track_dir / "curated" / "drums" / "oneshots" / "os_001.wav"
    before_bytes = os_path.read_bytes()

    stems_json = json.loads((track_dir / "stems.json").read_text())
    stems_json["bpm"] = 100.0
    (track_dir / "stems.json").write_text(json.dumps(stems_json))

    curate_bars.reslice_curated_from_anchor(stems_dir=track_dir, json_events=False)

    # File on disk must be byte-for-byte unchanged.
    assert os_path.read_bytes() == before_bytes
    # Manifest oneshots block must be unchanged.
    mf = json.loads((track_dir / "curated" / "manifest.json").read_text())
    assert len(mf["stems"]["drums"]["oneshots"]) == 1
    assert mf["stems"]["drums"]["oneshots"][0]["classification"] == "kick"


def test_reslice_preserves_user_offsets(curate_bars, tmp_path: Path):
    """User-committed offsets (from the M4L COMMIT button) survive a reslice."""
    track_dir = tmp_path / "track"
    _build_curated_track(track_dir, bpm=120.0, first_downbeat_sec=0.0)

    # Mark one loop as committed with custom offsets.
    mf = json.loads((track_dir / "curated" / "manifest.json").read_text())
    mf["stems"]["bass"]["loops"][0]["offsets"] = {
        "committed": True,
        "start_offset_sec": 0.05,
        "end_offset_sec": -0.03,
        "note": "user trim",
    }
    (track_dir / "curated" / "manifest.json").write_text(json.dumps(mf))

    stems_json = json.loads((track_dir / "stems.json").read_text())
    stems_json["bpm"] = 100.0
    (track_dir / "stems.json").write_text(json.dumps(stems_json))

    curate_bars.reslice_curated_from_anchor(stems_dir=track_dir, json_events=False)

    mf2 = json.loads((track_dir / "curated" / "manifest.json").read_text())
    offsets = mf2["stems"]["bass"]["loops"][0]["offsets"]
    assert offsets == {
        "committed": True,
        "start_offset_sec": 0.05,
        "end_offset_sec": -0.03,
        "note": "user trim",
    }


def test_reslice_errors_when_stems_json_missing(curate_bars, tmp_path: Path):
    track_dir = tmp_path / "track"
    track_dir.mkdir()
    (track_dir / "curated").mkdir()
    (track_dir / "curated" / "manifest.json").write_text("{}")

    with pytest.raises(FileNotFoundError, match="stems.json"):
        curate_bars.reslice_curated_from_anchor(stems_dir=track_dir, json_events=False)


def test_reslice_errors_when_curated_manifest_missing(curate_bars, tmp_path: Path):
    track_dir = tmp_path / "track"
    track_dir.mkdir()
    (track_dir / "stems.json").write_text(
        json.dumps({"bpm": 120, "tempo": {"first_downbeat_sec": 0}})
    )

    with pytest.raises(FileNotFoundError, match="curated/manifest.json"):
        curate_bars.reslice_curated_from_anchor(stems_dir=track_dir, json_events=False)


def test_reslice_errors_when_stems_json_has_no_bpm(curate_bars, tmp_path: Path):
    """A stems.json with no bpm field is unusable — _load_stems_manifest_tempo
    returns None and reslice raises ValueError. (Missing tempo.first_downbeat
    is OK — it falls back to 0.0.)"""
    track_dir = tmp_path / "track"
    track_dir.mkdir()
    (track_dir / "stems.json").write_text(json.dumps({"track_name": "x"}))  # no bpm
    (track_dir / "curated").mkdir()
    (track_dir / "curated" / "manifest.json").write_text(json.dumps({"stems": {}, "bpm": 120}))

    with pytest.raises(ValueError, match="no tempo block"):
        curate_bars.reslice_curated_from_anchor(stems_dir=track_dir, json_events=False)
