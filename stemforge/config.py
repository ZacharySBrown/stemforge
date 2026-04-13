from pathlib import Path

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
