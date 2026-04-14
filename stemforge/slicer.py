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
    silence_threshold: float = 1e-3,
    normalize: bool = True,
    normalize_headroom_db: float = -1.0,
    beats_per_slice: int = 1,
) -> list[Path]:
    """
    Slice stem WAV at beat boundaries.
    Output: {output_dir}/{stem_name}_beats/{stem_name}_beat_NNN.wav
    Skips near-silent chunks (saves space, avoids empty Drum Rack pads).
    If normalize=True, peak-normalizes the stem before slicing so all
    beat slices share a consistent level across stems.
    beats_per_slice: how many beats per output file (1 = individual beats,
                     4 = bars in 4/4 time, etc.)
    Returns list of created file paths.
    """
    y, sr = librosa.load(str(stem_path), sr=None, mono=False)
    if y.ndim == 1:
        y = y[np.newaxis, :]  # (1, samples)

    # Peak-normalize: scale so the loudest sample hits headroom target
    if normalize:
        peak = np.max(np.abs(y))
        if peak > 0:
            target = 10 ** (normalize_headroom_db / 20)  # e.g. -1dB → 0.891
            y = y * (target / peak)

    slices_dir = output_dir / f"{stem_name}_beats"
    slices_dir.mkdir(parents=True, exist_ok=True)

    total_samples = y.shape[-1]
    beat_samples = librosa.time_to_samples(beat_times, sr=sr).astype(int)

    # Group beats into slices of beats_per_slice
    bar_boundaries = beat_samples[::beats_per_slice]
    boundaries = np.concatenate([bar_boundaries, [total_samples]]).astype(int)
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
