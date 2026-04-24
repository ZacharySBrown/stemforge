"""stemforge.curation_schema — Curation Stage v2 schema helpers.

Parses the top-level `curation:` block from curation.yaml (trim_pad, warp_markers,
loop, per-stem overrides) and builds the per-item v0 schema blocks (`clip`,
`warp_markers`, `loop`, `offsets`) per specs/stemforge-curation-v2-spec.md.

v0 behaviour
------------
- `pad_bars` is always 0.0 in emitted manifest even if YAML requests padding.
- `padded_*` == `raw_*` (i.e. the wav file boundaries).
- `warp_markers` are stubs: a `start` at time 0 / beat 0 and an `end` at
  `(duration_sec, beat_pos_end)`.
- `offsets.committed = false`, offsets zeroed.

v1 will honour `pad_bars`, detect transients/downbeats, and let M4L commit
offsets back. The schema is identical — v1 just populates more of it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import soundfile as sf
import yaml


# ── Config dataclasses ──────────────────────────────────────────────────

@dataclass
class TrimPadConfig:
    default_bars: float = 0.5
    unit: str = "bars"  # "bars" | "beats" | "seconds"


@dataclass
class WarpMarkerConfig:
    enabled: bool = True
    mode: str = "auto"         # "auto" | "manual_only"
    auto_snap: str = "transient"  # "transient" | "downbeat" | "none"


@dataclass
class LoopConfig:
    enabled: bool = True
    loop_mode: str = "none"  # "none" | "loop" | "ping_pong"


@dataclass
class StemCurationSchemaConfig:
    """Per-stem curation-schema overrides (distinct from StemCurationConfig in
    stemforge.config which governs selection, not padding/warp)."""
    pad_bars: float = 0.5
    auto_snap: str = "transient"
    loop_enabled: bool = True
    loop_mode: str = "none"


@dataclass
class CurationSchemaConfig:
    """Parsed top-level `curation:` block. Source-of-truth for Stage v2 padding,
    warp-marker detection, and loop semantics."""
    trim_pad: TrimPadConfig = field(default_factory=TrimPadConfig)
    warp_markers: WarpMarkerConfig = field(default_factory=WarpMarkerConfig)
    loop: LoopConfig = field(default_factory=LoopConfig)
    stems: dict[str, StemCurationSchemaConfig] = field(default_factory=dict)

    def for_stem(self, stem_name: str) -> StemCurationSchemaConfig:
        """Return per-stem schema config, falling back to globals."""
        if stem_name in self.stems:
            return self.stems[stem_name]
        return StemCurationSchemaConfig(
            pad_bars=self.trim_pad.default_bars,
            auto_snap=self.warp_markers.auto_snap,
            loop_enabled=self.loop.enabled,
            loop_mode=self.loop.loop_mode,
        )


# ── Loader ──────────────────────────────────────────────────────────────

def load_curation_schema_config(path: str | Path | None) -> CurationSchemaConfig:
    """Load the top-level `curation:` block from curation.yaml.

    Missing file or missing block → all defaults per spec §2.
    """
    if path is None:
        return CurationSchemaConfig()
    p = Path(path)
    if not p.exists():
        return CurationSchemaConfig()

    raw = yaml.safe_load(p.read_text()) or {}
    cur = raw.get("curation")
    if not isinstance(cur, dict):
        return CurationSchemaConfig()

    tp_raw = cur.get("trim_pad") or {}
    trim_pad = TrimPadConfig(
        default_bars=float(tp_raw.get("default_bars", 0.5)),
        unit=str(tp_raw.get("unit", "bars")),
    )

    wm_raw = cur.get("warp_markers") or {}
    warp_markers = WarpMarkerConfig(
        enabled=bool(wm_raw.get("enabled", True)),
        mode=str(wm_raw.get("mode", "auto")),
        auto_snap=str(wm_raw.get("auto_snap", "transient")),
    )

    loop_raw = cur.get("loop") or {}
    loop = LoopConfig(
        enabled=bool(loop_raw.get("enabled", True)),
        loop_mode=str(loop_raw.get("loop_mode", "none")),
    )

    stems: dict[str, StemCurationSchemaConfig] = {}
    for stem_name, stem_raw in (cur.get("stems") or {}).items():
        stem_raw = stem_raw or {}
        stem_tp = (stem_raw.get("trim_pad") or {})
        stem_wm = (stem_raw.get("warp_markers") or {})
        stem_loop = (stem_raw.get("loop") or {})
        stems[stem_name] = StemCurationSchemaConfig(
            pad_bars=float(stem_tp.get("bars", trim_pad.default_bars)),
            auto_snap=str(stem_wm.get("auto_snap", warp_markers.auto_snap)),
            loop_enabled=bool(stem_loop.get("enabled", loop.enabled)),
            loop_mode=str(stem_loop.get("loop_mode", loop.loop_mode)),
        )

    return CurationSchemaConfig(
        trim_pad=trim_pad,
        warp_markers=warp_markers,
        loop=loop,
        stems=stems,
    )


# ── v0 schema block builder ─────────────────────────────────────────────

def _wav_duration_sec(wav_path: Path) -> float:
    """Read WAV duration cheaply via soundfile header. Returns 0.0 on failure."""
    try:
        return float(sf.info(str(wav_path)).duration)
    except Exception:
        return 0.0


def build_curation_block(
    wav_path: Path,
    phrase_bars: float | None,
    time_sig_numerator: int,
    stem_schema: StemCurationSchemaConfig,
    bpm: float | None = None,
) -> dict[str, Any]:
    """Build the v0 `clip` / `warp_markers` / `loop` / `offsets` blocks for
    a single loop or oneshot WAV.

    - `phrase_bars` is the nominal bar count for loops (e.g. 1, 2, 4). For
      oneshots pass `None` — we derive `beat_pos_end` from duration and bpm.
    - `time_sig_numerator` is beats-per-bar (usually 4).
    - v0 emits `pad_bars = 0.0` regardless of `stem_schema.pad_bars`.

    Returns a dict with keys: clip, warp_markers, loop, offsets.
    """
    duration = _wav_duration_sec(wav_path)

    # Derive beat_pos_end. For loops this is phrase_bars * beats_per_bar (clean,
    # independent of BPM). For oneshots we convert via BPM; if BPM is missing
    # we fall back to 0.0 for beat_pos_end (still a valid stub — v1 will
    # rebuild markers anyway).
    if phrase_bars is not None and phrase_bars > 0:
        beat_pos_end = float(phrase_bars) * float(time_sig_numerator)
    elif bpm and bpm > 0 and duration > 0:
        beat_pos_end = (duration * float(bpm)) / 60.0
    else:
        beat_pos_end = 0.0

    clip = {
        # v0: raw == padded, no padding applied
        "raw_start_sec": 0.0,
        "raw_end_sec": duration,
        "padded_start_sec": 0.0,
        "padded_end_sec": duration,
        "pad_bars": 0.0,
        "wide_window": False,
    }

    warp_markers = [
        {"time_sec": 0.0, "beat_pos": 0.0, "type": "start"},
        {"time_sec": duration, "beat_pos": beat_pos_end, "type": "end"},
    ]

    loop = {
        "enabled": bool(stem_schema.loop_enabled),
        "loop_start_sec": 0.0,
        "loop_end_sec": duration,
        "loop_mode": stem_schema.loop_mode,
    }

    offsets = {
        "committed": False,
        "start_offset_sec": 0.0,
        "end_offset_sec": 0.0,
        "note": "",
    }

    return {
        "clip": clip,
        "warp_markers": warp_markers,
        "loop": loop,
        "offsets": offsets,
    }
