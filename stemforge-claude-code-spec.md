# StemForge — Full Claude Code Build Spec
## Dual-mode stem pipeline + Max for Live device + Ableton template system
**Host:** Mac Mini (macOS, Apple Silicon) | Ableton Live 12 Suite | Python 3.11+
**Handoff to:** Claude Code — build everything in this document top to bottom.

---

## 0. What This Is — Plain English

StemForge is two things that work together:

**Part A — `stemforge` CLI (Python)**
Run from the terminal (or invoked by a claw). Takes an audio file, splits it
into stems (either via LALAL.AI API or local Demucs), detects BPM, slices each
stem at every beat boundary into individual WAV files, and writes everything
into an organized output folder along with a `stems.json` manifest.

**Part B — StemForge Loader (Max for Live device)**
A device you drop once into a permanent "StemForge" Ableton Live set. It
watches for new `stems.json` files in the output folder. When one appears (or
when you click "Load"), it reads the manifest, sets the Live set tempo, then
for each stem: duplicates a pre-built template track, renames it, colors it,
loads the stem WAV directly into a clip slot (using the Live Object Model —
this is the key capability that only M4L can do), and dials in effect
parameter values from a pipeline config file you maintain.

**The user workflow end to end:**
1. Drop an audio file into `~/stemforge/inbox/`
2. Run: `stemforge split ~/stemforge/inbox/track.wav`
   (or tell your claw: "split track.wav with idm pipeline")
3. stemforge runs for 1-3 minutes, prints completion summary with BPM
4. Switch to Ableton — the M4L device sees the new `stems.json` automatically
   OR you click "Load Latest" in the device UI
5. Ableton creates tracks, loads clips, sets tempo — everything is playing and
   ready to mix. No manual browser dragging needed.

---

## 1. Repository Layout

```
stemforge/
├── stemforge/
│   ├── __init__.py
│   ├── cli.py                  ← Click CLI entrypoint
│   ├── backends/
│   │   ├── __init__.py
│   │   ├── base.py             ← AbstractBackend
│   │   ├── lalal.py            ← LALAL.AI API client
│   │   └── demucs.py           ← Local Demucs runner
│   ├── slicer.py               ← BPM detection + beat slicing
│   ├── manifest.py             ← stems.json writer/reader
│   └── config.py               ← Paths, constants, defaults
├── m4l/
│   ├── StemForgeLoader.amxd   ← Max for Live device (binary, built by Claude Code)
│   ├── stemforge_loader.js     ← JavaScript source for the M4L device
│   └── README_M4L.md           ← How to install the M4L device
├── pipelines/
│   └── default.yaml            ← Pipeline configuration (user-editable)
├── pyproject.toml
├── requirements-remote.txt
├── requirements-local.txt
├── requirements-full.txt
└── setup.md
```

---

## 2. Dependency Files

### `requirements-remote.txt`
```
requests>=2.31.0
librosa>=0.10.2
soundfile>=0.12.1
numpy>=1.26.0
click>=8.1.7
rich>=13.7.0
pyyaml>=6.0.1
```

### `requirements-local.txt`
```
torch>=2.1.0
torchaudio>=2.1.0
demucs>=4.0.1
librosa>=0.10.2
soundfile>=0.12.1
numpy>=1.26.0
click>=8.1.7
rich>=13.7.0
pyyaml>=6.0.1
```

### `requirements-full.txt`
```
-r requirements-remote.txt
torch>=2.1.0
torchaudio>=2.1.0
demucs>=4.0.1
```

### `pyproject.toml`
```toml
[build-system]
requires = ["setuptools>=68", "wheel"]
build-backend = "setuptools.backends.legacy:build"

[project]
name = "stemforge"
version = "0.2.0"
description = "Stem splitting + beat slicing pipeline for Ableton Live IDM production"
requires-python = ">=3.11"
dependencies = [
    "requests>=2.31.0",
    "librosa>=0.10.2",
    "soundfile>=0.12.1",
    "numpy>=1.26.0",
    "click>=8.1.7",
    "rich>=13.7.0",
    "pyyaml>=6.0.1",
]

[project.optional-dependencies]
local = ["torch>=2.1.0", "torchaudio>=2.1.0", "demucs>=4.0.1"]

[project.scripts]
stemforge = "stemforge.cli:cli"

[tool.setuptools.packages.find]
where = ["."]
include = ["stemforge*"]
```

**Install commands Claude Code must run:**
```bash
python3 -m venv ~/stemforge/.venv
source ~/stemforge/.venv/bin/activate

# Remote-only (no PyTorch):
pip install -e .

# With local Demucs support (Apple Silicon):
pip install torch torchaudio   # do NOT use --index-url cuda flag on Apple Silicon
pip install -e ".[local]"

# Verify:
python -c "import demucs; print('demucs OK')"
python -c "import torch; print('MPS:', torch.backends.mps.is_available())"
```

---

## 3. `stemforge/config.py`

```python
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
```

---

## 4. `stemforge/backends/base.py`

```python
from abc import ABC, abstractmethod
from pathlib import Path

class AbstractBackend(ABC):

    @abstractmethod
    def separate(self, audio_path: Path, output_dir: Path, **kwargs) -> dict[str, Path]:
        """
        Separate audio into stems.
        Returns dict mapping stem name → output WAV path.
        e.g. {"drums": Path("~/stemforge/processed/track/drums.wav"), ...}
        """
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        ...
```

---

## 5. `stemforge/backends/lalal.py`

Implement the LALAL.AI backend. Auth is `X-License-Key` header.
Key comes from `LALAL_LICENSE_KEY` environment variable.

Flow: upload file → submit multistem job → poll until done → download stems.

```python
import os, time, requests
from pathlib import Path
from rich.console import Console
from .base import AbstractBackend
from ..config import LALAL_BASE, LALAL_PRESETS, LALAL_DEFAULT_PRESET

console = Console()

class LalalBackend(AbstractBackend):

    @property
    def name(self) -> str:
        return "LALAL.AI"

    def _key(self) -> str:
        key = os.environ.get("LALAL_LICENSE_KEY", "").strip()
        if not key:
            raise RuntimeError(
                "LALAL_LICENSE_KEY not set.\n"
                "  1. Subscribe at lalal.ai (Pro plan, $15/mo)\n"
                "  2. Profile page → copy Activation Key\n"
                "  3. export LALAL_LICENSE_KEY=your_key"
            )
        return key

    def _h(self) -> dict:
        return {"X-License-Key": self._key()}

    def check_minutes(self) -> dict:
        r = requests.post(f"{LALAL_BASE}/limits/minutes_left/",
                         headers=self._h(), timeout=15)
        r.raise_for_status()
        return r.json()

    def _upload(self, path: Path) -> str:
        with open(path, "rb") as f:
            r = requests.post(
                f"{LALAL_BASE}/upload/",
                headers={
                    **self._h(),
                    "Content-Disposition": f"attachment; filename={path.name}",
                    "Content-Type": "application/octet-stream",
                },
                data=f, timeout=300,
            )
        r.raise_for_status()
        return r.json()["source_id"]

    def _submit(self, source_id: str, stems: list[str]) -> str:
        r = requests.post(
            f"{LALAL_BASE}/split/multistem/",
            headers={**self._h(), "Content-Type": "application/json"},
            json={"source_id": source_id, "stem_list": stems},
            timeout=30,
        )
        r.raise_for_status()
        return r.json()["task_id"]

    def _poll(self, task_id: str, interval: int = 8, timeout: int = 600) -> list:
        deadline = time.time() + timeout
        dots = 0
        while time.time() < deadline:
            r = requests.post(
                f"{LALAL_BASE}/check/",
                headers={**self._h(), "Content-Type": "application/json"},
                json={"task_ids": [task_id]}, timeout=15,
            )
            r.raise_for_status()
            task = r.json().get(task_id, {})
            status = task.get("status")
            if status == "success":
                console.print()
                return task.get("tracks", [])
            elif status == "error":
                raise RuntimeError(f"LALAL task failed: {task.get('error')}")
            pct = task.get("progress", 0)
            dots = (dots + 1) % 4
            console.print(f"  Processing{'.' * dots}   {pct:.0f}%", end="\r")
            time.sleep(interval)
        raise TimeoutError(f"Task {task_id} timed out")

    def _download(self, tracks: list, output_dir: Path) -> dict[str, Path]:
        output_dir.mkdir(parents=True, exist_ok=True)
        downloaded = {}
        for track in tracks:
            url = track.get("url")
            label = track.get("label", "unknown")
            if not url:
                continue
            if label == "no_multistem":
                label = "residual"
            ext = Path(url.split("?")[0]).suffix or ".wav"
            out = output_dir / f"{label}{ext}"
            r = requests.get(url, stream=True, timeout=120)
            r.raise_for_status()
            with open(out, "wb") as f:
                for chunk in r.iter_content(65536):
                    f.write(chunk)
            downloaded[label] = out
            console.print(f"  [green]OK[/green] {label}: {out.name}")
        return downloaded

    def _cleanup(self, source_id: str):
        try:
            requests.post(
                f"{LALAL_BASE}/delete/",
                headers={**self._h(), "Content-Type": "application/json"},
                json={"source_id": source_id}, timeout=15,
            )
        except Exception:
            pass

    def separate(self, audio_path: Path, output_dir: Path, **kwargs) -> dict[str, Path]:
        """
        kwargs:
          stems (list[str]): explicit stem list, OR
          preset (str): key from LALAL_PRESETS
        """
        stems = kwargs.get("stems")
        if stems is None:
            preset = kwargs.get("preset", LALAL_DEFAULT_PRESET)
            stems = LALAL_PRESETS.get(preset, LALAL_PRESETS[LALAL_DEFAULT_PRESET])

        console.print(f"  Backend: [cyan]LALAL.AI[/cyan]  stems: {', '.join(stems)}")
        console.print(f"  Cost: ~{len(stems)}x track duration in fast minutes")

        source_id = self._upload(audio_path)
        task_id = self._submit(source_id, stems)
        console.print(f"  Job: [dim]{task_id}[/dim]")

        t0 = time.time()
        tracks = self._poll(task_id)
        console.print(f"  Done in {time.time() - t0:.0f}s")

        result = self._download(tracks, output_dir)
        self._cleanup(source_id)
        return result
```

---

## 6. `stemforge/backends/demucs.py`

```python
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
        except ImportError:
            raise RuntimeError(
                "Demucs not installed.\n"
                "  pip install torch torchaudio demucs\n"
                "  See requirements-local.txt"
            )

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

        # Load audio
        waveform, sr = torchaudio.load(str(audio_path))

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

        for stem_name, source in zip(model.sources, sources):
            out_path = output_dir / f"{stem_name}.wav"
            torchaudio.save(
                str(out_path), source, model.samplerate,
                encoding="PCM_S", bits_per_sample=24,
            )
            stem_paths[stem_name] = out_path
            console.print(f"  [green]OK[/green] {stem_name}: {out_path.name}")

        return stem_paths
        # Note: model.sources is always ["drums","bass","vocals","other"] for 4-stem
        # and ["drums","bass","vocals","guitar","piano","other"] for htdemucs_6s
        # Never hardcode stem names — always iterate model.sources
```

---

## 7. `stemforge/slicer.py`

```python
import numpy as np
import soundfile as sf
import librosa
from pathlib import Path


def detect_bpm_and_beats(audio_path: Path) -> tuple[float, np.ndarray]:
    """
    Detect BPM and beat timestamps (in seconds) from an audio file.
    Uses the drums/most percussive stem for best accuracy.
    Returns (bpm, beat_times_array).
    """
    y, sr = librosa.load(str(audio_path), sr=None, mono=True)
    tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr, units="frames")
    beat_times = librosa.frames_to_time(beat_frames, sr=sr)
    return float(np.atleast_1d(tempo)[0]), beat_times


def slice_at_beats(
    stem_path: Path,
    beat_times: np.ndarray,
    output_dir: Path,
    stem_name: str,
    silence_threshold: float = 1e-5,
) -> list[Path]:
    """
    Slice stem WAV at beat boundaries.
    Output: {output_dir}/{stem_name}_beats/{stem_name}_beat_NNN.wav
    Skips near-silent chunks (saves space, avoids empty Drum Rack pads).
    Returns list of created file paths.
    """
    y, sr = librosa.load(str(stem_path), sr=None, mono=False)
    if y.ndim == 1:
        y = y[np.newaxis, :]  # (1, samples)

    slices_dir = output_dir / f"{stem_name}_beats"
    slices_dir.mkdir(parents=True, exist_ok=True)

    total_samples = y.shape[-1]
    boundaries = np.concatenate([
        librosa.time_to_samples(beat_times, sr=sr),
        [total_samples],
    ]).astype(int)
    boundaries = np.clip(boundaries, 0, total_samples)

    created = []
    for i in range(len(boundaries) - 1):
        start, end = int(boundaries[i]), int(boundaries[i + 1])
        if end <= start:
            continue
        chunk = y[:, start:end]
        if float(np.sqrt(np.mean(chunk ** 2))) < silence_threshold:
            continue
        fname = slices_dir / f"{stem_name}_beat_{i + 1:03d}.wav"
        sf.write(str(fname), chunk.T, sr, subtype="PCM_24")
        created.append(fname)

    return created
```

---

## 8. `stemforge/manifest.py`

```python
"""
stems.json schema — written by CLI, read by M4L device.
"""
import json, time
from pathlib import Path
from dataclasses import dataclass, asdict


@dataclass
class StemInfo:
    name: str           # e.g. "drums"
    wav_path: str       # absolute path to full stem WAV
    beats_dir: str      # absolute path to beat slices folder
    beat_count: int     # number of beat slice files written


@dataclass
class StemManifest:
    track_name: str
    source_file: str
    backend: str
    bpm: float
    beat_count: int
    stems: list[StemInfo]
    output_dir: str
    pipeline: str       # pipeline name used (from pipelines/default.yaml)
    processed_at: str


def write_manifest(
    output_dir: Path,
    track_name: str,
    source_file: Path,
    backend: str,
    bpm: float,
    beat_count: int,
    stem_paths: dict[str, Path],
    slice_counts: dict[str, int],
    pipeline: str = "default",
) -> Path:
    stems = []
    for stem_name, stem_path in stem_paths.items():
        beats_dir = output_dir / f"{stem_name}_beats"
        stems.append(StemInfo(
            name=stem_name,
            wav_path=str(stem_path.resolve()),
            beats_dir=str(beats_dir.resolve()),
            beat_count=slice_counts.get(stem_name, 0),
        ))

    manifest = StemManifest(
        track_name=track_name,
        source_file=str(source_file.resolve()),
        backend=backend,
        bpm=round(bpm, 2),
        beat_count=beat_count,
        stems=stems,
        output_dir=str(output_dir.resolve()),
        pipeline=pipeline,
        processed_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
    )

    path = output_dir / "stems.json"
    path.write_text(json.dumps(asdict(manifest), indent=2))
    return path


def read_manifest(manifest_path: Path) -> dict:
    return json.loads(manifest_path.read_text())
```

---

## 9. `stemforge/cli.py`

```python
#!/usr/bin/env python3
import json, os, sys, time
from pathlib import Path

import click
from rich.console import Console
from rich.rule import Rule

from .backends.lalal import LalalBackend
from .backends.demucs import DemucsBackend
from .slicer import detect_bpm_and_beats, slice_at_beats
from .manifest import write_manifest
from .config import (
    PROCESSED_DIR, LALAL_PRESETS, LALAL_STEMS, LALAL_DEFAULT_PRESET,
    DEMUCS_MODELS,
)

console = Console()


@click.group()
def cli():
    """StemForge — stem splitting + beat slicing for Ableton Live."""
    pass


@cli.command()
@click.argument("audio_file", type=click.Path(exists=True, path_type=Path))
@click.option("--backend", "-b",
              type=click.Choice(["lalal", "demucs", "auto"]),
              default="auto",
              help="'auto' uses LALAL if LALAL_LICENSE_KEY is set, else Demucs.")
@click.option("--stems", "-s", default=None,
              help=f"[lalal] Preset ({', '.join(LALAL_PRESETS)}) or "
                   f"comma-separated stems. Default: {LALAL_DEFAULT_PRESET}")
@click.option("--model", "-m", default="default",
              help=f"[demucs] Model key: {', '.join(DEMUCS_MODELS)}.")
@click.option("--pipeline", "-p", default="default",
              help="Pipeline name from pipelines/default.yaml (written to manifest).")
@click.option("--output", "-o", default=None, type=click.Path(path_type=Path),
              help=f"Output root directory. Default: {PROCESSED_DIR}")
@click.option("--no-slice", is_flag=True, default=False,
              help="Skip beat slicing. Full stems only.")
def split(audio_file, backend, stems, model, pipeline, output, no_slice):
    """
    Split an audio file into stems and slice at beat boundaries.

    \b
    Examples:
      stemforge split track.wav                          # auto backend, IDM preset
      stemforge split track.wav --backend lalal          # force LALAL.AI
      stemforge split track.wav --backend demucs         # force local Demucs
      stemforge split track.wav --stems chop             # drum+bass only (LALAL)
      stemforge split track.wav --model 6stem            # 6-stem Demucs model
      stemforge split track.wav --pipeline glitch        # use 'glitch' pipeline config
      stemforge split track.wav --no-slice               # full stems, no beat files
    """
    # ── Resolve backend ──────────────────────────────────────────────────────
    if backend == "auto":
        has_lalal = bool(os.environ.get("LALAL_LICENSE_KEY", "").strip())
        backend = "lalal" if has_lalal else "demucs"
        console.print(f"  [dim]Auto-selected backend: {backend}[/dim]")

    be = LalalBackend() if backend == "lalal" else DemucsBackend()

    # ── Output dir ───────────────────────────────────────────────────────────
    out_root = output or PROCESSED_DIR
    track_name = audio_file.stem
    track_out = out_root / track_name
    track_out.mkdir(parents=True, exist_ok=True)

    # ── LALAL stem resolution ─────────────────────────────────────────────────
    backend_kwargs = {}
    if backend == "lalal":
        if stems is None:
            backend_kwargs["preset"] = LALAL_DEFAULT_PRESET
        elif stems in LALAL_PRESETS:
            backend_kwargs["preset"] = stems
        else:
            stem_list = [s.strip() for s in stems.split(",")]
            bad = [s for s in stem_list if s not in LALAL_STEMS]
            if bad:
                raise click.UsageError(f"Unknown stems: {bad}. Available: {LALAL_STEMS}")
            backend_kwargs["stems"] = stem_list
    else:
        backend_kwargs["model"] = model

    # ── Header ────────────────────────────────────────────────────────────────
    console.print(Rule(f"[bold cyan]StemForge[/bold cyan] — {track_name}"))
    console.print(f"  File:     {audio_file}")
    console.print(f"  Backend:  [cyan]{be.name}[/cyan]")
    console.print(f"  Pipeline: [cyan]{pipeline}[/cyan]")
    console.print(f"  Output:   {track_out}")
    console.print()

    # ── 1. Separate ───────────────────────────────────────────────────────────
    console.print("[bold]1/3  Separating stems[/bold]")
    try:
        stem_paths = be.separate(audio_file, track_out, **backend_kwargs)
    except Exception as e:
        console.print(f"[red]Separation failed:[/red] {e}")
        sys.exit(1)

    if not stem_paths:
        console.print("[red]No stems produced.[/red]")
        sys.exit(1)

    # ── 2. BPM + beat slicing ─────────────────────────────────────────────────
    console.print()
    console.print("[bold]2/3  BPM detection + beat slicing[/bold]")

    # Prefer drums/drum stem for BPM accuracy
    bpm_source = (
        stem_paths.get("drums") or stem_paths.get("drum") or
        stem_paths.get("bass") or next(iter(stem_paths.values()))
    )
    bpm, beat_times = detect_bpm_and_beats(bpm_source)
    console.print(
        f"  BPM: [bold cyan]{bpm:.1f}[/bold cyan]  "
        f"half-time: {bpm/2:.1f}  |  {len(beat_times)} beats"
    )

    slice_counts = {}
    if not no_slice:
        for stem_name, stem_path in stem_paths.items():
            if stem_name == "residual":
                continue
            slices = slice_at_beats(stem_path, beat_times, track_out, stem_name)
            slice_counts[stem_name] = len(slices)
            console.print(f"  {stem_name}: {len(slices)} beat files → {stem_name}_beats/")

    # ── 3. Write manifest ─────────────────────────────────────────────────────
    console.print()
    console.print("[bold]3/3  Writing stems.json manifest[/bold]")
    manifest_path = write_manifest(
        output_dir=track_out,
        track_name=track_name,
        source_file=audio_file,
        backend=backend,
        bpm=bpm,
        beat_count=len(beat_times),
        stem_paths=stem_paths,
        slice_counts=slice_counts,
        pipeline=pipeline,
    )
    console.print(f"  Written: {manifest_path}")

    # ── Summary ───────────────────────────────────────────────────────────────
    console.print()
    console.print(Rule("[bold green]Done![/bold green]"))
    console.print(f"\n[bold]Output:[/bold] {track_out}")
    console.print(f"  BPM: [cyan]{bpm:.1f}[/cyan]")
    for label, path in stem_paths.items():
        kb = path.stat().st_size // 1024
        line = f"  {label}.wav  ({kb:,}KB)"
        if label in slice_counts:
            line += f"  → {label}_beats/ [{slice_counts[label]} files]"
        console.print(line)
    console.print(
        "\n[dim]The M4L device in Ableton will detect stems.json automatically.[/dim]"
    )
    console.print(
        "[dim]Or: Ableton browser → Places → stemforge/processed → drag files.[/dim]"
    )


@cli.command()
def balance():
    """Show remaining LALAL.AI API minutes."""
    be = LalalBackend()
    with console.status("Checking..."):
        data = be.check_minutes()
    console.print("\n[bold]LALAL.AI minutes remaining:[/bold]")
    console.print(f"  Fast:    [cyan]{data.get('fast_minutes_left', '?')}[/cyan]")
    console.print(f"  Relaxed: [cyan]{data.get('relaxed_minutes_left', '?')}[/cyan]")


@cli.command("list")
def list_options():
    """Show available stems, presets, and models."""
    console.print("\n[bold]LALAL.AI presets:[/bold]")
    for name, stem_list in LALAL_PRESETS.items():
        console.print(f"  [cyan]{name:<8}[/cyan]  {', '.join(stem_list)}  "
                      f"[dim]({len(stem_list)}x cost)[/dim]")
    console.print(f"\n[bold]All LALAL stems:[/bold]  {', '.join(LALAL_STEMS)}")
    console.print("\n[bold]Demucs models:[/bold]")
    descs = {
        "default": "htdemucs — drums, bass, vocals, other (fast, ~1x realtime on M2)",
        "fine":    "htdemucs_ft — same 4 stems, better quality, 4x slower",
        "6stem":   "htdemucs_6s — adds guitar + piano (best for IDM sampling)",
    }
    for key, desc in descs.items():
        console.print(f"  [cyan]{key:<8}[/cyan]  {desc}")


if __name__ == "__main__":
    cli()
```

---

## 10. `pipelines/default.yaml`

This is the user-editable pipeline configuration. The M4L device reads this
file to know which template track to duplicate per stem type, and what effect
parameter values to dial in. Claude Code writes this file with sensible IDM
defaults. The user edits it over time to build their own signal chain presets.

```yaml
# pipelines/default.yaml
# ─────────────────────────────────────────────────────────────────────────────
# StemForge Pipeline Configuration
# Edit this file to customize how stems are processed in Ableton.
#
# Each pipeline is a named set of stem→template mappings.
# When stemforge split runs with --pipeline <name>, that name is baked into
# stems.json and the M4L device uses it to select the right mappings.
#
# Template tracks must exist in your Ableton "StemForge Templates" set.
# See setup.md for how to build them.
#
# Effect parameter indices: use the M4L device's "Inspect" button to find
# the parameter index for any device on any track. VSTs expose their
# parameters by index just like native devices.
#
# Warp modes: beats=0, tones=1, texture=2, re-pitch=3, complex=4, complex-pro=5
# ─────────────────────────────────────────────────────────────────────────────

pipelines:

  # ── DEFAULT: clean stems, minimal processing ────────────────────────────────
  default:
    description: "Clean stems, warped and looped, ready to use"
    stems:
      drums:
        template: "SF | Drums Raw"
        color: 0xFF2400
        warp_mode: beats
        loop: true
      drum:
        template: "SF | Drums Raw"
        color: 0xFF2400
        warp_mode: beats
        loop: true
      bass:
        template: "SF | Bass"
        color: 0x0055FF
        warp_mode: beats
        loop: true
      other:
        template: "SF | Texture"
        color: 0x00AA44
        warp_mode: complex
        loop: true
      vocals:
        template: "SF | Vocals"
        color: 0xFF8800
        warp_mode: tones
        loop: true
      synthesizer:
        template: "SF | Texture"
        color: 0xAA00FF
        warp_mode: complex
        loop: true
      guitar:
        template: "SF | Texture"
        color: 0xFFCC00
        warp_mode: complex
        loop: true
      electricguitar:
        template: "SF | Texture"
        color: 0xFFCC00
        warp_mode: complex
        loop: true
      piano:
        template: "SF | Texture"
        color: 0xAA00FF
        warp_mode: tones
        loop: true

  # ── IDM CRUSHED: heavy degradation — Aphex/Squarepusher territory ────────────
  idm_crushed:
    description: "Bitcrushed, saturated, degraded — maximum texture"
    stems:
      drums:
        template: "SF | Drums Crushed"
        color: 0xFF2400
        warp_mode: beats
        loop: true
        effects:
          # Device 0: LO-FI-AF (VST)
          # Digital section — bitcrusher at ~10-bit, sample rate heavy reduction
          - device: 0
            params:
              # param indices must be verified via M4L inspect on your machine
              # these are approximate starting points for LO-FI-AF
              Digital_Bits: 0.55        # ~10-bit range (0=16bit, 1=4bit)
              Digital_Rate: 0.45        # sample rate reduction
              Analog_Flux: 0.25         # tape warble
              Global_Strength: 0.75     # overall intensity
          # Device 1: Decapitator (VST)
          - device: 1
            params:
              Drive: 0.35
              Style: 0.0                # style A = Ampex 350 warmth
              Mix: 0.6
          # Device 2: Ableton Compressor
          - device: 2
            params:
              Ratio: 0.85               # ~8:1
              Attack_Time: 0.05
              Release_Time: 0.25
              Makeup: 0.55

      drum:
        template: "SF | Drums Crushed"
        color: 0xFF2400
        warp_mode: beats
        loop: true
        effects:
          - device: 0
            params:
              Digital_Bits: 0.55
              Digital_Rate: 0.45
              Analog_Flux: 0.25
              Global_Strength: 0.75
          - device: 1
            params:
              Drive: 0.35
              Style: 0.0
              Mix: 0.6

      bass:
        template: "SF | Bass"
        color: 0x0055FF
        warp_mode: beats
        loop: true
        effects:
          # Device 0: Ableton EQ Eight (highpass + low shelf)
          - device: 0
            params:
              "1 Frequency": 0.22       # highpass ~40Hz
              "2 Gain": 0.55            # low shelf boost ~80Hz
          # Device 1: LO-FI-AF — analog section only, subtle tape
          - device: 1
            params:
              Analog_Flux: 0.15
              Analog_Press: 0.3
              Global_Strength: 0.35     # subtle on bass

      other:
        template: "SF | Texture Verb"
        color: 0x00AA44
        warp_mode: complex
        loop: true
        effects:
          # Device 0: LO-FI-AF — spectral + analog for texture weirdness
          - device: 0
            params:
              Spectral_Ripple: 0.3
              Spectral_MP3: 0.2
              Analog_Flux: 0.4
              Global_Strength: 0.55
          # Device 1: EchoBoy (VST) — tape echo
          - device: 1
            params:
              Style: 0.3                # tape echo style
              Time: 0.5                 # 1/4 note synced
              Feedback: 0.3
              Mix: 0.35
          # Device 2: Ableton Reverb — large hall
          - device: 2
            params:
              Room_Size: 0.75
              Decay_Time: 0.7
              Dry_Wet: 0.35

      synthesizer:
        template: "SF | Texture Verb"
        color: 0xAA00FF
        warp_mode: complex
        loop: true
        effects:
          - device: 0
            params:
              Spectral_Ripple: 0.4
              Spectral_MP3: 0.3
              Global_Strength: 0.6

  # ── GLITCH: Crystallizer + spectral destruction ────────────────────────────
  glitch:
    description: "Granular reverse textures, spectral mangling — Four Tet / Boards of Canada"
    stems:
      drums:
        template: "SF | Drums Raw"
        color: 0xFF2400
        warp_mode: beats
        loop: true

      drum:
        template: "SF | Drums Raw"
        color: 0xFF2400
        warp_mode: beats
        loop: true

      bass:
        template: "SF | Bass"
        color: 0x0055FF
        warp_mode: beats
        loop: true

      other:
        template: "SF | Texture Crystallized"
        color: 0x00AA44
        warp_mode: complex-pro
        loop: true
        effects:
          # Device 0: Crystallizer (VST) — granular reverse echo
          - device: 0
            params:
              Pitch: 0.43               # -7 semitones (0=+12, 0.5=0, 1=-12)
              Splice: 0.2               # short grain size
              Delay: 0.4                # delay time
              Recycle: 0.35             # feedback
              Reverse: 1.0              # reverse on
              Mix: 0.7
          # Device 1: Ableton Reverb — wash it out
          - device: 1
            params:
              Room_Size: 0.9
              Decay_Time: 0.85
              Dry_Wet: 0.6

      synthesizer:
        template: "SF | Texture Crystallized"
        color: 0xAA00FF
        warp_mode: complex-pro
        loop: true
        effects:
          - device: 0
            params:
              Pitch: 0.57               # +7 semitones
              Splice: 0.3
              Recycle: 0.45
              Reverse: 1.0
              Mix: 0.65

  # ── AMBIENT: long tails, wide spaces — slow IDM / textural ─────────────────
  ambient:
    description: "Expansive reverbs, slow modulation — textural/ambient IDM"
    stems:
      drums:
        template: "SF | Drums Raw"
        color: 0xFF2400
        warp_mode: beats
        loop: true
        effects:
          # LO-FI-AF — very subtle analog warmth only
          - device: 0
            params:
              Analog_Flux: 0.1
              Global_Strength: 0.2

      drum:
        template: "SF | Drums Raw"
        color: 0xFF2400
        warp_mode: beats
        loop: true

      bass:
        template: "SF | Bass"
        color: 0x0055FF
        warp_mode: tones
        loop: true

      other:
        template: "SF | Texture Verb"
        color: 0x00AA44
        warp_mode: complex-pro
        loop: true
        effects:
          # PhaseMistress — slow deep phase
          - device: 0
            params:
              Rate: 0.08                # very slow
              Depth: 0.8
              Style: 0.0
          # EchoBoy — long tape delay
          - device: 1
            params:
              Style: 0.3
              Time: 0.75               # dotted 1/4
              Feedback: 0.45
              Mix: 0.45
          # SuperPlate/Little Plate — big plate reverb
          - device: 2
            params:
              Decay: 0.85
              Mix: 0.5

      synthesizer:
        template: "SF | Texture Verb"
        color: 0xAA00FF
        warp_mode: complex-pro
        loop: true
```

---

## 11. Ableton Template Tracks — Manual Setup Instructions

**Claude Code must write `setup.md` with these exact instructions.**
These template tracks are built by hand once in Ableton — they cannot be
created programmatically. The M4L device duplicates them.

```markdown
## Building the StemForge Template Set

### Step 1: Create a dedicated Ableton set
- File → New Live Set
- Save as: ~/Music/Ableton/Projects/StemForge Templates/StemForge Templates.als
- This set stays open while you produce. Never delete it.

### Step 2: Add ~/stemforge/processed to Ableton browser
Browser → Places → right-click → "Add Folder" → select ~/stemforge/processed
New stems appear here instantly after each stemforge run.

### Step 3: Build these template tracks (in order)
Each track below is a recipe. Build exactly this — the M4L device finds them
by name. Track names must match exactly.

─────────────────────────────────────────────────────────────────────────
TRACK 1: "SF | Drums Raw"   [Audio Track]   Color: Red
─────────────────────────────────────────────────────────────────────────
Devices (left to right on the track):
  1. Ableton Compressor
     - Ratio: 2.5:1
     - Attack: 10ms
     - Release: 80ms
     - Makeup: 0dB
  2. Ableton EQ Eight
     - Band 1: High shelf +2dB @ 10kHz

Clip settings (when audio is loaded by M4L):
  - Warp: ON, Mode: Beats
  - Loop: ON
  - Launch Mode: Toggle

─────────────────────────────────────────────────────────────────────────
TRACK 2: "SF | Drums Crushed"   [Audio Track]   Color: Red (darker)
─────────────────────────────────────────────────────────────────────────
Devices:
  1. LO-FI-AF (VST3 — Unfiltered Audio)
     Default preset: "Default"
     Sections active: Digital ON, Analog ON, Spectral OFF, Convolution OFF
     - Digital: Bits ~10-bit, Rate moderate
     - Analog: Flux (tape warble) moderate
     - Global Strength: 0.7
  2. Decapitator (VST3 — Soundtoys)
     - Style: A (Ampex 350)
     - Drive: 3
     - Mix: 60%
  3. Ableton Compressor
     - Ratio: 6:1
     - Attack: 5ms
     - Release: 60ms
     - Makeup: +2dB
  4. EchoBoy Jr (VST3 — Soundtoys)  [optional, can bypass]
     - Style: Tape Echo
     - Time: Sync 1/16
     - Feedback: 15%
     - Mix: 12%

─────────────────────────────────────────────────────────────────────────
TRACK 3: "SF | Bass"   [Audio Track]   Color: Blue
─────────────────────────────────────────────────────────────────────────
Devices:
  1. Ableton EQ Eight
     - Band 1: High Pass @ 35Hz
     - Band 2: Low shelf +2dB @ 80Hz
     - Band 3: High shelf -1dB @ 8kHz
  2. Ableton Compressor
     - Ratio: 4:1
     - Attack: 20ms
     - Release: 120ms
  3. LO-FI-AF (VST3)
     Sections: Analog ON only
     - Analog: Flux minimal (0.1), Press moderate (0.3)
     - Global Strength: 0.3
  4. Decapitator (VST3)
     - Style: E (warm transformer)
     - Drive: 1.5
     - Low Cut: 40Hz
     - Mix: 40%

─────────────────────────────────────────────────────────────────────────
TRACK 4: "SF | Texture Verb"   [Audio Track]   Color: Green
─────────────────────────────────────────────────────────────────────────
Devices:
  1. PhaseMistress (VST3 — Soundtoys)
     - Rate: slow (20%)
     - Depth: 60%
     - Style: Vintage
  2. EchoBoy (VST3 — Soundtoys)
     - Style: Tape Echo
     - Time: Sync 1/4
     - Feedback: 35%
     - Saturation: 20%
     - Mix: 40%
  3. Ableton Reverb
     - Room Size: 75%
     - Decay: 3.0s
     - Diffusion: 90%
     - Dry/Wet: 35%
  4. LO-FI-AF (VST3)
     Sections: Spectral ON, Analog ON
     - Spectral: Ripple 0.2, MP3 0.15
     - Analog: Flux 0.3
     - Global Strength: 0.45

Clip settings: Warp Complex, Loop ON

─────────────────────────────────────────────────────────────────────────
TRACK 5: "SF | Texture Crystallized"   [Audio Track]   Color: Green (teal)
─────────────────────────────────────────────────────────────────────────
Devices:
  1. Crystallizer (VST3 — Soundtoys)
     - Pitch: -5 semitones
     - Splice: short
     - Delay: 40%
     - Recycle: 30%
     - Reverse: ON
     - Mix: 70%
  2. Ableton Reverb
     - Room Size: 90%
     - Decay: 5.0s
     - Dry/Wet: 60%
  3. Ableton Utility
     - Width: 130%

Clip settings: Warp Complex Pro, Loop ON

─────────────────────────────────────────────────────────────────────────
TRACK 6: "SF | Vocals"   [Audio Track]   Color: Orange
─────────────────────────────────────────────────────────────────────────
Devices:
  1. Ableton EQ Eight
     - Band 1: High Pass @ 120Hz
     - Band 2: Presence boost +2dB @ 3kHz
  2. Ableton Compressor
     - Ratio: 3:1
     - Attack: 15ms
     - Release: 100ms
  3. LO-FI-AF (VST3)
     Sections: Analog ON, Convolution ON (mic IRs for vintage feel)
     - Convolution: Amount 0.3, select "phone mic" or "vintage mic" IR
     - Analog: Flux 0.2, Press 0.25
     - Global Strength: 0.4
  4. EchoBoy (VST3 — Soundtoys)
     - Style: Space Echo
     - Time: Sync 1/8
     - Feedback: 20%
     - Mix: 25%

─────────────────────────────────────────────────────────────────────────
TRACK 7: "SF | Beat Chop Simpler"   [MIDI Track]   Color: Red (bright)
─────────────────────────────────────────────────────────────────────────
Instruments + Devices:
  1. Ableton Simpler
     - Mode: Classic (not Slice — Slice mode is manual)
     - Warp: ON, Complex Pro
     - Note: M4L loads beat WAV directly into Simpler's sample slot
  2. Decapitator (VST3 — Soundtoys)
     - Style: B
     - Drive: 2
     - Mix: 50%
  3. PrimalTap (VST3 — Soundtoys)
     - Clock: ~100ms
     - Feedback: 20%
     - Mix: 20%

Note: For this track, M4L loads the DRUMS beat slice (beat_001.wav or most
energetic beat as determined by RMS ranking) into Simpler's sample slot.
The M4L device targets Simpler's "Sample" parameter via LOM.

### Step 4: Group all tracks
Select all 7 tracks → Cmd+G → name group "StemForge Templates" → color grey.
Fold the group. These tracks stay in the set forever.

### Step 5: Install AbletonOSC (optional, for tempo sync from CLI)
git clone https://github.com/ideoforms/AbletonOSC /tmp/AbletonOSC
cp -r /tmp/AbletonOSC/AbletonOSC \
  ~/Music/Ableton/User\ Library/Remote\ Scripts/AbletonOSC
Then: Live Preferences → MIDI → Control Surface → AbletonOSC

### Step 6: Install the StemForge Loader M4L device
Drag StemForgeLoader.amxd from the stemforge/m4l/ folder onto any track
in the StemForge Templates set (a dedicated MIDI track called "SF Loader"
is ideal). It will stay there permanently.
```

---

## 12. M4L Device — `m4l/stemforge_loader.js`

This is the JavaScript source for the Max for Live device. Claude Code builds
this file AND the Max patch wrapper (described below).

The device is an **Instrument** type M4L device (so it can sit on a MIDI track
with no audio implications). It does not process audio.

```javascript
// stemforge_loader.js
// ─────────────────────────────────────────────────────────────────────────────
// Max for Live JavaScript device — StemForge Loader
// Watches ~/stemforge/processed/ for new stems.json files.
// When found, loads stems into Ableton template tracks using the Live API.
//
// Live API path references (all 0-indexed):
//   Song:          live_set
//   Track N:       live_set tracks N
//   ClipSlot N:    live_set tracks T clip_slots S
//   Device on trk: live_set tracks T devices D
//   Device param:  live_set tracks T devices D parameters P
// ─────────────────────────────────────────────────────────────────────────────

inlets = 1;
outlets = 2;   // outlet 0: status string for display, outlet 1: bang on load complete

var liveAPI  = new LiveAPI();
var YAML     = null;   // YAML parsing done in Python via system call (see below)
var fs       = null;   // Max's file system via "file" object

// ── Configuration ─────────────────────────────────────────────────────────────
var PROCESSED_DIR = Packages.java.lang.System.getProperty("user.home") +
                    "/stemforge/processed";
var PIPELINES_DIR = "";  // set from Max patch via setPipelinesDir message
var POLL_INTERVAL = 3000; // ms between folder checks in watch mode
var WARP_MODES    = {beats:0, tones:1, texture:2, "re-pitch":3, complex:4, "complex-pro":5};

// State
var lastLoadedManifest = "";
var watchTimer = null;
var isWatching = false;
var pipelineConfig = {};

// ── Entry points called from Max patch ────────────────────────────────────────

function bang() {
    loadLatest();
}

function loadLatest() {
    var manifest = findLatestManifest(PROCESSED_DIR);
    if (!manifest) {
        outlet(0, "No stems.json found in " + PROCESSED_DIR);
        return;
    }
    if (manifest === lastLoadedManifest) {
        outlet(0, "Already loaded: " + manifest);
        return;
    }
    loadManifest(manifest);
}

function startWatch() {
    if (isWatching) return;
    isWatching = true;
    outlet(0, "Watching " + PROCESSED_DIR);
    scheduleWatch();
}

function stopWatch() {
    isWatching = false;
    if (watchTimer) { watchTimer.cancel(); watchTimer = null; }
    outlet(0, "Watch stopped");
}

function setPipelinesDir(dir) {
    PIPELINES_DIR = dir;
    outlet(0, "Pipelines dir: " + dir);
}

function loadPipeline(name) {
    // Read and parse the default.yaml pipeline config.
    // Max doesn't have native YAML parsing so we read it as text
    // and do lightweight parsing for the values we need.
    // For production, consider converting default.yaml to JSON.
    var path = PIPELINES_DIR + "/" + (name || "default") + ".yaml";
    var f = new File(path, "read", "text");
    if (!f.isopen) {
        outlet(0, "Pipeline not found: " + path);
        return null;
    }
    // Read full content
    var lines = [];
    f.open();
    while (!f.eof) {
        lines.push(f.readline());
    }
    f.close();
    // Store raw for lookup — parameter setting uses pipeline lookup below
    pipelineConfig[name || "default"] = lines.join("\n");
    outlet(0, "Loaded pipeline: " + (name || "default"));
}

// ── Core: load a stems.json manifest ─────────────────────────────────────────

function loadManifest(manifestPath) {
    outlet(0, "Loading: " + manifestPath);

    // Read stems.json
    var f = new File(manifestPath, "read", "text");
    if (!f.isopen) {
        outlet(0, "Cannot open: " + manifestPath);
        return;
    }
    var raw = "";
    f.open();
    while (!f.eof) { raw += f.readline() + "\n"; }
    f.close();

    var manifest;
    try {
        manifest = JSON.parse(raw);
    } catch(e) {
        outlet(0, "JSON parse error: " + e);
        return;
    }

    // Set tempo
    setBPM(manifest.bpm);

    // Load pipeline config for parameter setting
    loadPipeline(manifest.pipeline || "default");
    var pipeline = getPipelineSection(manifest.pipeline || "default");

    // Get current track count so we append after existing tracks
    var api = new LiveAPI("live_set");
    api.property = "tracks";
    var numTracks = getTrackCount();

    // Process each stem
    var stemsLoaded = 0;
    for (var i = 0; i < manifest.stems.length; i++) {
        var stemInfo = manifest.stems[i];
        if (stemInfo.name === "residual") continue;

        var stemConfig = pipeline ? pipeline[stemInfo.name] : null;
        var templateName = stemConfig ? stemConfig.template : "SF | Texture Verb";

        outlet(0, "Loading stem: " + stemInfo.name + " → " + templateName);

        var newTrackIndex = duplicateTemplate(templateName, numTracks + stemsLoaded);
        if (newTrackIndex < 0) {
            outlet(0, "Template not found: " + templateName);
            continue;
        }

        // Rename track
        var trackName = manifest.track_name + " | " + stemInfo.name;
        setTrackName(newTrackIndex, trackName);

        // Set color
        var color = stemConfig ? stemConfig.color : 0x444444;
        setTrackColor(newTrackIndex, color || 0x444444);

        // Load audio into clip slot 0
        loadAudioClip(newTrackIndex, 0, stemInfo.wav_path);

        // Set clip properties
        var warpMode = stemConfig ? WARP_MODES[stemConfig.warp_mode] || 0 : 0;
        setClipProperties(newTrackIndex, 0, {
            warp_mode: warpMode,
            looping: stemConfig ? (stemConfig.loop ? 1 : 0) : 1,
            warping: 1,
        });

        // Apply effect parameters from pipeline config
        if (stemConfig && stemConfig.effects) {
            applyEffects(newTrackIndex, stemConfig.effects);
        }

        stemsLoaded++;
    }

    // Load best beat slice into "SF | Beat Chop Simpler" if present
    loadBestBeatSlice(manifest, numTracks + stemsLoaded);

    lastLoadedManifest = manifestPath;
    outlet(0, "Loaded " + stemsLoaded + " stems — " + manifest.track_name +
              " @ " + manifest.bpm + " BPM");
    outlet(1, "bang"); // signal completion
}

// ── Live API helpers ──────────────────────────────────────────────────────────

function setBPM(bpm) {
    var api = new LiveAPI("live_set");
    api.set("tempo", bpm);
    outlet(0, "Tempo → " + bpm + " BPM");
}

function getTrackCount() {
    var api = new LiveAPI("live_set");
    return api.getcount("tracks");
}

function findTrackByName(name) {
    var count = getTrackCount();
    for (var i = 0; i < count; i++) {
        var api = new LiveAPI("live_set tracks " + i);
        var trackName = api.get("name");
        if (trackName && trackName[0] === name) {
            return i;
        }
    }
    return -1;
}

function duplicateTemplate(templateName, insertAfterIndex) {
    var templateIndex = findTrackByName(templateName);
    if (templateIndex < 0) return -1;

    // Duplicate the track via Song.duplicate_track
    var songAPI = new LiveAPI("live_set");
    songAPI.call("duplicate_track", templateIndex);

    // The new track appears at templateIndex + 1
    // We need to move it to insertAfterIndex
    // LOM doesn't have move_track, but duplicate inserts at source+1
    // Acceptable for now — tracks appear in order of stem processing
    return templateIndex + 1;
}

function setTrackName(trackIndex, name) {
    var api = new LiveAPI("live_set tracks " + trackIndex);
    api.set("name", name);
}

function setTrackColor(trackIndex, color) {
    var api = new LiveAPI("live_set tracks " + trackIndex);
    api.set("color", color);
}

function loadAudioClip(trackIndex, slotIndex, filePath) {
    // This is the key capability: ClipSlot.create_clip via file path
    // The LOM function signature: create_clip(path) on an audio track ClipSlot
    var api = new LiveAPI("live_set tracks " + trackIndex +
                          " clip_slots " + slotIndex);
    api.call("create_clip", filePath);
    // Small delay to let Live process the file
    var t = new Task(function() {}, this);
    t.schedule(200);
}

function setClipProperties(trackIndex, slotIndex, props) {
    var clipPath = "live_set tracks " + trackIndex +
                   " clip_slots " + slotIndex + " clip";
    var api = new LiveAPI(clipPath);
    if (api.id === "0") return; // clip not yet loaded

    if (props.warping !== undefined)   api.set("warping", props.warping);
    if (props.warp_mode !== undefined) api.set("warp_mode", props.warp_mode);
    if (props.looping !== undefined)   api.set("looping", props.looping);
}

function applyEffects(trackIndex, effects) {
    for (var d = 0; d < effects.length; d++) {
        var effect = effects[d];
        var deviceIndex = effect.device;
        var params = effect.params;
        if (!params) continue;

        // Get parameter list for this device
        var devicePath = "live_set tracks " + trackIndex +
                         " devices " + deviceIndex;
        var deviceAPI = new LiveAPI(devicePath);
        var paramCount = deviceAPI.getcount("parameters");

        // For each named parameter in the config, find and set it
        // Note: param matching is by index in the config (not by name)
        // The config uses descriptive keys for readability but the actual
        // setting is by sequential index in the effects[d].params object
        var paramKeys = Object.keys(params);
        for (var p = 0; p < paramKeys.length; p++) {
            var paramPath = devicePath + " parameters " + p;
            var paramAPI = new LiveAPI(paramPath);
            if (paramAPI.id !== "0") {
                paramAPI.set("value", params[paramKeys[p]]);
            }
        }
    }
}

function loadBestBeatSlice(manifest, insertIndex) {
    // Find the drums stem beat slices
    var drumsStem = null;
    for (var i = 0; i < manifest.stems.length; i++) {
        if (manifest.stems[i].name === "drums" ||
            manifest.stems[i].name === "drum") {
            drumsStem = manifest.stems[i];
            break;
        }
    }
    if (!drumsStem || !drumsStem.beats_dir) return;

    // Find Simpler template track
    var simplerIndex = findTrackByName("SF | Beat Chop Simpler");
    if (simplerIndex < 0) return;

    // Duplicate it
    var newSimpler = duplicateTemplate("SF | Beat Chop Simpler", insertIndex);
    if (newSimpler < 0) return;

    setTrackName(newSimpler, manifest.track_name + " | chop");
    setTrackColor(newSimpler, 0xFF2400);

    // Load first beat slice (beat_001.wav) into Simpler's sample slot
    // Simpler's sample parameter is typically parameter index 0
    var firstBeat = drumsStem.beats_dir + "/" +
                    drumsStem.name + "_beat_001.wav";

    // Load via Simpler's built-in load mechanism (device param 0)
    var devicePath = "live_set tracks " + newSimpler + " devices 0";
    var deviceAPI = new LiveAPI(devicePath);
    deviceAPI.call("load_device", firstBeat);
    // Note: if load_device is not available, fallback is drag-and-drop.
    // Document this limitation clearly.

    outlet(0, "Beat chop Simpler loaded: " + drumsStem.name + "_beat_001.wav");
}

// ── File watching ─────────────────────────────────────────────────────────────

function findLatestManifest(baseDir) {
    // Walk baseDir for the most recently modified stems.json
    // Max's file access is limited — we check known structure:
    // baseDir/{track_name}/stems.json
    var f = new File(baseDir);
    if (!f.isopen) return null;

    var newest = null;
    var newestTime = 0;

    // List subdirectories
    var subdirs = [];
    f.open();
    var entry;
    while ((entry = f.readdir()) !== null) {
        subdirs.push(entry);
    }
    f.close();

    for (var i = 0; i < subdirs.length; i++) {
        var manifestPath = baseDir + "/" + subdirs[i] + "/stems.json";
        var mf = new File(manifestPath);
        if (mf.isopen) {
            // Use file modification date for comparison
            // Max's File object doesn't expose mtime directly,
            // so we track by reading and comparing processed_at timestamps
            mf.open();
            var content = "";
            while (!mf.eof) { content += mf.readline() + "\n"; }
            mf.close();
            try {
                var parsed = JSON.parse(content);
                var t = new Date(parsed.processed_at).getTime();
                if (t > newestTime) {
                    newestTime = t;
                    newest = manifestPath;
                }
            } catch(e) {}
        }
    }

    return newest;
}

function scheduleWatch() {
    if (!isWatching) return;
    watchTimer = new Task(function() {
        var manifest = findLatestManifest(PROCESSED_DIR);
        if (manifest && manifest !== lastLoadedManifest) {
            outlet(0, "New stems detected: " + manifest);
            loadManifest(manifest);
        }
        scheduleWatch(); // reschedule
    }, this);
    watchTimer.schedule(POLL_INTERVAL);
}

// ── Pipeline config parsing ────────────────────────────────────────────────────

function getPipelineSection(pipelineName) {
    // Convert the loaded YAML text (stored in pipelineConfig) to a usable
    // JS object. Since Max lacks YAML parsing, the pipeline config should
    // also be distributed as a JSON file: pipelines/default.json
    // Claude Code should generate BOTH default.yaml (human-editable)
    // AND default.json (machine-readable, auto-generated from yaml on CLI run).
    // The M4L device reads default.json.

    var jsonPath = PIPELINES_DIR + "/" + pipelineName + ".json";
    var f = new File(jsonPath, "read", "text");
    if (!f.isopen) {
        outlet(0, "Pipeline JSON not found: " + jsonPath +
                  " — run: stemforge generate-pipeline-json");
        return null;
    }
    var raw = "";
    f.open();
    while (!f.eof) { raw += f.readline() + "\n"; }
    f.close();

    try {
        var config = JSON.parse(raw);
        return config.pipelines ? config.pipelines[pipelineName] ?
               config.pipelines[pipelineName].stems : null : null;
    } catch(e) {
        outlet(0, "Pipeline JSON parse error: " + e);
        return null;
    }
}
```

---

## 13. Additional CLI Command: `generate-pipeline-json`

Add this to `cli.py` so the pipeline YAML auto-converts to JSON for the M4L device:

```python
@cli.command("generate-pipeline-json")
@click.option("--pipeline-dir", default=None, type=click.Path(path_type=Path))
def generate_pipeline_json(pipeline_dir):
    """
    Convert pipelines/default.yaml → pipelines/default.json for M4L device.
    Run this after editing default.yaml.
    """
    import yaml
    p_dir = pipeline_dir or (Path(__file__).parent.parent / "pipelines")
    for yaml_file in p_dir.glob("*.yaml"):
        with open(yaml_file) as f:
            data = yaml.safe_load(f)
        json_file = yaml_file.with_suffix(".json")
        json_file.write_text(json.dumps(data, indent=2))
        console.print(f"[green]OK[/green] {yaml_file.name} → {json_file.name}")
    console.print("\nRestart or reload the M4L device to pick up changes.")
```

---

## 14. Max Patch Wrapper for the M4L Device

Claude Code must describe (in `m4l/README_M4L.md`) how to build the Max patch
wrapper around `stemforge_loader.js`. The patch itself is binary (`.amxd`), but
Claude Code should provide the patch description so it can be built in Max:

```markdown
## Max Patch Structure for StemForgeLoader.amxd

The patch contains:

[midiin] → discard (device needs to be instrument type to sit on MIDI track)

[loadbang] → [js stemforge_loader.js] (main logic)
           → [message setPipelinesDir /path/to/pipelines] (set on load)
           → [message loadPipeline default]

UI Objects:
  [umenu] "Pipeline" — lists available pipelines from PIPELINES_DIR
          → [js stemforge_loader.js] via message "loadPipeline $1"

  [toggle] "Watch" — starts/stops folder watching
           → [js stemforge_loader.js] via message "startWatch"/"stopWatch"

  [button] "Load Latest" — manual trigger
           → [bang] → [js stemforge_loader.js]

  [textedit] status — receives output from outlet 0 of js object
           displays last status message

  [number] BPM display — receives bpm from manifest after load

Connections:
  [js stemforge_loader.js] outlet 0 → [textedit] status display
  [js stemforge_loader.js] outlet 1 → [print] "Load complete"

Save as: m4l/StemForgeLoader.amxd
```

---

## 15. Acceptance Criteria

Claude Code is done when all of the following pass:

```bash
# 1. Install
pip install -e ".[local]"
python -c "from stemforge.cli import cli; print('CLI OK')"

# 2. List options
stemforge list

# 3. Split with Demucs (no API key needed)
stemforge split ~/stemforge/inbox/test.wav --backend demucs --no-slice
# → ~/stemforge/processed/test/drums.wav exists
# → ~/stemforge/processed/test/stems.json exists and is valid JSON

# 4. Split with slicing
stemforge split ~/stemforge/inbox/test.wav --backend demucs
# → ~/stemforge/processed/test/drums_beats/drums_beat_001.wav exists

# 5. Pipeline JSON generation
stemforge generate-pipeline-json
# → pipelines/default.json exists and is valid JSON

# 6. Balance check (requires LALAL key)
stemforge balance

# 7. stems.json schema validation
python -c "
from stemforge.manifest import read_manifest
from pathlib import Path
m = read_manifest(Path('~/stemforge/processed/test/stems.json').expanduser())
assert 'bpm' in m
assert 'stems' in m
assert len(m['stems']) > 0
assert 'wav_path' in m['stems'][0]
print('Manifest OK:', m['track_name'], m['bpm'], 'BPM')
"

# 8. M4L files exist
ls m4l/stemforge_loader.js
ls m4l/README_M4L.md

# 9. Pipeline files exist
ls pipelines/default.yaml
ls pipelines/default.json

# 10. Setup docs exist
ls setup.md
```

---

## 16. Known Limitations — Document These in README

1. **M4L cannot move tracks** — `Song.duplicate_track` inserts at source+1, so duplicated template tracks don't end up in a tidy group. User manually groups them after loading. A future version could use a Group Track approach.

2. **Simpler sample loading** — `load_device` may not work for all Ableton versions. Fallback: M4L opens a file dialog or user drags from browser. Document which Live 12 versions support this.

3. **VST parameter indices** — The pipeline YAML uses descriptive param names for readability, but the M4L device sets params by sequential index. Users must verify their param indices using the M4L "Inspect" workflow described in setup.md. VST param ordering can differ between plugin versions.

4. **No LO-FI-AF internal section reordering via API** — LO-FI-AF's 4-section drag-reorder is UI-only. The M4L device can set parameter values but cannot reorder Convolution/Spectral/Digital/Analog sections programmatically. Set up the order you want in the template track and it stays.

5. **Beat slicing is grid-quantized, not onset-detected** — Librosa's beat tracker gives musical beat positions, not transient onsets. IDM material with complex polyrhythms may benefit from adjusting the silence threshold or using onset detection instead. This is a future enhancement.

6. **Demucs first-run download** — First run downloads ~80MB model to `~/.cache/torch/hub/`. Normal and expected. Subsequent runs use cache.
```
