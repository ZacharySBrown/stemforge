from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

# ── Folder layout ─────────────────────────────────────────────────────────────
STEMFORGE_ROOT = Path.home() / "stemforge"
INBOX_DIR      = STEMFORGE_ROOT / "inbox"
PROCESSED_DIR  = STEMFORGE_ROOT / "processed"
LOGS_DIR       = STEMFORGE_ROOT / "logs"
PIPELINES_DIR  = Path(__file__).parent.parent / "pipelines"

for d in [INBOX_DIR, PROCESSED_DIR, LOGS_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# ── LALAL.AI ──────────────────────────────────────────────────────────────────
LALAL_BASE = "https://www.lalal.ai/api/v1"

LALAL_STEMS = [
    "vocals", "drum", "bass", "piano",
    "electricguitar", "acousticguitar",
    "synthesizer", "strings", "wind",
]

LALAL_PRESETS = {
    "idm":   ["drum", "bass", "synthesizer"],
    "chop":  ["drum", "bass"],
    "4stem": ["vocals", "drum", "bass"],
    "full":  ["vocals", "drum", "bass", "synthesizer", "electricguitar"],
    "drums": ["drum"],
}

LALAL_DEFAULT_PRESET = "idm"

# ── Music.AI ──────────────────────────────────────────────────────────────────
MUSIC_AI_BASE = "https://api.music.ai/v1"

MUSIC_AI_WORKFLOWS = {
    "suite":  "music-ai/stem-separation-suite",       # 9-stem: vocals, drums, bass, keys, strings, guitars, piano, wind, other
    "vocals": "music-ai/stems-vocals-accompaniment",   # 4-stem: vocals, drums, bass, other
}

MUSIC_AI_DEFAULT_WORKFLOW = "vocals"

# ── Demucs ────────────────────────────────────────────────────────────────────
DEMUCS_MODELS = {
    "default": "htdemucs",      # 4 stems: drums, bass, vocals, other — fast
    "fine":    "htdemucs_ft",   # same 4, better quality, ~4x slower
    "6stem":   "htdemucs_6s",   # adds guitar + piano
}

# ── Ableton track colors (RGB hex) ────────────────────────────────────────────
# These are set via the LOM's color property (0x00RRGGBB format)
STEM_COLORS = {
    "drums":          0xFF2400,  # red
    "drum":           0xFF2400,
    "bass":           0x0055FF,  # blue
    "other":          0x00AA44,  # green
    "vocals":         0xFF8800,  # orange
    "guitar":         0xFFCC00,  # yellow
    "electricguitar": 0xFFCC00,
    "acousticguitar": 0xFFAA00,
    "piano":          0xAA00FF,  # purple
    "synthesizer":    0xAA00FF,
    "strings":        0x00CCAA,  # teal
    "wind":           0x88BBFF,  # light blue
    "keys":           0xAA00FF,  # purple (alias for synth/piano)
    "guitars":        0xFFCC00,  # yellow (alias for guitar group)
    "residual":       0x444444,  # dark grey
}

# ── Warp modes (Ableton internal index) ───────────────────────────────────────
WARP_MODES = {
    "beats":       0,
    "tones":       1,
    "texture":     2,
    "re-pitch":    3,
    "complex":     4,
    "complex-pro": 5,
}

# ── Curation Config ──────────────────────────────────────────────────────

DEFAULT_CURATION_CONFIG = PIPELINES_DIR / "curation.yaml"


@dataclass
class StemCurationConfig:
    phrase_bars: int = 1
    loop_count: int = 8
    oneshot_count: int = 8
    strategy: str = "max-diversity"
    oneshot_mode: str = "diverse"
    chromatic: bool = False
    midi_extract: bool = False
    midi_quantize: str = "1/16"
    bottom_mode: str = "melodic"    # melodic | scale | reconstruct
    chromatic_root: str = "auto"
    rms_floor: float = 0.005
    crest_min: float = 4.0
    content_density_min: float = 0.0  # fraction of 20ms frames with energy above rms threshold
    distance_weights: dict = field(default_factory=lambda: {
        "rhythm": 0.5, "spectral": 0.25, "energy": 0.25
    })
    processing: list[dict] = field(default_factory=lambda: [{"pipeline": "default"}])


@dataclass
class SongConfig:
    boundary_method: str = "recurrence"
    min_segment_bars: int = 4
    max_segments: int = 8
    prefer_transitions: bool = True
    transition_window_bars: int = 2


@dataclass
class DJConfig:
    base_position: str = "top_left"
    subloop_axis: str = "vertical"
    oneshot_axis: str = "horizontal"
    subloop_divisions: list[float] = field(default_factory=lambda: [1, 0.5, 0.5, 0.25])
    fill_mode: str = "combo"


@dataclass
class LayoutConfig:
    mode: str = "stems"
    pad_grid: str = "8x8"
    quadrant_size: str = "4x4"


@dataclass
class CurationConfig:
    version: int = 2
    layout: LayoutConfig = field(default_factory=LayoutConfig)
    stems: dict[str, StemCurationConfig] = field(default_factory=dict)
    song: SongConfig = field(default_factory=SongConfig)
    dj: DJConfig = field(default_factory=DJConfig)

    def for_stem(self, stem_name: str) -> StemCurationConfig:
        """Get config for a stem, falling back to defaults."""
        return self.stems.get(stem_name, StemCurationConfig())


def load_curation_config(path: str | Path | None = None) -> CurationConfig:
    """Load curation config from YAML. Merges per-stem overrides with defaults."""
    path = Path(path) if path else DEFAULT_CURATION_CONFIG
    if not path.exists():
        return CurationConfig()

    with open(path) as f:
        raw = yaml.safe_load(f)

    if not raw:
        return CurationConfig()

    defaults = raw.get("defaults", {})

    # Build per-stem configs, merging with defaults
    stems: dict[str, StemCurationConfig] = {}
    for stem_name, stem_raw in raw.get("stems", {}).items():
        merged = {**defaults, **stem_raw}
        stems[stem_name] = StemCurationConfig(
            phrase_bars=merged.get("phrase_bars", 1),
            loop_count=merged.get("loop_count", 8),
            oneshot_count=merged.get("oneshot_count", 8),
            strategy=merged.get("strategy", "max-diversity"),
            oneshot_mode=merged.get("oneshot_mode", "diverse"),
            chromatic=merged.get("chromatic", False),
            midi_extract=merged.get("midi_extract", False),
            midi_quantize=merged.get("midi_quantize", "1/16"),
            bottom_mode=merged.get("bottom_mode", "melodic"),
            chromatic_root=merged.get("chromatic_root", "auto"),
            rms_floor=merged.get("rms_floor", 0.005),
            crest_min=merged.get("crest_min", 4.0),
            content_density_min=merged.get("content_density_min", 0.0),
            distance_weights=merged.get("distance_weights", defaults.get("distance_weights", {})),
            processing=merged.get("processing", [{"pipeline": "default"}]),
        )

    # Build section configs
    layout_raw = raw.get("layout", {})
    layout = LayoutConfig(
        mode=layout_raw.get("mode", "stems"),
        pad_grid=layout_raw.get("pad_grid", "8x8"),
        quadrant_size=layout_raw.get("quadrant_size", "4x4"),
    )

    song_raw = raw.get("song", {})
    song = SongConfig(
        boundary_method=song_raw.get("boundary_method", "recurrence"),
        min_segment_bars=song_raw.get("min_segment_bars", 4),
        max_segments=song_raw.get("max_segments", 8),
        prefer_transitions=song_raw.get("prefer_transitions", True),
        transition_window_bars=song_raw.get("transition_window_bars", 2),
    )

    dj_raw = raw.get("dj", {})
    dj = DJConfig(
        base_position=dj_raw.get("base_position", "top_left"),
        subloop_axis=dj_raw.get("subloop_axis", "vertical"),
        oneshot_axis=dj_raw.get("oneshot_axis", "horizontal"),
        subloop_divisions=dj_raw.get("subloop_divisions", [1, 0.5, 0.5, 0.25]),
        fill_mode=dj_raw.get("fill_mode", "combo"),
    )

    return CurationConfig(
        version=raw.get("version", 2),
        layout=layout,
        stems=stems,
        song=song,
        dj=dj,
    )
