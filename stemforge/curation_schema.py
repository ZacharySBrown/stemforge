"""stemforge.curation_schema — Curation Stage v2 schema helpers.

Parses the top-level `curation:` block from curation.yaml (trim_pad, warp_markers,
loop, per-stem overrides) and builds the per-item v0 schema blocks (`clip`,
`warp_markers`, `loop`, `offsets`) per specs/stemforge-curation-v2-spec.md.

v0 behaviour (default; oneshots + backwards-compat callers)
-----------------------------------------------------------
- `pad_bars` is always 0.0 in emitted manifest even if YAML requests padding.
- `padded_*` == `raw_*` (i.e. the wav file boundaries).
- `warp_markers` are stubs: a `start` at time 0 / beat 0 and an `end` at
  `(duration_sec, beat_pos_end)`.
- `offsets.committed = false`, offsets zeroed.

v1 behaviour (loops, when caller passes `pad_bars_applied` + friends)
--------------------------------------------------------------------
- Caller has re-sliced the source stem with `pad_bars` of context on each side.
- The padded WAV runs `[0, padded_end_sec]`; the exact-bar window inside it
  is `[raw_start_sec, raw_end_sec]` with `raw_start_sec > 0`.
- Loop block locks `loop_start_sec`/`loop_end_sec` to the exact-bar window so
  Ableton's loop points sit on-grid even while the file has pre-roll context.
- Warp markers still emit only a `start`/`end` pair — v1 trusts the caller
  to have time-aligned the padded region. Future v1.x will detect transients
  inside the padded file and emit intermediate markers.

Offsets.committed remains false until M4L commits a user trim back.
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
    *,
    pad_bars_applied: float | None = None,
    bar_duration_sec: float | None = None,
    ts_num: int | None = None,
    loop_mode: str | None = None,
    raw_start_sec: float | None = None,
) -> dict[str, Any]:
    """Build the `clip` / `warp_markers` / `loop` / `offsets` blocks for a
    single loop or oneshot WAV.

    Two modes are supported via the keyword-only v1 params:

    **v0 stub (default)** — when `pad_bars_applied` is None:
      - `pad_bars = 0.0`, `padded_* == raw_*` (file boundaries).
      - Warp markers are a `start`/`end` pair across the whole file.
      - Backwards-compat with oneshots and any caller that hasn't adopted v1.

    **v1 padded (loops)** — when `pad_bars_applied` is provided:
      The caller has already re-sliced the source stem to include
      `pad_bars` bars of context on each side of the exact-bar window. The
      padded WAV file runs `[0, padded_end_sec]`. Inside that file, the
      original bar content starts at `raw_start_sec` and ends at
      `raw_start_sec + bar_duration_sec * phrase_bars`.

    Args:
      wav_path: Path to the curated WAV on disk (padded in v1, exact-bar in v0).
      phrase_bars: Nominal bar count for loops (1, 2, 4…). For oneshots pass None.
      time_sig_numerator: Beats-per-bar (usually 4). Used only when ts_num omitted.
      stem_schema: Per-stem schema config — drives loop_enabled + default loop_mode.
      bpm: Track BPM. Used for oneshot beat_pos_end derivation.
      pad_bars_applied: v1 — actual pad bars applied (symmetric min after
        clamping at source edges). When None, v0 stub path is used.
      bar_duration_sec: v1 — one-bar duration derived from bpm + time signature.
      ts_num: v1 — explicit beats-per-bar (falls back to time_sig_numerator).
      loop_mode: v1 — optional loop_mode override (falls back to stem_schema).
      raw_start_sec: v1 — where the exact-bar window starts inside the padded
        file. Normally equals `pad_bars_applied * bar_duration_sec`, but the
        caller may pass a clamped value near stem edges.

    Returns a dict with keys: clip, warp_markers, loop, offsets.
    """
    duration = _wav_duration_sec(wav_path)

    # ── v0 stub path ────────────────────────────────────────────────────
    if pad_bars_applied is None:
        if phrase_bars is not None and phrase_bars > 0:
            beat_pos_end = float(phrase_bars) * float(time_sig_numerator)
        elif bpm and bpm > 0 and duration > 0:
            beat_pos_end = (duration * float(bpm)) / 60.0
        else:
            beat_pos_end = 0.0

        clip = {
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
            "loop_mode": loop_mode if loop_mode is not None else stem_schema.loop_mode,
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

    # ── v1 padded path ──────────────────────────────────────────────────
    beats_per_bar = int(ts_num if ts_num is not None else time_sig_numerator)
    pb = float(phrase_bars) if phrase_bars else 1.0
    bd = float(bar_duration_sec) if bar_duration_sec and bar_duration_sec > 0 else 0.0
    pad = float(pad_bars_applied)

    # raw_start_sec defaults to pad * bar_duration but caller may override
    # for edge-clamped bars.
    r_start = float(raw_start_sec) if raw_start_sec is not None else pad * bd
    r_end = r_start + pb * bd
    padded_end = duration  # padded WAV runs [0, duration]

    clip = {
        "raw_start_sec": r_start,
        "raw_end_sec": r_end,
        "padded_start_sec": 0.0,
        "padded_end_sec": padded_end,
        "pad_bars": pad,
        "wide_window": bool(pad > 0.5),
    }

    # Warp-marker beat_pos at file end: the padded WAV spans the equivalent
    # of (pad_bars + phrase_bars + pad_bars) bars. If either side was clamped
    # (file shorter than nominal), scale proportionally via duration ratio so
    # the grid still aligns to what's actually in the file.
    nominal_span_bars = 2.0 * pad + pb
    nominal_duration = nominal_span_bars * bd
    if nominal_duration > 0 and abs(padded_end - nominal_duration) / nominal_duration > 0.01:
        # Clamped — rescale beat_pos_end by actual/nominal ratio.
        span_bars = nominal_span_bars * (padded_end / nominal_duration)
    else:
        span_bars = nominal_span_bars
    beat_pos_end = span_bars * beats_per_bar

    warp_markers = [
        {"time_sec": 0.0, "beat_pos": 0.0, "type": "start"},
        {"time_sec": padded_end, "beat_pos": beat_pos_end, "type": "end"},
    ]

    loop = {
        "enabled": bool(stem_schema.loop_enabled),
        "loop_start_sec": r_start,
        "loop_end_sec": r_end,
        "loop_mode": loop_mode if loop_mode is not None else stem_schema.loop_mode,
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
