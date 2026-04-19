"""
stemforge.drum_separator — Drum sub-stem separation via LarsNet.

Separates a drum stem into 5 sub-stems: kick, snare, toms, hi-hat, cymbals.
Uses parallel U-Nets trained on StemGMD (1224 hours of isolated drum stems).

Model weights (562 MB) downloaded separately to ~/.stemforge/models/larsnet/
"""

from __future__ import annotations

import shutil
from pathlib import Path

import soundfile as sf
import torch

LARSNET_MODELS_DIR = Path.home() / ".stemforge" / "models" / "larsnet"
LARSNET_STEMS = ["kick", "snare", "toms", "hihat", "cymbals"]

# Where to find the config.yaml shipped with this module
_MODULE_DIR = Path(__file__).parent
_CONFIG_PATH = _MODULE_DIR / "config.yaml"


def _resolve_models_dir() -> Path:
    """Find LarsNet model weights. Checks multiple locations."""
    candidates = [
        LARSNET_MODELS_DIR / "pretrained_larsnet_models",
        Path("/tmp/larsnet/pretrained_larsnet_models"),
        _MODULE_DIR / "pretrained_larsnet_models",
    ]
    for d in candidates:
        if d.exists() and (d / "kick" / "pretrained_kick_unet.pth").exists():
            return d
    return candidates[0]  # default, will fail with clear error


def _make_config(models_dir: Path) -> Path:
    """Create a config.yaml pointing at the actual model paths."""
    import yaml

    with open(_CONFIG_PATH) as f:
        config = yaml.safe_load(f)

    # Update model paths to absolute
    for stem in LARSNET_STEMS:
        key = stem
        model_file = models_dir / stem / f"pretrained_{stem}_unet.pth"
        config["inference_models"][key] = str(model_file)

    tmp_config = Path("/tmp/stemforge_larsnet_config.yaml")
    with open(tmp_config, "w") as f:
        yaml.dump(config, f)

    return tmp_config


def separate_drums(
    drums_path: Path,
    output_dir: Path,
    device: str = "auto",
) -> dict[str, Path]:
    """
    Separate a drum stem into kick, snare, toms, hi-hat, cymbals.

    Args:
        drums_path: Path to drums.wav from htdemucs
        output_dir: Where to write sub-stem WAVs
        device: "auto" (MPS if available, else CPU), "mps", "cpu", "cuda"

    Returns:
        dict mapping stem name → output WAV path
    """
    from .larsnet import LarsNet

    # Resolve device
    if device == "auto":
        if torch.backends.mps.is_available():
            device = "mps"
        elif torch.cuda.is_available():
            device = "cuda"
        else:
            device = "cpu"

    # Find models
    models_dir = _resolve_models_dir()
    if not models_dir.exists():
        raise FileNotFoundError(
            f"LarsNet models not found at {models_dir}.\n"
            f"Download from: https://drive.google.com/uc?id=1U8-5924B1ii1cjv9p0MTPzayb00P4qoL\n"
            f"Unzip to: {LARSNET_MODELS_DIR}/"
        )

    # Create config pointing at models
    config_path = _make_config(models_dir)

    # Run separation
    net = LarsNet(device=device, config=str(config_path))
    stems = net(str(drums_path))

    # Write output
    output_dir.mkdir(parents=True, exist_ok=True)
    result = {}
    for stem_name, waveform in stems.items():
        out_path = output_dir / f"{stem_name}.wav"
        sf.write(str(out_path), waveform.cpu().numpy().T, net.sr, subtype="PCM_24")
        result[stem_name] = out_path

    return result


def is_available() -> bool:
    """Check if LarsNet models are downloaded and ready."""
    models_dir = _resolve_models_dir()
    return models_dir.exists() and (models_dir / "kick" / "pretrained_kick_unet.pth").exists()
