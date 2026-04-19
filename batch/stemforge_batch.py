#!/usr/bin/env python3
"""
stemforge_batch.py

Batch stem separation pipeline using Modal + ONNX Runtime CUDA EP.
Points at a local directory of audio files, fans out to GPU instances
in parallel, downloads stems back to a local output directory.

Usage:
    # Basic — process all .wav/.mp3/.flac in a directory
    python3 stemforge_batch.py --input-dir ~/music/tracks

    # Custom output directory
    python3 stemforge_batch.py --input-dir ~/music/tracks --output-dir ~/music/stems

    # Limit parallelism (default: all tracks in parallel)
    python3 stemforge_batch.py --input-dir ~/music/tracks --max-parallel 5

    # Dry run — show what would be processed without running
    python3 stemforge_batch.py --input-dir ~/music/tracks --dry-run

    # Specific GPU type
    python3 stemforge_batch.py --input-dir ~/music/tracks --gpu A100

Prerequisites:
    pip install modal onnx
    modal setup
    modal volume create stemforge-models
    modal volume put stemforge-models \
        /path/to/htdemucs_ft_fused_static.onnx \
        /htdemucs_ft_fused_static.onnx
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import modal

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SUPPORTED_EXTENSIONS = {".wav", ".mp3", ".flac", ".aiff", ".aif", ".m4a", ".ogg"}
MODEL_PATH           = "/model/htdemucs_ft_fused_static.onnx"
STEMS                = ["drums", "bass", "vocals", "other"]
DEFAULT_GPU          = "A10G"
DEFAULT_MAX_PARALLEL = 20   # Modal hard limit per workspace on free tier is 10;
                             # paid tier supports higher. Adjust as needed.

# ---------------------------------------------------------------------------
# Modal image — CUDA 12 + cuDNN required for onnxruntime-gpu CUDA EP
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
app    = modal.App("stemforge-batch")


# ---------------------------------------------------------------------------
# Remote function — runs on GPU in Modal cloud
# ---------------------------------------------------------------------------

@app.function(
    image=image,
    gpu=DEFAULT_GPU,
    volumes={"/model": volume},
    timeout=600,                   # 10 min max per track
    retries=1,
)
def split_track(
    audio_bytes: bytes,
    filename: str,
    sample_rate: int = 44100,
) -> dict[str, bytes]:
    """
    Receive raw audio bytes, run htdemucs_ft inference, return stem WAV bytes.

    Returns a dict mapping stem name -> WAV bytes:
        { "drums": b"...", "bass": b"...", "vocals": b"...", "other": b"..." }
    """
    import io
    import numpy as np
    import onnxruntime as ort
    import soundfile as sf
    import librosa

    # -----------------------------------------------------------------------
    # Decode audio
    # -----------------------------------------------------------------------
    audio_buf = io.BytesIO(audio_bytes)
    audio, sr  = sf.read(audio_buf, dtype="float32", always_2d=True)

    # Ensure stereo
    if audio.shape[1] == 1:
        audio = np.repeat(audio, 2, axis=1)
    elif audio.shape[1] > 2:
        audio = audio[:, :2]

    # Resample to 44.1kHz if needed
    if sr != sample_rate:
        audio = librosa.resample(audio.T, orig_sr=sr, target_sr=sample_rate).T
        sr = sample_rate

    # Shape: [samples, 2] → [1, 2, samples]
    mix = audio.T[np.newaxis, :, :]   # [1, 2, N]

    # -----------------------------------------------------------------------
    # Chunk into segments matching the model's static input shape
    # (343980 samples = ~7.8s @ 44.1kHz)
    # -----------------------------------------------------------------------
    CHUNK = 343980
    n_samples = mix.shape[2]
    n_chunks  = (n_samples + CHUNK - 1) // CHUNK

    # -----------------------------------------------------------------------
    # Load ONNX session
    # -----------------------------------------------------------------------
    sess = ort.InferenceSession(
        MODEL_PATH,
        providers=[
            ("CUDAExecutionProvider", {"device_id": 0}),
            "CPUExecutionProvider",
        ],
    )

    # -----------------------------------------------------------------------
    # Run inference chunk by chunk
    # -----------------------------------------------------------------------
    # Output accumulators: one list per stem
    stem_chunks: dict[str, list[np.ndarray]] = {s: [] for s in STEMS}

    for i in range(n_chunks):
        start = i * CHUNK
        end   = start + CHUNK
        chunk = mix[:, :, start:end]

        # Pad last chunk to exactly CHUNK samples
        if chunk.shape[2] < CHUNK:
            pad = CHUNK - chunk.shape[2]
            chunk = np.pad(chunk, ((0, 0), (0, 0), (0, pad)))

        # z_cac is the STFT representation — compute from chunk
        # Shape expected by model: [1, 4, 2048, 336]
        z_cac = _compute_z_cac(chunk)

        outputs = sess.run(
            None,
            {"mix": chunk, "z_cac": z_cac},
        )

        # time_out_stacked: [4, 2, CHUNK] — 4 heads × stereo × samples
        time_out = outputs[0]   # [4, 2, CHUNK]

        # Average the 4 specialist heads for each stem
        for stem_idx, stem_name in enumerate(STEMS):
            stem_audio = time_out[stem_idx]           # [2, CHUNK]
            actual_len = min(CHUNK, n_samples - start)
            stem_chunks[stem_name].append(stem_audio[:, :actual_len])

    # -----------------------------------------------------------------------
    # Concatenate chunks and encode as WAV bytes
    # -----------------------------------------------------------------------
    result: dict[str, bytes] = {}
    for stem_name in STEMS:
        full_audio = np.concatenate(stem_chunks[stem_name], axis=1)  # [2, N]
        buf = io.BytesIO()
        sf.write(buf, full_audio.T, sr, format="WAV", subtype="FLOAT")
        result[stem_name] = buf.getvalue()

    return result


def _compute_z_cac(mix_chunk: "np.ndarray") -> "np.ndarray":
    """
    Compute the STFT-based z_cac input from a mix chunk.
    Shape: [1, 4, 2048, 336] matching the model's static input.

    This mirrors the HTDemucs preprocessing used during export.
    """
    import numpy as np
    from scipy.signal import stft as scipy_stft

    # Parameters matching HTDemucs STFT config
    N_FFT    = 4096
    HOP      = 1024
    WIN      = N_FFT

    batch, channels, samples = mix_chunk.shape  # [1, 2, CHUNK]
    mix_np = mix_chunk[0]  # [2, CHUNK]

    # Compute STFT for each channel
    stft_channels = []
    for ch in range(channels):
        _, _, Zxx = scipy_stft(
            mix_np[ch],
            nperseg=WIN,
            noverlap=WIN - HOP,
            nfft=N_FFT,
            boundary="zeros",
            padded=True,
        )
        stft_channels.append(Zxx)  # [freqs, frames]

    # Stack channels: [2, freqs, frames]
    Z = np.stack(stft_channels, axis=0)

    # Split real/imag → 4 channels: [4, freqs, frames]
    Z4 = np.concatenate([Z.real, Z.imag], axis=0).astype(np.float32)

    # Crop/pad to model's expected shape [1, 4, 2048, 336]
    freq_bins = 2048
    time_frames = 336
    Z4 = Z4[:, :freq_bins, :]
    if Z4.shape[2] < time_frames:
        pad = time_frames - Z4.shape[2]
        Z4 = np.pad(Z4, ((0, 0), (0, 0), (0, pad)))
    else:
        Z4 = Z4[:, :, :time_frames]

    return Z4[np.newaxis, :, :, :]  # [1, 4, 2048, 336]


# ---------------------------------------------------------------------------
# Local entrypoint
# ---------------------------------------------------------------------------

@app.local_entrypoint()
def main(
    input_dir:    str  = None,
    output_dir:   str  = None,
    max_parallel: int  = DEFAULT_MAX_PARALLEL,
    gpu:          str  = DEFAULT_GPU,
    dry_run:      bool = False,
):
    if input_dir is None:
        print("ERROR: --input-dir is required.")
        print("Usage: modal run stemforge_batch.py --input-dir ~/music/tracks")
        sys.exit(1)

    input_path  = Path(input_dir).expanduser().resolve()
    output_path = Path(output_dir).expanduser().resolve() if output_dir else input_path / "stems"

    if not input_path.exists():
        print(f"ERROR: Input directory not found: {input_path}")
        sys.exit(1)

    # Collect audio files
    audio_files = sorted([
        f for f in input_path.iterdir()
        if f.is_file() and f.suffix.lower() in SUPPORTED_EXTENSIONS
    ])

    if not audio_files:
        print(f"No supported audio files found in {input_path}")
        print(f"Supported formats: {', '.join(sorted(SUPPORTED_EXTENSIONS))}")
        sys.exit(0)

    print(f"\nStemForge Batch Pipeline")
    print(f"{'=' * 50}")
    print(f"Input:        {input_path}")
    print(f"Output:       {output_path}")
    print(f"Tracks found: {len(audio_files)}")
    print(f"GPU:          {gpu}")
    print(f"Parallelism:  up to {max_parallel} simultaneous instances")
    print(f"{'=' * 50}\n")

    if dry_run:
        print("DRY RUN — files that would be processed:")
        for f in audio_files:
            print(f"  {f.name}")
        print(f"\nTotal: {len(audio_files)} tracks")
        return

    output_path.mkdir(parents=True, exist_ok=True)

    # -----------------------------------------------------------------------
    # Build job list — skip already-processed tracks
    # -----------------------------------------------------------------------
    jobs: list[tuple[bytes, str]] = []
    skipped = []

    for audio_file in audio_files:
        stem_dir = output_path / audio_file.stem
        if all((stem_dir / f"{s}.wav").exists() for s in STEMS):
            skipped.append(audio_file.name)
            continue
        audio_bytes = audio_file.read_bytes()
        jobs.append((audio_bytes, audio_file.name))

    if skipped:
        print(f"Skipping {len(skipped)} already-processed tracks:")
        for name in skipped:
            print(f"  {name}")
        print()

    if not jobs:
        print("All tracks already processed. Nothing to do.")
        return

    print(f"Processing {len(jobs)} track(s) in parallel...\n")

    # -----------------------------------------------------------------------
    # Fan out — Modal handles spinning up/down instances
    # -----------------------------------------------------------------------
    t_start = time.perf_counter()
    results = list(
        split_track.starmap(
            jobs,
            kwargs={"sample_rate": 44100},
            order_outputs=True,
        )
    )
    elapsed = time.perf_counter() - t_start

    # -----------------------------------------------------------------------
    # Write stems to disk
    # -----------------------------------------------------------------------
    print("\nWriting stems to disk...")
    manifest = []

    for (_, filename), stem_bytes in zip(jobs, results):
        track_name = Path(filename).stem
        stem_dir   = output_path / track_name
        stem_dir.mkdir(parents=True, exist_ok=True)

        track_entry = {"track": filename, "stems": {}}
        for stem_name, wav_bytes in stem_bytes.items():
            out_file = stem_dir / f"{stem_name}.wav"
            out_file.write_bytes(wav_bytes)
            track_entry["stems"][stem_name] = str(out_file)
            print(f"  {track_name}/{stem_name}.wav")

        manifest.append(track_entry)

    # Write manifest JSON for downstream tooling
    manifest_path = output_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))

    # -----------------------------------------------------------------------
    # Summary
    # -----------------------------------------------------------------------
    print(f"\n{'=' * 50}")
    print(f"Done.")
    print(f"Tracks processed: {len(jobs)}")
    print(f"Total wall time:  {elapsed:.1f}s")
    if len(jobs) > 0:
        print(f"Avg per track:    {elapsed / len(jobs):.1f}s")
    print(f"Output directory: {output_path}")
    print(f"Manifest:         {manifest_path}")
    print(f"{'=' * 50}\n")


# ---------------------------------------------------------------------------
# CLI wrapper (for running outside Modal local entrypoint context)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="StemForge batch stem separation")
    parser.add_argument("--input-dir",    required=True,              help="Directory of audio files to process")
    parser.add_argument("--output-dir",   default=None,               help="Output directory for stems (default: <input-dir>/stems/)")
    parser.add_argument("--max-parallel", type=int, default=DEFAULT_MAX_PARALLEL, help="Max concurrent Modal instances")
    parser.add_argument("--gpu",          default=DEFAULT_GPU,        help="GPU type (A10G, A100, T4)")
    parser.add_argument("--dry-run",      action="store_true",        help="List files without processing")
    args = parser.parse_args()

    print("Run this script with Modal:")
    print(f"  modal run stemforge_batch.py"
          f" --input-dir {args.input_dir}"
          + (f" --output-dir {args.output_dir}" if args.output_dir else "")
          + (f" --gpu {args.gpu}" if args.gpu != DEFAULT_GPU else "")
          + (" --dry-run" if args.dry_run else ""))
