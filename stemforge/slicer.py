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


def _write_bar_slices(
    y: np.ndarray,
    sr: int,
    bar_samples: np.ndarray,
    output_dir: Path,
    stem_name: str,
    silence_threshold: float,
    normalize: bool,
    normalize_headroom_db: float = -1.0,
) -> list[Path]:
    if normalize:
        peak = float(np.max(np.abs(y)))
        if peak > 0:
            target = 10 ** (normalize_headroom_db / 20)
            y = y * (target / peak)

    slices_dir = output_dir / f"{stem_name}_bars"
    slices_dir.mkdir(parents=True, exist_ok=True)

    total_samples = y.shape[-1]
    boundaries = np.concatenate([np.asarray(bar_samples, dtype=int), [total_samples]])
    boundaries = np.clip(boundaries, 0, total_samples)

    created: list[Path] = []
    for i in range(len(boundaries) - 1):
        start, end = int(boundaries[i]), int(boundaries[i + 1])
        if end <= start:
            continue
        chunk = y[:, start:end]
        if float(np.sqrt(np.mean(chunk ** 2))) < silence_threshold:
            continue
        fname = slices_dir / f"{stem_name}_bar_{i + 1:03d}.wav"
        sf.write(str(fname), chunk.T, sr, subtype="PCM_24")
        created.append(fname)

    return created


def slice_at_bars_from_analysis(
    stem_path: Path,
    analysis: dict,
    output_dir: Path,
    stem_name: str,
    silence_threshold: float = 1e-3,
    normalize: bool = True,
) -> list[Path]:
    """
    Slice stem at bar boundaries using Ableton warp markers + time signature.
    Uses np.interp on sparse warp markers; groups beats by numerator.
    Output: {output_dir}/{stem_name}_bars/{stem_name}_bar_NNN.wav
    """
    numerator = int(analysis["time_signature"]["numerator"])
    warp_markers = analysis["warp_markers"]
    if len(warp_markers) < 2:
        raise ValueError("Need at least two warp markers for bar slicing.")

    beat_times = np.array([m["beat_time"] for m in warp_markers], dtype=float)
    sample_times = np.array([m["sample_time"] for m in warp_markers], dtype=float)

    order = np.argsort(beat_times)
    beat_times = beat_times[order]
    sample_times = sample_times[order]

    y, sr = librosa.load(str(stem_path), sr=None, mono=False)
    if y.ndim == 1:
        y = y[np.newaxis, :]

    analysis_sr = analysis.get("sample_rate")
    if analysis_sr and int(analysis_sr) != sr:
        sample_times = sample_times * (sr / float(analysis_sr))

    all_beats = np.arange(beat_times[0], beat_times[-1] + 1e-9, 1.0)
    all_samples = np.interp(all_beats, beat_times, sample_times).astype(int)
    bar_samples = all_samples[::numerator]

    return _write_bar_slices(
        y, sr, bar_samples, output_dir, stem_name,
        silence_threshold=silence_threshold, normalize=normalize,
    )


def slice_at_bars(
    stem_path: Path,
    output_dir: Path,
    stem_name: str,
    time_sig_numerator: int = 4,
    silence_threshold: float = 1e-3,
    normalize: bool = True,
    beat_times: np.ndarray = None,
) -> list[Path]:
    """
    Librosa-fallback bar slicer — detects beats then groups by numerator.
    """
    y, sr = librosa.load(str(stem_path), sr=None, mono=False)
    if y.ndim == 1:
        y = y[np.newaxis, :]

    if beat_times is None:
        _, beat_times = detect_bpm_and_beats(stem_path)

    beat_samples = librosa.time_to_samples(beat_times, sr=sr).astype(int)
    bar_samples = beat_samples[::int(time_sig_numerator)]

    return _write_bar_slices(
        y, sr, bar_samples, output_dir, stem_name,
        silence_threshold=silence_threshold, normalize=normalize,
    )
