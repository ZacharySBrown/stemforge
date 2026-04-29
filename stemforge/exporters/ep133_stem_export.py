"""
stemforge.exporters.ep133_stem_export — EP-133 stem export pipeline.

Reads stems.json, processes each stem WAV (mono, 46875 Hz, 16-bit),
and writes an EP-133-ready package: re-formatted WAVs + SETUP.md.

Key facts (krate-confirmed, NOT spec guesses):
- sound.mutegroup is a bool in device JSON (false/true), not an int 1-8.
- midi.channel is present in pad metadata (int 0-15).
- loop is set via TNGE chunk embedded in the WAV on upload — SysEx path TBD.
  We record loop intent in config/manifest but skip the SysEx SET for now.
- Time stretch non-off modes need a live trace. Fields added but skipped in
  SysEx auto-path.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf

EP133_SAMPLE_RATE = 46875
EP133_BIT_DEPTH = 16

_VALID_PLAY_MODES = frozenset({"oneshot", "key", "legato"})
_VALID_TIME_MODES = frozenset({"bpm", "bar", "none"})
_VALID_SYNC_MODES = frozenset({"midi_clock", "sync24", "usb_midi"})
_MAX_MUTE_GROUPS = 8


# ──────────────────────────────────────────────────────────────────────────────
# Config dataclasses
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class EP133TimeStretchConfig:
    """Time-stretch parameters for a single pad.

    mode: "bpm" | "bar" | "none"
    source_bpm: BPM of the source audio (auto-read from manifest when None)
    bars: number of bars for mode="bar"

    NOTE: Non-"none" modes are unconfirmed in SysEx. Fields are recorded in
    the manifest and SETUP.md but are NOT written via SysEx auto-path.
    """

    mode: str = "none"
    source_bpm: float | None = None
    bars: int | None = None  # for mode="bar"

    def __post_init__(self) -> None:
        if self.mode not in _VALID_TIME_MODES:
            raise ValueError(
                f"time_stretch.mode {self.mode!r} must be one of {sorted(_VALID_TIME_MODES)}"
            )

    @classmethod
    def from_dict(cls, d: dict) -> EP133TimeStretchConfig:
        return cls(
            mode=d.get("mode", "none"),
            source_bpm=d.get("source_bpm"),
            bars=d.get("bars"),
        )

    def to_dict(self) -> dict:
        d: dict = {"mode": self.mode}
        if self.source_bpm is not None:
            d["source_bpm"] = self.source_bpm
        if self.bars is not None:
            d["bars"] = self.bars
        return d


@dataclass
class EP133StemConfig:
    """Per-stem export configuration.

    mute_group: 0 = no choke, 1–8 = choke group.
      Device JSON field is bool (True if group ≥ 1), but we track the group
      number here for SETUP.md display.
    loop: Intent recorded in config + SETUP.md. SysEx path TBD (TNGE chunk).
    pad_group / pad_num: Pad assignment on the device.
    """

    play_mode: str = "oneshot"
    loop: bool = False
    mute_group: int = 0
    time_stretch: EP133TimeStretchConfig = field(
        default_factory=EP133TimeStretchConfig
    )
    pad_group: str = "A"
    pad_num: int = 1

    def __post_init__(self) -> None:
        if self.play_mode not in _VALID_PLAY_MODES:
            raise ValueError(
                f"play_mode {self.play_mode!r} must be one of {sorted(_VALID_PLAY_MODES)}"
            )
        if not (0 <= self.mute_group <= _MAX_MUTE_GROUPS):
            raise ValueError(
                f"mute_group {self.mute_group} must be 0..{_MAX_MUTE_GROUPS}"
            )
        if self.pad_group not in "ABCD":
            raise ValueError(f"pad_group {self.pad_group!r} must be A|B|C|D")
        if not (1 <= self.pad_num <= 12):
            raise ValueError(f"pad_num {self.pad_num} must be 1..12")

    @classmethod
    def from_dict(cls, d: dict, defaults: dict | None = None) -> EP133StemConfig:
        """Build from a stem YAML dict, merging with optional defaults."""
        merged = dict(defaults or {})
        merged.update(d)

        # Handle nested time_stretch
        ts_raw = merged.get("time_stretch", {})
        ts = EP133TimeStretchConfig.from_dict(ts_raw if isinstance(ts_raw, dict) else {})

        # Handle nested pad_map (flattened at caller site into pad_group/pad_num)
        return cls(
            play_mode=merged.get("play_mode", "oneshot"),
            loop=bool(merged.get("loop", False)),
            mute_group=int(merged.get("mute_group", 0)),
            time_stretch=ts,
            pad_group=str(merged.get("pad_group", "A")),
            pad_num=int(merged.get("pad_num", 1)),
        )


@dataclass
class EP133ExportConfig:
    """Top-level EP-133 export configuration.

    Parsed from the `ep133_export:` key in a pipeline YAML file.
    """

    enabled: bool = True
    sync_mode: str = "midi_clock"
    stems: dict[str, EP133StemConfig] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.sync_mode not in _VALID_SYNC_MODES:
            raise ValueError(
                f"sync_mode {self.sync_mode!r} must be one of {sorted(_VALID_SYNC_MODES)}"
            )

    @classmethod
    def from_pipeline_dict(cls, d: dict) -> EP133ExportConfig:
        """Parse from the `ep133_export` top-level dict in a pipeline YAML."""
        ep = d.get("ep133_export", d)  # accept either full file or sub-key

        enabled = bool(ep.get("enabled", True))
        sync_mode = ep.get("sync", {}).get("mode", "midi_clock")

        defaults_raw = ep.get("defaults", {})
        pad_map_raw = ep.get("pad_map", {})
        stems_raw = ep.get("stems", {})

        stems: dict[str, EP133StemConfig] = {}
        for stem_name, stem_dict in stems_raw.items():
            merged = dict(defaults_raw)
            merged.update(stem_dict or {})

            # Inject pad_group / pad_num from pad_map if present
            if stem_name in pad_map_raw:
                pm = pad_map_raw[stem_name]
                merged["pad_group"] = pm.get("group", "A")
                merged["pad_num"] = pm.get("pad", 1)

            stems[stem_name] = EP133StemConfig.from_dict(merged)

        return cls(enabled=enabled, sync_mode=sync_mode, stems=stems)

    @classmethod
    def default(cls) -> EP133ExportConfig:
        """Factory defaults per spec Section 3 mode mapping."""
        stems = {
            "drums": EP133StemConfig(
                play_mode="oneshot",
                loop=True,
                mute_group=0,
                time_stretch=EP133TimeStretchConfig(mode="bar", bars=4),
                pad_group="A",
                pad_num=1,
            ),
            "bass": EP133StemConfig(
                play_mode="oneshot",
                loop=True,
                mute_group=1,
                time_stretch=EP133TimeStretchConfig(mode="bpm"),
                pad_group="B",
                pad_num=1,
            ),
            "vocals": EP133StemConfig(
                play_mode="key",
                loop=False,
                mute_group=2,
                time_stretch=EP133TimeStretchConfig(mode="bpm"),
                pad_group="C",
                pad_num=1,
            ),
            "other": EP133StemConfig(
                play_mode="legato",
                loop=False,
                mute_group=0,
                time_stretch=EP133TimeStretchConfig(mode="bpm"),
                pad_group="D",
                pad_num=1,
            ),
        }
        return cls(enabled=True, sync_mode="midi_clock", stems=stems)

    def stem_config(self, stem_name: str) -> EP133StemConfig:
        """Return config for a stem, falling back to defaults."""
        if stem_name in self.stems:
            return self.stems[stem_name]
        # Fall back to the default per spec Section 3
        defaults = EP133ExportConfig.default().stems
        return defaults.get(stem_name, EP133StemConfig())


# ──────────────────────────────────────────────────────────────────────────────
# Audio processing
# ──────────────────────────────────────────────────────────────────────────────

def process_stem_wav(
    src_path: Path,
    out_path: Path,
    *,
    start_sec: float = 0.0,
    end_sec: float | None = None,
) -> tuple[Path, float, int]:
    """Process a stem WAV for the EP-133.

    Steps:
    1. Read source WAV (soundfile)
    2. Downmix to mono if stereo
    3. Slice to [start_sec, end_sec] — for v0, full file (start=0, end=None)
    4. Resample to EP133_SAMPLE_RATE (46875 Hz) via librosa
    5. Normalize: if peak > -1.0 dBFS, clip to [-1, 1] and rescale to peak=1.0
    6. Convert to int16
    7. Write as 16-bit WAV (soundfile)

    Returns: (output_path, duration_sec, channels_written)
    """
    import librosa

    audio, sr = sf.read(str(src_path), always_2d=False)

    # Downmix to mono
    if audio.ndim == 2:
        audio = audio.mean(axis=1)
    audio = audio.astype(np.float32)

    # Slice to [start_sec, end_sec]
    if start_sec > 0.0 or end_sec is not None:
        start_samp = int(start_sec * sr)
        end_samp = int(end_sec * sr) if end_sec is not None else len(audio)
        audio = audio[start_samp:end_samp]

    # Resample
    if sr != EP133_SAMPLE_RATE:
        audio = librosa.resample(audio, orig_sr=sr, target_sr=EP133_SAMPLE_RATE)

    # Normalize if peak > -1.0 dBFS
    peak = float(np.abs(audio).max())
    if peak > 0.0:
        audio = np.clip(audio, -1.0, 1.0)
        if peak > 1.0:
            # Already clipped — no further scale needed
            pass
        else:
            # Scale to peak = 1.0
            audio = audio / peak

    # Convert to int16
    audio_i16 = (audio * 32767.0).astype(np.int16)

    # Write 16-bit WAV
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(out_path), audio_i16, EP133_SAMPLE_RATE, subtype="PCM_16")

    duration_sec = len(audio_i16) / EP133_SAMPLE_RATE
    return out_path, duration_sec, 1  # always mono


# ──────────────────────────────────────────────────────────────────────────────
# SETUP.md generation
# ──────────────────────────────────────────────────────────────────────────────

def _time_stretch_label(ts: EP133TimeStretchConfig, fallback_bpm: float | None) -> str:
    if ts.mode == "none":
        return "off"
    if ts.mode == "bar":
        bars = ts.bars or "?"
        return f"BAR {bars}"
    # mode == "bpm"
    bpm = ts.source_bpm or fallback_bpm
    return f"BPM {bpm:.1f}" if bpm is not None else "BPM (auto)"


def generate_setup_md(
    song_name: str,
    bpm: float,
    results: list[dict[str, Any]],
    sync_mode: str = "midi_clock",
) -> str:
    """Generate the SETUP.md for an EP-133 export package.

    `results` is the list of result dicts returned by export_ep133_package.
    """
    lines: list[str] = []

    lines.append(f"# EP-133 Setup — {song_name}")
    lines.append("")

    # BPM Sync section
    lines.append("## BPM Sync")
    lines.append("")
    lines.append("1. Connect EP-133 to computer via USB-C")
    lines.append("2. EP-133: SHIFT+ERASE → MIDI → Clock → On")
    if sync_mode == "midi_clock":
        lines.append("3. Ableton: set MIDI output to EP-133, enable Clock")
    elif sync_mode == "sync24":
        lines.append("3. Sync source: connect 3.5mm TRS-A to EP-133 Sync In")
    elif sync_mode == "usb_midi":
        lines.append("3. USB MIDI clock — ensure host sends MIDI Clock on EP-133 port")
    lines.append("")
    lines.append(f"Project BPM: {bpm:.1f}")
    lines.append("")

    # Import table
    lines.append("## Import Samples (EP Sample Tool)")
    lines.append("")
    lines.append("Open EP Sample Tool. Import in this order:")
    lines.append("")
    lines.append("| Pad | Group | File | Play Mode | Loop | Mute Group | Time Stretch |")
    lines.append("|-----|-------|------|-----------|------|------------|--------------|")

    for r in results:
        cfg: EP133StemConfig = r["config"]
        audio = r["audio"]
        filename = audio["filename"]
        loop_str = "yes" if cfg.loop else "no"
        mg_str = str(cfg.mute_group) if cfg.mute_group > 0 else "—"
        ts_label = _time_stretch_label(cfg.time_stretch, bpm)
        lines.append(
            f"| {cfg.pad_num} | {cfg.pad_group} | {filename} "
            f"| {cfg.play_mode} | {loop_str} | {mg_str} | {ts_label} |"
        )

    lines.append("")

    # On-device Sound Edit
    lines.append("## On-Device Sound Edit (per pad)")
    lines.append("")
    lines.append("After import, for each pad:")
    lines.append("  SHIFT + SOUND → navigate with +/- to:")
    lines.append("  - Sound: set Play Mode (knobX)")
    lines.append("  - Time: set BPM or BAR + value (knobX / knobY)")
    lines.append("  - Mute Group: set group number (knobX)")
    lines.append("  - Trim: fine-adjust start point if needed (knobX = start, knobY = length)")
    lines.append("")

    # Per-pad detail
    lines.append("### Per-Pad Settings")
    lines.append("")
    for r in results:
        cfg = r["config"]
        audio = r["audio"]
        ts = cfg.time_stretch
        ts_label = _time_stretch_label(ts, bpm)
        mg_str = str(cfg.mute_group) if cfg.mute_group > 0 else "none"
        lines.append(
            f"**Pad {cfg.pad_group}{cfg.pad_num} — {r['stem']}** (`{audio['filename']}`)"
        )
        lines.append(f"- Play Mode: `{cfg.play_mode}`")
        lines.append(f"- Loop: {'yes' if cfg.loop else 'no'}")
        lines.append(f"- Mute Group: {mg_str}")
        lines.append(f"- Time Stretch: {ts_label}")
        if cfg.loop:
            lines.append(
                "- NOTE: Loop must be set manually on-device via Sound Edit → Loop"
                " until TNGE/SysEx path is confirmed."
            )
        if ts.mode != "none":
            lines.append(
                "- NOTE: Time Stretch must be set manually on-device via Sound Edit → Time"
                " until SysEx SET field is confirmed."
            )
        lines.append("")

    # Latch workaround
    drums_results = [r for r in results if r["stem"] == "drums"]
    if drums_results:
        lines.append("## Sticky Loop Upgrade (Optional — Drums)")
        lines.append("")
        lines.append("To get true on/off toggle for drums:")
        lines.append("  Program drums_ep133.wav as a looping sequencer pattern.")
        lines.append("  Assign a free pad to start/stop that pattern.")
        lines.append(
            "  This replaces oneshot+loop with a pattern trigger — true on/off toggle."
        )
        lines.append("  Cannot be automated by stemforge export; requires manual on-device setup.")
        lines.append("")

    # Known gaps / manual steps
    lines.append("## Known Gaps (SysEx Auto-Path Limitations)")
    lines.append("")
    lines.append(
        "The following settings are recorded in `ep133_manifest.json` but must be"
        " set manually on-device:"
    )
    lines.append("")
    lines.append("- **Loop** — Set via Sound Edit → Loop. SysEx TNGE chunk path TBD.")
    lines.append(
        "- **Time Stretch (BPM/BAR mode)** — Set via Sound Edit → Time."
        " SysEx SET field not yet confirmed via live trace."
    )
    lines.append("- **sound.playmode** — Writability via FILE_METADATA_SET TBD.")
    lines.append("")

    return "\n".join(lines)


# ──────────────────────────────────────────────────────────────────────────────
# Main export function
# ──────────────────────────────────────────────────────────────────────────────

def _load_stems_json(stems_json_path: Path) -> dict:
    return json.loads(stems_json_path.read_text())


def _find_wav_path(stems_data: dict, stem_name: str, stems_json_dir: Path) -> Path | None:
    """Locate the WAV for a stem name from stems.json."""
    for stem_entry in stems_data.get("stems", []):
        if stem_entry.get("name") == stem_name:
            wav = stem_entry.get("wav_path")
            if wav:
                p = Path(wav)
                if not p.is_absolute():
                    p = stems_json_dir / p
                return p
    return None


def export_ep133_package(
    stems_json_path: Path,
    config: EP133ExportConfig,
    out_dir: Path,
    *,
    dry_run: bool = False,
) -> list[dict[str, Any]]:
    """Export stems as an EP-133 package.

    For each stem in `config.stems`:
    1. Locate WAV from stems.json
    2. process_stem_wav → {stem}_ep133.wav in out_dir
    3. Build manifest block (spec Section 6 JSON format)

    Writes:
    - {stem}_ep133.wav for each processed stem
    - ep133_manifest.json (list of result blocks)
    - SETUP.md

    Returns list of result dicts (one per exported stem).
    """
    stems_data = _load_stems_json(stems_json_path)
    stems_json_dir = stems_json_path.parent

    song_name = stems_data.get("track_name") or stems_json_dir.name
    bpm: float = float(stems_data.get("bpm", 120.0))

    if not dry_run:
        out_dir.mkdir(parents=True, exist_ok=True)

    # Validate mute group count
    active_groups = {
        cfg.mute_group
        for cfg in config.stems.values()
        if cfg.mute_group > 0
    }
    if len(active_groups) > _MAX_MUTE_GROUPS:
        raise ValueError(
            f"ep133_export defines {len(active_groups)} non-zero mute groups"
            f" but the device supports at most {_MAX_MUTE_GROUPS}"
        )

    results: list[dict[str, Any]] = []

    for stem_name, stem_cfg in config.stems.items():
        wav_path = _find_wav_path(stems_data, stem_name, stems_json_dir)
        if wav_path is None or not wav_path.exists():
            # Stem not in this manifest — skip silently
            continue

        out_wav = out_dir / f"{stem_name}_ep133.wav"

        if dry_run:
            # For dry-run, read duration without processing
            info = sf.info(str(wav_path))
            duration_sec = info.duration
            channels = 1
        else:
            _, duration_sec, channels = process_stem_wav(
                wav_path,
                out_wav,
                start_sec=0.0,
                end_sec=None,  # v0: use full file
            )

        # Build time_stretch block for manifest
        ts = stem_cfg.time_stretch
        ts_dict = ts.to_dict()
        # Resolve source_bpm from manifest if not set explicitly
        if ts.mode != "none" and ts.source_bpm is None:
            ts_dict["source_bpm"] = bpm

        audio_block = {
            "filename": out_wav.name,
            "sample_rate": EP133_SAMPLE_RATE,
            "bit_depth": EP133_BIT_DEPTH,
            "channels": "mono" if channels == 1 else "stereo",
            "duration_sec": round(duration_sec, 4),
            "export_start_sec": 0.0,
            "export_end_sec": round(duration_sec, 4),
        }

        ep133_block = {
            "play_mode": stem_cfg.play_mode,
            "loop": stem_cfg.loop,
            "mute_group": stem_cfg.mute_group,
            "time_stretch": ts_dict,
            "pad": {"group": stem_cfg.pad_group, "pad": stem_cfg.pad_num},
            "audio": audio_block,
        }

        results.append({
            "stem": stem_name,
            "ep133": ep133_block,
            # Internal: keep config reference for SETUP.md generation
            "config": stem_cfg,
            "audio": audio_block,
        })

    if not dry_run and results:
        # Write ep133_manifest.json (spec Section 6 format)
        manifest_records = [{"stem": r["stem"], "ep133": r["ep133"]} for r in results]
        (out_dir / "ep133_manifest.json").write_text(
            json.dumps(manifest_records, indent=2)
        )

        # Write SETUP.md
        setup_md = generate_setup_md(
            song_name=song_name,
            bpm=bpm,
            results=results,
            sync_mode=config.sync_mode,
        )
        (out_dir / "SETUP.md").write_text(setup_md)

    return results


def load_config_from_yaml(pipeline_yaml: Path) -> EP133ExportConfig:
    """Load EP133ExportConfig from a pipeline YAML file."""
    import yaml

    data = yaml.safe_load(pipeline_yaml.read_text())
    return EP133ExportConfig.from_pipeline_dict(data)
