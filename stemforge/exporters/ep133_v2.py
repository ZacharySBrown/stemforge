"""
stemforge.exporters.ep133_v2 — Manifest-driven EP-133 export pipeline.

Reads a curated manifest (Curation Stage v2 schema) and produces:

1. Per-stem WAVs formatted for EP Sample Tool (46,875 Hz / 16-bit stereo)
2. An ``ep133`` sub-object appended to each loop's manifest entry
3. A ``SETUP.md`` with pad assignment map + BPM sync instructions

Distinct from ``stemforge.exporters.ep133`` (which drives SysEx uploads to the
hardware via EP Sample Tool's USB-MIDI protocol). This module stops at
producing the files EP Sample Tool would import — the hardware push is a
separate concern.

Spec: ``specs/stemforge-ep133-export-spec.md``
"""

from __future__ import annotations

import copy
import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import librosa
import numpy as np
import soundfile as sf
import yaml


# EP-133 EP Sample Tool target audio format. These are fixed by the spec.
EP133_SAMPLE_RATE = 46875
EP133_BIT_DEPTH = 16
EP133_CHANNELS = "stereo"

# Mute group ceiling from hardware: 8 groups + 0 ("no group").
EP133_MAX_MUTE_GROUPS = 8


# ── Config defaults (spec Section 4) ────────────────────────────────────────

DEFAULT_EP133_CONFIG: dict[str, Any] = {
    "enabled": True,
    "sync": {"mode": "midi_clock", "master": "ableton"},
    "defaults": {
        "play_mode": "key",
        "loop": False,
        "mute_group": 0,
        "time_stretch": {"mode": "bpm", "source_bpm": None},
    },
    "stems": {
        "drums": {
            "play_mode": "oneshot",
            "loop": True,
            "mute_group": 0,
            "time_stretch": {"mode": "bar", "bars": 4},
        },
        "bass": {
            "play_mode": "oneshot",
            "loop": True,
            "mute_group": 1,
            "time_stretch": {"mode": "bpm", "source_bpm": None},
        },
        "vocals": {
            "play_mode": "key",
            "loop": False,
            "mute_group": 2,
            "time_stretch": {"mode": "bpm", "source_bpm": None},
        },
        "other": {
            "play_mode": "legato",
            "loop": False,
            "mute_group": 0,
            "time_stretch": {"mode": "bpm", "source_bpm": None},
        },
    },
    "pad_map": {
        "drums": {"group": "A", "pad": 1},
        "bass": {"group": "A", "pad": 2},
        "vocals": {"group": "A", "pad": 3},
        "other": {"group": "A", "pad": 4},
    },
}


@dataclass
class _PadRow:
    """One row of the SETUP.md pad table."""
    group: str
    pad: int
    filename: str
    play_mode: str
    loop: bool
    mute_group: int
    time_stretch: str
    stem: str
    position: int


@dataclass
class _ExportReport:
    loops_exported: int = 0
    loops_skipped: int = 0
    pad_rows: list[_PadRow] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


# ── Config loading ──────────────────────────────────────────────────────────


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override into a copy of base. override wins on leaves."""
    out = copy.deepcopy(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def load_ep133_config(config_path: Path | None) -> dict[str, Any]:
    """Load the ``ep133_export`` block from a curation YAML.

    Missing file or missing block falls back to ``DEFAULT_EP133_CONFIG``.
    Per-block values merge over the defaults, so the YAML only needs to
    specify overrides.
    """
    if config_path is None or not Path(config_path).exists():
        return copy.deepcopy(DEFAULT_EP133_CONFIG)
    data = yaml.safe_load(Path(config_path).read_text()) or {}
    user_block = data.get("ep133_export") or {}
    return _deep_merge(DEFAULT_EP133_CONFIG, user_block)


def _stem_config(cfg: dict[str, Any], stem: str) -> dict[str, Any]:
    """Resolve the effective per-stem config (defaults + per-stem override)."""
    merged = _deep_merge(cfg["defaults"], cfg["stems"].get(stem, {}))
    return merged


# ── Manifest helpers ────────────────────────────────────────────────────────


def _iter_loops(stem_entry: Any) -> list[dict[str, Any]]:
    """Yield loop entries for a stem.

    Handles both shapes produced by ``stemforge_curate_bars``:
      - drums: ``{"loops": [...], "oneshots": [...]}``
      - others: ``[...]``
    """
    if isinstance(stem_entry, dict):
        loops = stem_entry.get("loops") or []
        if isinstance(loops, list):
            return loops
        return []
    if isinstance(stem_entry, list):
        return stem_entry
    return []


def _loop_file_path(loop: dict[str, Any], manifest_dir: Path) -> Path:
    """Resolve a loop's ``file`` to an absolute Path."""
    raw = loop["file"]
    p = Path(raw)
    if not p.is_absolute():
        p = (manifest_dir / p).resolve()
    return p


def _resolve_boundaries(
    loop: dict[str, Any],
    total_duration_sec: float,
) -> tuple[float, float, bool]:
    """Return (export_start, export_end, used_clip_block).

    v0/v1: if a ``clip`` block exists, use
    ``padded_start_sec + offsets.start_offset_sec`` — likewise for end.
    Otherwise (legacy pre-v2 manifests) use the whole file.
    """
    clip = loop.get("clip")
    offsets = loop.get("offsets") or {}
    if clip and "padded_start_sec" in clip and "padded_end_sec" in clip:
        start = float(clip["padded_start_sec"]) + float(offsets.get("start_offset_sec", 0.0))
        end = float(clip["padded_end_sec"]) + float(offsets.get("end_offset_sec", 0.0))
        # Clamp to legal range.
        start = max(0.0, start)
        end = min(total_duration_sec, end)
        if end <= start:
            # Degenerate; fall back to whole file.
            return 0.0, total_duration_sec, False
        return start, end, True
    return 0.0, total_duration_sec, False


# ── Audio pipeline ──────────────────────────────────────────────────────────


def _slice_and_format(
    src_path: Path,
    start_sec: float,
    end_sec: float,
) -> tuple[np.ndarray, float]:
    """Load → slice → resample to 46,875 Hz → normalize (if peak > -1 dBFS).

    Returns (audio_stereo_T_channels, duration_sec). Caller writes the WAV.
    """
    # Read entire file then slice — simpler than seeking and avoids frame-count
    # edge cases with soundfile's ``start``/``stop`` at non-integer positions.
    audio, sr = sf.read(str(src_path), always_2d=True)
    # audio shape: (samples, channels)

    total_dur = audio.shape[0] / sr
    # Caller already clamped, but be defensive.
    s_frame = max(0, int(round(start_sec * sr)))
    e_frame = min(audio.shape[0], int(round(end_sec * sr)))
    if e_frame <= s_frame:
        raise ValueError(
            f"Empty slice for {src_path.name}: start={start_sec}s end={end_sec}s "
            f"total={total_dur:.3f}s"
        )
    audio = audio[s_frame:e_frame]

    # To (channels, samples) for resample, then stereo.
    audio_ch = audio.T
    if audio_ch.ndim == 1:
        audio_ch = np.stack([audio_ch, audio_ch])
    elif audio_ch.shape[0] == 1:
        audio_ch = np.stack([audio_ch[0], audio_ch[0]])
    elif audio_ch.shape[0] > 2:
        audio_ch = audio_ch[:2]

    # Resample channels independently via librosa. librosa expects float.
    audio_ch = audio_ch.astype(np.float32, copy=False)
    if sr != EP133_SAMPLE_RATE:
        resampled = np.stack([
            librosa.resample(audio_ch[c], orig_sr=sr, target_sr=EP133_SAMPLE_RATE)
            for c in range(audio_ch.shape[0])
        ])
    else:
        resampled = audio_ch

    # Peak-normalize only if over -1 dBFS. Target ceiling = 10 ** (-1/20).
    peak = float(np.max(np.abs(resampled))) if resampled.size else 0.0
    ceiling = 10 ** (-1.0 / 20)  # ≈ 0.8913
    if peak > ceiling and peak > 0:
        resampled = resampled * (ceiling / peak)

    # Back to (samples, channels) for soundfile.
    out = resampled.T
    duration_sec = out.shape[0] / EP133_SAMPLE_RATE
    return out, duration_sec


def _write_wav_16bit(audio: np.ndarray, path: Path) -> None:
    """Write 16-bit PCM stereo WAV. ``audio`` is (samples, channels), float."""
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(path), audio, EP133_SAMPLE_RATE, subtype="PCM_16")


# ── Metadata (ep133 block) ──────────────────────────────────────────────────


def _build_ep133_block(
    stem: str,
    stem_cfg: dict[str, Any],
    pad_assignment: dict[str, int | str],
    filename: str,
    duration_sec: float,
    export_start: float,
    export_end: float,
    source_bpm: float | None,
) -> dict[str, Any]:
    """Assemble the ``ep133`` sub-object for a manifest entry."""
    ts_cfg = copy.deepcopy(stem_cfg.get("time_stretch") or {})
    # source_bpm: if null in config, pull from the manifest.
    if ts_cfg.get("source_bpm") in (None, "null") and source_bpm is not None:
        ts_cfg["source_bpm"] = float(source_bpm)
    # Keep schema predictable — always emit the four potential keys.
    ts_out: dict[str, Any] = {
        "mode": ts_cfg.get("mode", "none"),
        "source_bpm": ts_cfg.get("source_bpm"),
        "bars": ts_cfg.get("bars"),
    }

    return {
        "play_mode": stem_cfg.get("play_mode", "key"),
        "loop": bool(stem_cfg.get("loop", False)),
        "mute_group": int(stem_cfg.get("mute_group", 0)),
        "time_stretch": ts_out,
        "pad": {"group": pad_assignment["group"], "pad": int(pad_assignment["pad"])},
        "audio": {
            "filename": filename,
            "sample_rate": EP133_SAMPLE_RATE,
            "bit_depth": EP133_BIT_DEPTH,
            "channels": EP133_CHANNELS,
            "duration_sec": round(duration_sec, 4),
            "export_start_sec": round(export_start, 4),
            "export_end_sec": round(export_end, 4),
        },
    }


# ── Validation ──────────────────────────────────────────────────────────────


def _validate_mute_groups(cfg: dict[str, Any]) -> list[str]:
    """Spec Section 12 open question 4: enforce EP-133's 8-group ceiling.

    Counts distinct non-zero mute_group values across stem configs. Returns a
    list of warnings/errors; emptiness means all clear.
    """
    groups: set[int] = set()
    for stem_name, stem_over in cfg.get("stems", {}).items():
        merged = _deep_merge(cfg["defaults"], stem_over)
        g = int(merged.get("mute_group", 0) or 0)
        if g != 0:
            groups.add(g)
    if len(groups) > EP133_MAX_MUTE_GROUPS:
        return [
            f"ep133_export: {len(groups)} distinct non-zero mute groups "
            f"defined ({sorted(groups)}), exceeds EP-133 maximum of "
            f"{EP133_MAX_MUTE_GROUPS}. Clamp or consolidate."
        ]
    return []


# ── SETUP.md generation (spec Section 10) ───────────────────────────────────


def _render_setup_md(
    song_name: str,
    project_bpm: float | None,
    rows: list[_PadRow],
    cfg: dict[str, Any],
) -> str:
    bpm_str = f"{project_bpm:.1f}" if project_bpm is not None else "(set from Ableton)"

    sync_cfg = cfg.get("sync") or {}
    sync_mode = sync_cfg.get("mode", "midi_clock")
    master = sync_cfg.get("master", "ableton")

    # Pad table. Empty mute_group rendered as em-dash (spec example uses '—').
    table_lines = [
        "| Pad | Group | File | Play Mode | Loop | Mute Group | Time Stretch |",
        "|-----|-------|------|-----------|------|------------|--------------|",
    ]
    for r in sorted(rows, key=lambda x: (x.group, x.pad, x.position)):
        mg = "—" if r.mute_group == 0 else str(r.mute_group)
        loop_str = "yes" if r.loop else "no"
        table_lines.append(
            f"| {r.pad} | {r.group} | {r.filename} | {r.play_mode} | "
            f"{loop_str} | {mg} | {r.time_stretch} |"
        )
    table = "\n".join(table_lines)

    return f"""# EP-133 Setup — {song_name}

## BPM Sync
1. Connect EP-133 to Mac via USB-C
2. EP-133: SHIFT+ERASE → System Settings → MIDI → Clock → On
3. Ableton: set MIDI output to EP-133, enable Clock (master: {master}, mode: {sync_mode})

Project BPM: {bpm_str}

## Import Samples (EP Sample Tool)
Open EP Sample Tool and import the files in this directory in the order below.

{table}

## On-Device Sound Edit (per pad)
After import, for each pad:
  SHIFT + SOUND → navigate with +/- to:
  - Sound: set Play Mode (oneshot / key / legato)
  - Time: set BPM or BAR + value
  - Mute Group: set group number (1–8, 0 = no group)
  - Trim: fine-adjust start point if needed (knobX = start, knobY = length)

## Sticky Loop Upgrade (Optional — Drums)
The EP-133 has no native latching toggle pad mode. To get a true on/off toggle
for drums:

  1. Program `drums_*_ep133.wav` as a looping sequencer pattern
  2. Assign a free pad to start/stop that pattern
  3. This replaces `oneshot + loop` with a pattern trigger

See specs/stemforge-ep133-export-spec.md Section 9 for details.

---
Generated by `stemforge export --target ep133 --manifest ...`
"""


# ── Top-level entry point ───────────────────────────────────────────────────


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    """Write JSON to ``path`` atomically (tmp in same dir → rename)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=path.name + ".", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump(data, fh, indent=2)
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def export_from_manifest(
    manifest_path: Path,
    config_path: Path | None,
    out_dir: Path,
) -> Path:
    """Export every loop in a curated manifest to EP Sample Tool format.

    Args:
        manifest_path: Path to ``curated/manifest.json`` (written by
            ``stemforge_curate_bars``).
        config_path: Path to a curation YAML that may contain an
            ``ep133_export`` block. ``None`` uses built-in defaults.
        out_dir: Where per-song artifacts land. A sub-folder
            ``out_dir/<song_name>/`` is created containing the WAVs and
            ``SETUP.md``.

    Returns:
        Path to the per-song output directory.

    Side effects:
        Mutates ``manifest_path`` on disk — each loop gets an ``ep133`` block.
    """
    manifest_path = Path(manifest_path).resolve()
    out_dir = Path(out_dir).resolve()

    if not manifest_path.exists():
        raise FileNotFoundError(f"manifest not found: {manifest_path}")

    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise OSError(f"Cannot create output dir {out_dir}: {e}") from e

    manifest = json.loads(manifest_path.read_text())
    manifest_dir = manifest_path.parent

    cfg = load_ep133_config(config_path)
    errors = _validate_mute_groups(cfg)
    if errors:
        # Fail hard — spec calls this out as an error, not a warning.
        raise ValueError("\n".join(errors))

    song_name = manifest.get("track") or manifest_path.parent.parent.name
    project_bpm = manifest.get("bpm")

    song_out = out_dir / song_name
    song_out.mkdir(parents=True, exist_ok=True)

    report = _ExportReport()

    stems = manifest.get("stems", {})
    for stem_name, stem_entry in stems.items():
        stem_cfg = _stem_config(cfg, stem_name)
        pad_assignment = cfg["pad_map"].get(stem_name)
        if pad_assignment is None:
            report.warnings.append(
                f"no pad_map entry for stem '{stem_name}' — skipping"
            )
            continue

        loops = _iter_loops(stem_entry)
        for loop in loops:
            try:
                src = _loop_file_path(loop, manifest_dir)
            except KeyError:
                report.loops_skipped += 1
                report.warnings.append(
                    f"{stem_name} position={loop.get('position','?')}: missing 'file' key"
                )
                continue

            if not src.exists():
                report.loops_skipped += 1
                report.warnings.append(f"{stem_name}: source file missing: {src}")
                continue

            # Boundary resolution per spec Section 5.
            info = sf.info(str(src))
            total_dur = info.frames / info.samplerate
            export_start, export_end, _used_clip = _resolve_boundaries(loop, total_dur)

            # Slice + format.
            audio, duration_sec = _slice_and_format(src, export_start, export_end)

            # Filename: spec shows `<stem>_ep133.wav` but manifests carry 16
            # loops per stem, so we include the position index to disambiguate.
            position = int(loop.get("position", 0))
            filename = f"{stem_name}_{position:02d}_ep133.wav"
            out_wav = song_out / filename
            _write_wav_16bit(audio, out_wav)

            ep133_block = _build_ep133_block(
                stem=stem_name,
                stem_cfg=stem_cfg,
                pad_assignment=pad_assignment,
                filename=filename,
                duration_sec=duration_sec,
                export_start=export_start,
                export_end=export_end,
                source_bpm=project_bpm,
            )
            loop["ep133"] = ep133_block
            report.loops_exported += 1

            # SETUP.md row
            ts_desc = _describe_time_stretch(ep133_block["time_stretch"], project_bpm)
            report.pad_rows.append(_PadRow(
                group=str(pad_assignment["group"]),
                pad=int(pad_assignment["pad"]),
                filename=filename,
                play_mode=ep133_block["play_mode"],
                loop=ep133_block["loop"],
                mute_group=ep133_block["mute_group"],
                time_stretch=ts_desc,
                stem=stem_name,
                position=position,
            ))

    # Write mutated manifest back atomically.
    _atomic_write_json(manifest_path, manifest)

    # SETUP.md
    setup = _render_setup_md(song_name, project_bpm, report.pad_rows, cfg)
    (song_out / "SETUP.md").write_text(setup)

    # Leave a brief report sidecar for callers that want it (not in spec but
    # cheap and useful).
    report_dict = {
        "song": song_name,
        "out_dir": str(song_out),
        "loops_exported": report.loops_exported,
        "loops_skipped": report.loops_skipped,
        "warnings": report.warnings,
    }
    (song_out / "_ep133_export_report.json").write_text(
        json.dumps(report_dict, indent=2)
    )

    return song_out


def _describe_time_stretch(ts: dict[str, Any], project_bpm: float | None) -> str:
    """One-cell description for the SETUP.md table."""
    mode = ts.get("mode", "none")
    if mode == "bar":
        bars = ts.get("bars")
        return f"BAR {bars}" if bars is not None else "BAR"
    if mode == "bpm":
        src = ts.get("source_bpm") or project_bpm
        return f"BPM {src:.1f}" if isinstance(src, (int, float)) else "BPM"
    return "none"
