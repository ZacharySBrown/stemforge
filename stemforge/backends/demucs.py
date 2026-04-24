import time
from pathlib import Path
from rich.console import Console
from .base import AbstractBackend
from ..config import DEMUCS_MODELS

console = Console()


class DemucsBackend(AbstractBackend):

    @property
    def name(self) -> str:
        return "Demucs (local)"

    def separate(self, audio_path: Path, output_dir: Path, **kwargs) -> dict[str, Path]:
        """
        kwargs:
          model (str): key from DEMUCS_MODELS or raw model name
                       e.g. "default", "fine", "6stem", or "htdemucs_ft"
        """
        try:
            import torch
            import torchaudio
            from demucs.pretrained import get_model
            from demucs.apply import apply_model
        except ImportError as e:
            raise RuntimeError(
                "Demucs backend requires the 'native' extras (torch + demucs).\n"
                "  Install with:  pip install 'stemforge[native]'\n"
                "Alternatively, use a cloud backend:\n"
                "  stemforge split <file> --backend lalal\n"
                "  stemforge split <file> --backend musicai"
            ) from e

        model_key = kwargs.get("model", "default")
        model_name = DEMUCS_MODELS.get(model_key, model_key)

        # Device: MPS on Apple Silicon, CUDA if available, else CPU
        if torch.backends.mps.is_available():
            device = torch.device("mps")
        elif torch.cuda.is_available():
            device = torch.device("cuda")
        else:
            device = torch.device("cpu")

        console.print(f"  Backend: [cyan]Demucs ({model_name})[/cyan]  device: {device}")
        if device.type == "cpu":
            console.print("  [yellow]Warning:[/yellow] CPU mode is 5-10x slower than MPS.")

        # Load model — first run downloads ~80MB to ~/.cache/torch/hub/
        console.print("  Loading model (cached after first run)...")
        model = get_model(model_name)
        model.to(device)

        # Load audio via soundfile directly — torchaudio ≥2.11 routes through
        # torchcodec regardless of backend=, and torchcodec is an optional dep
        # we don't want to require.
        import soundfile as sf
        audio_np, sr = sf.read(str(audio_path), dtype="float32", always_2d=True)
        waveform = torch.from_numpy(audio_np.T).contiguous()  # [channels, samples]

        # Resample if needed
        if sr != model.samplerate:
            console.print(f"  Resampling {sr}Hz → {model.samplerate}Hz")
            waveform = torchaudio.functional.resample(waveform, sr, model.samplerate)

        # Ensure stereo
        if waveform.shape[0] == 1:
            waveform = waveform.repeat(2, 1)
        elif waveform.shape[0] > 2:
            waveform = waveform[:2]

        # Add batch dim: (1, channels, samples)
        waveform = waveform.unsqueeze(0).to(device)

        console.print("  Separating... (apply_model handles chunking internally)")
        t0 = time.time()
        with torch.no_grad():
            sources = apply_model(model, waveform, device=device, progress=True)
        console.print(f"  Done in {time.time() - t0:.0f}s")

        # sources: (batch=1, stems, channels, samples) → drop batch dim
        sources = sources[0].cpu()  # (stems, channels, samples)

        output_dir.mkdir(parents=True, exist_ok=True)
        stem_paths = {}

        import soundfile as sf
        for stem_name, source in zip(model.sources, sources):
            out_path = output_dir / f"{stem_name}.wav"
            # Write via soundfile directly — torchaudio ≥2.11 routes save
            # through torchcodec which is an optional dep we don't require.
            # soundfile expects [samples, channels]; source is [channels, samples].
            sf.write(
                str(out_path),
                source.numpy().T,
                model.samplerate,
                subtype="PCM_24",
            )
            stem_paths[stem_name] = out_path
            console.print(f"  [green]OK[/green] {stem_name}: {out_path.name}")

        return stem_paths
        # Note: model.sources is always ["drums","bass","vocals","other"] for 4-stem
        # and ["drums","bass","vocals","guitar","piano","other"] for htdemucs_6s
        # Never hardcode stem names — always iterate model.sources
