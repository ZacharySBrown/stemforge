#!/usr/bin/env python3
"""
run_batch.py — Drop tracks in a folder, split them on Modal GPUs in batches of 20.

Usage:
    # Put your audio files in ~/stemforge-input/ (or any folder), then:
    modal run batch/run_batch.py --input-dir ~/stemforge-input

    # Custom output + batch size:
    modal run batch/run_batch.py --input-dir ~/stemforge-input --output-dir ~/stems --batch-size 10

    # Dry run — see what would be processed:
    modal run batch/run_batch.py --input-dir ~/stemforge-input --dry-run

    # Pick a GPU (A10G default, A100 for speed, T4 for cheap):
    modal run batch/run_batch.py --input-dir ~/stemforge-input --gpu A100

Prerequisites:
    pip install modal
    modal setup
    modal volume create stemforge-models
    modal volume put stemforge-models /path/to/htdemucs_ft_fused_static.onnx /htdemucs_ft_fused_static.onnx
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import modal

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

SUPPORTED_EXTENSIONS = {".wav", ".mp3", ".flac", ".aiff", ".aif", ".m4a", ".ogg"}
MODEL_PATH           = "/model/htdemucs_ft_fused_static.onnx"
STEMS                = ["drums", "bass", "vocals", "other"]
DEFAULT_GPU          = "A10G"
DEFAULT_BATCH_SIZE   = 20

# ---------------------------------------------------------------------------
# Modal setup — same image + volume as stemforge_batch.py
# ---------------------------------------------------------------------------

image = (
    modal.Image.from_registry(
        "nvidia/cuda:12.4.1-cudnn-runtime-ubuntu22.04",
        add_python="3.11",
    )
    .pip_install(
        "onnxruntime-gpu==1.24.4",
        "numpy",
        "soundfile",
        "librosa",
        "scipy",
    )
)

volume = modal.Volume.from_name("stemforge-models")
app    = modal.App("stemforge-first-run")


# ---------------------------------------------------------------------------
# Remote GPU function (identical to stemforge_batch.py)
# ---------------------------------------------------------------------------

@app.function(
    image=image,
    gpu=DEFAULT_GPU,
    volumes={"/model": volume},
    timeout=600,
    retries=1,
)
def split_track(
    audio_bytes: bytes,
    filename: str,
    sample_rate: int = 44100,
) -> dict[str, bytes]:
    """Run htdemucs_ft ONNX inference on GPU. Returns {stem_name: wav_bytes}."""
    import io
    import numpy as np
    import onnxruntime as ort
    import soundfile as sf
    import librosa
    from scipy.signal import stft as scipy_stft

    # -- Decode audio --------------------------------------------------------
    audio, sr = sf.read(io.BytesIO(audio_bytes), dtype="float32", always_2d=True)

    if audio.shape[1] == 1:
        audio = np.repeat(audio, 2, axis=1)
    elif audio.shape[1] > 2:
        audio = audio[:, :2]

    if sr != sample_rate:
        audio = librosa.resample(audio.T, orig_sr=sr, target_sr=sample_rate).T
        sr = sample_rate

    mix = audio.T[np.newaxis, :, :]  # [1, 2, N]

    # -- Chunk into model segments -------------------------------------------
    CHUNK = 343980  # ~7.8s @ 44.1kHz
    n_samples = mix.shape[2]
    n_chunks  = (n_samples + CHUNK - 1) // CHUNK

    # -- z_cac helper --------------------------------------------------------
    def compute_z_cac(chunk):
        N_FFT, HOP, WIN = 4096, 1024, 4096
        mix_np = chunk[0]  # [2, CHUNK]
        stft_channels = []
        for ch in range(mix_np.shape[0]):
            _, _, Zxx = scipy_stft(
                mix_np[ch], nperseg=WIN, noverlap=WIN - HOP,
                nfft=N_FFT, boundary="zeros", padded=True,
            )
            stft_channels.append(Zxx)
        Z = np.stack(stft_channels, axis=0)
        Z4 = np.concatenate([Z.real, Z.imag], axis=0).astype(np.float32)
        Z4 = Z4[:, :2048, :]
        if Z4.shape[2] < 336:
            Z4 = np.pad(Z4, ((0, 0), (0, 0), (0, 336 - Z4.shape[2])))
        else:
            Z4 = Z4[:, :, :336]
        return Z4[np.newaxis, :, :, :]

    # -- Load model + run inference ------------------------------------------
    sess = ort.InferenceSession(
        MODEL_PATH,
        providers=[("CUDAExecutionProvider", {"device_id": 0}), "CPUExecutionProvider"],
    )

    stem_chunks: dict[str, list[np.ndarray]] = {s: [] for s in STEMS}
    for i in range(n_chunks):
        start = i * CHUNK
        chunk = mix[:, :, start:start + CHUNK]
        if chunk.shape[2] < CHUNK:
            chunk = np.pad(chunk, ((0, 0), (0, 0), (0, CHUNK - chunk.shape[2])))
        z_cac = compute_z_cac(chunk)
        outputs = sess.run(None, {"mix": chunk, "z_cac": z_cac})
        time_out = outputs[0]  # [4, 2, CHUNK]
        actual_len = min(CHUNK, n_samples - start)
        for idx, name in enumerate(STEMS):
            stem_chunks[name].append(time_out[idx][:, :actual_len])

    # -- Encode stems as WAV -------------------------------------------------
    result: dict[str, bytes] = {}
    for stem_name in STEMS:
        full = np.concatenate(stem_chunks[stem_name], axis=1)
        buf = io.BytesIO()
        sf.write(buf, full.T, sr, format="WAV", subtype="FLOAT")
        result[stem_name] = buf.getvalue()
    return result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def collect_audio_files(input_path: Path) -> list[Path]:
    """Recursively find audio files, sorted by name."""
    files = []
    for f in sorted(input_path.rglob("*")):
        if f.is_file() and f.suffix.lower() in SUPPORTED_EXTENSIONS:
            files.append(f)
    return files


def is_already_processed(track_path: Path, output_path: Path) -> bool:
    """Check if all 4 stems already exist for this track."""
    stem_dir = output_path / track_path.stem
    return all((stem_dir / f"{s}.wav").exists() for s in STEMS)


def format_duration(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.1f}s"
    m, s = divmod(int(seconds), 60)
    return f"{m}m {s}s"


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

@app.local_entrypoint()
def main(
    input_dir:  str  = None,
    output_dir: str  = None,
    batch_size: int  = DEFAULT_BATCH_SIZE,
    gpu:        str  = DEFAULT_GPU,
    dry_run:    bool = False,
):
    if input_dir is None:
        print("Usage: modal run batch/run_batch.py --input-dir ~/stemforge-input")
        sys.exit(1)

    input_path  = Path(input_dir).expanduser().resolve()
    output_path = (Path(output_dir).expanduser().resolve() if output_dir
                   else input_path / "stems")

    if not input_path.exists():
        print(f"ERROR: Not found: {input_path}")
        sys.exit(1)

    # -- Collect + filter ----------------------------------------------------
    all_files = collect_audio_files(input_path)
    if not all_files:
        print(f"No audio files found in {input_path}")
        print(f"Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}")
        sys.exit(0)

    skipped = [f for f in all_files if is_already_processed(f, output_path)]
    to_process = [f for f in all_files if not is_already_processed(f, output_path)]

    # -- Header --------------------------------------------------------------
    print()
    print("  ____  _                 _____                    ")
    print(" / ___|| |_ ___ _ __ ___ |  ___|__  _ __ __ _  ___ ")
    print(" \\___ \\| __/ _ \\ '_ ` _ \\| |_ / _ \\| '__/ _` |/ _ \\")
    print("  ___) | ||  __/ | | | | |  _| (_) | | | (_| |  __/")
    print(" |____/ \\__\\___|_| |_| |_|_|  \\___/|_|  \\__, |\\___|")
    print("                                         |___/      ")
    print(f"  Batch Runner — {len(all_files)} tracks found")
    print()
    print(f"  Input:      {input_path}")
    print(f"  Output:     {output_path}")
    print(f"  GPU:        {gpu}")
    print(f"  Batch size: {batch_size}")
    if skipped:
        print(f"  Skipping:   {len(skipped)} already processed")
    print(f"  To process: {len(to_process)} tracks")
    print()

    if dry_run:
        print("DRY RUN — would process:\n")
        for i, f in enumerate(to_process, 1):
            print(f"  {i:3d}. {f.name}")
        print(f"\n  {len(to_process)} tracks in {(len(to_process) + batch_size - 1) // batch_size} batches of {batch_size}")
        return

    if not to_process:
        print("All tracks already processed. Nothing to do.")
        return

    output_path.mkdir(parents=True, exist_ok=True)

    # -- Process in batches --------------------------------------------------
    n_batches = (len(to_process) + batch_size - 1) // batch_size
    manifest = []
    total_start = time.perf_counter()
    tracks_done = 0
    tracks_failed = 0

    for batch_idx in range(n_batches):
        batch_start_idx = batch_idx * batch_size
        batch_files = to_process[batch_start_idx : batch_start_idx + batch_size]

        print(f"{'=' * 60}")
        print(f"  BATCH {batch_idx + 1}/{n_batches}  —  {len(batch_files)} tracks")
        print(f"{'=' * 60}")
        for f in batch_files:
            print(f"    {f.name}")
        print()

        # Read audio bytes
        jobs: list[tuple[bytes, str]] = []
        for audio_file in batch_files:
            jobs.append((audio_file.read_bytes(), audio_file.name))

        # Fan out to Modal GPUs
        batch_start = time.perf_counter()
        try:
            results = list(
                split_track.starmap(
                    jobs,
                    kwargs={"sample_rate": 44100},
                    order_outputs=True,
                )
            )
        except Exception as e:
            print(f"\n  ERROR in batch {batch_idx + 1}: {e}")
            tracks_failed += len(batch_files)
            print("  Continuing to next batch...\n")
            continue

        batch_elapsed = time.perf_counter() - batch_start

        # Write stems to disk
        for (_, filename), stem_bytes in zip(jobs, results):
            track_name = Path(filename).stem
            stem_dir   = output_path / track_name
            stem_dir.mkdir(parents=True, exist_ok=True)

            track_entry = {"track": filename, "stems": {}}
            for stem_name, wav_bytes in stem_bytes.items():
                out_file = stem_dir / f"{stem_name}.wav"
                out_file.write_bytes(wav_bytes)
                track_entry["stems"][stem_name] = str(out_file.relative_to(output_path))

            manifest.append(track_entry)
            tracks_done += 1

        print(f"  Batch {batch_idx + 1} done in {format_duration(batch_elapsed)}"
              f"  ({batch_elapsed / len(batch_files):.1f}s avg/track)")

        # Running totals
        total_elapsed = time.perf_counter() - total_start
        remaining = len(to_process) - (batch_start_idx + len(batch_files))
        if remaining > 0 and tracks_done > 0:
            eta = (total_elapsed / tracks_done) * remaining
            print(f"  Progress: {tracks_done}/{len(to_process)} done"
                  f"  —  ~{format_duration(eta)} remaining")
        print()

    # -- Write combined manifest ---------------------------------------------
    manifest_path = output_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))

    # -- Final summary -------------------------------------------------------
    total_elapsed = time.perf_counter() - total_start
    print(f"{'=' * 60}")
    print(f"  ALL DONE")
    print(f"{'=' * 60}")
    print(f"  Tracks processed: {tracks_done}")
    if tracks_failed:
        print(f"  Tracks failed:    {tracks_failed}")
    print(f"  Total wall time:  {format_duration(total_elapsed)}")
    if tracks_done > 0:
        print(f"  Avg per track:    {total_elapsed / tracks_done:.1f}s")
    print(f"  Output:           {output_path}")
    print(f"  Manifest:         {manifest_path}")
    print(f"{'=' * 60}")
    print()
    print(f"  Stems ready for StemForge pipeline or direct Ableton import.")
    print()
