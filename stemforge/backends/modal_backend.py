"""Modal backend — GPU stem separation via Modal cloud.

Calls the deployed `stemforge-batch` Modal app's `split_track` function.
Audio bytes are sent up, stem WAV bytes come back. No local GPU needed.

Prerequisites:
    pip install modal
    modal setup
    modal deploy batch/stemforge_batch.py
"""

from __future__ import annotations

import time
from pathlib import Path

from rich.console import Console

from .base import AbstractBackend

console = Console()

STEMS = ["drums", "bass", "vocals", "other"]

# Modal app and function names must match batch/stemforge_batch.py
MODAL_APP_NAME = "stemforge-batch"
MODAL_FUNCTION_NAME = "split_track"

# Lazy import — modal is an optional dependency
try:
    import modal
except ImportError:
    modal = None  # type: ignore[assignment]


class ModalBackend(AbstractBackend):

    @property
    def name(self) -> str:
        return "Modal (cloud GPU)"

    def separate(self, audio_path: Path, output_dir: Path, **kwargs) -> dict[str, Path]:
        """
        Upload audio to Modal GPU, run htdemucs_ft ONNX inference, download stems.

        kwargs:
            sample_rate (int): Target sample rate. Default: 44100
        """
        if modal is None:
            raise RuntimeError(
                "Modal backend requires the 'modal' package.\n"
                "  Install with:  pip install modal\n"
                "  Then set up:   modal setup\n"
                "  Then deploy:   modal deploy batch/stemforge_batch.py"
            )

        console.print(f"  Backend: [cyan]Modal (cloud GPU)[/cyan]")

        # Look up the deployed function by app + function name
        try:
            split_track = modal.Function.lookup(MODAL_APP_NAME, MODAL_FUNCTION_NAME)
        except Exception as e:
            raise RuntimeError(
                f"Could not find deployed Modal function '{MODAL_APP_NAME}/{MODAL_FUNCTION_NAME}'.\n"
                f"  Deploy first:  modal deploy batch/stemforge_batch.py\n"
                f"  Error: {e}"
            )

        # Read audio bytes from disk
        audio_bytes = audio_path.read_bytes()
        file_size_mb = len(audio_bytes) / (1024 * 1024)
        console.print(f"  Uploading {audio_path.name} ({file_size_mb:.1f} MB)...")

        # Call remote GPU function
        sample_rate = kwargs.get("sample_rate", 44100)
        t0 = time.time()

        try:
            stem_bytes: dict[str, bytes] = split_track.remote(
                audio_bytes,
                audio_path.name,
                sample_rate=sample_rate,
            )
        except Exception as e:
            raise RuntimeError(f"Modal split_track failed: {e}")

        elapsed = time.time() - t0
        console.print(f"  GPU inference done in {elapsed:.1f}s")

        # Write stems to disk
        output_dir.mkdir(parents=True, exist_ok=True)
        stem_paths: dict[str, Path] = {}

        for stem_name, wav_bytes in stem_bytes.items():
            out_path = output_dir / f"{stem_name}.wav"
            out_path.write_bytes(wav_bytes)
            stem_paths[stem_name] = out_path
            size_mb = len(wav_bytes) / (1024 * 1024)
            console.print(f"  [green]OK[/green] {stem_name}: {out_path.name} ({size_mb:.1f} MB)")

        return stem_paths
