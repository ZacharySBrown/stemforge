"""
stemforge.midi_extractor — Pitch detection, note extraction, and MIDI clip generation.

For pitched stems (bass, vocals, other), detects the melodic content and produces:
  1. Root sample — cleanest single note for chromatic Sampler playback
  2. Key detection — song key for scale-mode pad mapping
  3. Per-section MIDI clips — detected note sequences for DAW editing
  4. Scale/chromatic pad mappings — for live performance

Three bottom-half modes for quadrant layout:
  - melodic (default): 12 chromatic pads + 4 loops
  - scale: 8 in-key pads + 8 loops
  - reconstruct: 4 chromatic pads + 4 MIDI clips + 8 loops
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path

import librosa
import numpy as np
import soundfile as sf


# ── Pitch ranges per stem type ───────────────────────────────────────────

PITCH_RANGES = {
    "bass":   {"fmin": 30, "fmax": 500},
    "vocals": {"fmin": 80, "fmax": 1000},
    "other":  {"fmin": 50, "fmax": 2000},
}

# Scale templates (semitone intervals from root)
SCALE_TEMPLATES = {
    "major":     [0, 2, 4, 5, 7, 9, 11, 12],
    "minor":     [0, 2, 3, 5, 7, 8, 10, 12],
    "dorian":    [0, 2, 3, 5, 7, 9, 10, 12],
    "mixolydian": [0, 2, 4, 5, 7, 9, 10, 12],
    "pentatonic_major": [0, 2, 4, 7, 9, 12, 14, 16],
    "pentatonic_minor": [0, 3, 5, 7, 10, 12, 15, 17],
}

NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


@dataclass
class DetectedNote:
    """A single detected note event."""
    midi_note: int
    start_time: float       # seconds
    end_time: float
    duration: float         # seconds
    velocity: int           # 0-127
    confidence: float       # voiced probability


@dataclass
class MIDIClip:
    """A sequence of notes for one song section."""
    section_label: str
    notes: list[DetectedNote] = field(default_factory=list)
    duration_beats: float = 0.0

    def to_dict(self) -> dict:
        return {
            "section": self.section_label,
            "duration_beats": round(self.duration_beats, 2),
            "note_count": len(self.notes),
            "notes": [
                {
                    "midi_note": n.midi_note,
                    "note_name": midi_to_name(n.midi_note),
                    "start_time": round(n.start_time, 4),
                    "end_time": round(n.end_time, 4),
                    "duration": round(n.duration, 4),
                    "velocity": n.velocity,
                }
                for n in self.notes
            ],
        }


@dataclass
class MIDIExtractionResult:
    """Full MIDI extraction output for one stem."""
    root_sample_path: Path | None = None
    root_note: int = 60                 # MIDI note of the root sample
    detected_key: str = "C"             # e.g., "C", "G#"
    detected_mode: str = "major"        # "major" or "minor"
    note_range: tuple[int, int] = (36, 72)  # (low, high) MIDI notes detected
    clips: list[MIDIClip] = field(default_factory=list)
    chromatic_pads: list[dict] = field(default_factory=list)    # for melodic mode
    scale_pads: list[dict] = field(default_factory=list)        # for scale mode

    def to_dict(self) -> dict:
        return {
            "root_sample": str(self.root_sample_path) if self.root_sample_path else None,
            "root_note": self.root_note,
            "root_note_name": midi_to_name(self.root_note),
            "detected_key": self.detected_key,
            "detected_mode": self.detected_mode,
            "note_range": {
                "low": self.note_range[0],
                "low_name": midi_to_name(self.note_range[0]),
                "high": self.note_range[1],
                "high_name": midi_to_name(self.note_range[1]),
            },
            "clips": [c.to_dict() for c in self.clips],
            "chromatic_pads": self.chromatic_pads,
            "scale_pads": self.scale_pads,
        }


# ── Utility functions ────────────────────────────────────────────────────

def midi_to_name(midi_note: int) -> str:
    """Convert MIDI note number to name (e.g., 60 → 'C4')."""
    octave = (midi_note // 12) - 1
    note = NOTE_NAMES[midi_note % 12]
    return f"{note}{octave}"


def hz_to_midi(freq: float) -> int:
    """Convert frequency in Hz to nearest MIDI note number."""
    if freq <= 0:
        return 0
    return int(round(12 * np.log2(freq / 440.0) + 69))


def midi_to_hz(midi_note: int) -> float:
    """Convert MIDI note number to frequency in Hz."""
    return 440.0 * (2 ** ((midi_note - 69) / 12))


# ── Core pitch detection ─────────────────────────────────────────────────

def detect_pitches(
    audio_path: Path,
    stem_name: str = "bass",
    sr: int = 22050,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, int]:
    """
    Detect pitches using pyin (probabilistic YIN).

    Returns:
        f0: fundamental frequency per frame (Hz, NaN for unvoiced)
        voiced_flag: boolean per frame
        voiced_prob: probability per frame
        sr: sample rate used
    """
    y, sr = librosa.load(str(audio_path), sr=sr, mono=True)

    pitch_range = PITCH_RANGES.get(stem_name, PITCH_RANGES["other"])
    f0, voiced_flag, voiced_prob = librosa.pyin(
        y, sr=sr,
        fmin=pitch_range["fmin"],
        fmax=pitch_range["fmax"],
    )

    return f0, voiced_flag, voiced_prob, sr


def segment_notes(
    f0: np.ndarray,
    voiced_flag: np.ndarray,
    voiced_prob: np.ndarray,
    sr: int,
    hop_length: int = 512,
    min_duration_s: float = 0.05,
    quantize: str | None = None,
    bpm: float = 120.0,
) -> list[DetectedNote]:
    """
    Group continuous voiced frames into discrete note events.

    Args:
        f0: frequency per frame (NaN = unvoiced)
        voiced_flag: boolean voiced/unvoiced per frame
        voiced_prob: voiced probability per frame
        sr: sample rate
        hop_length: frames to samples conversion
        min_duration_s: reject notes shorter than this
        quantize: grid quantization (None, "1/16", "1/8")
        bpm: tempo for quantization
    """
    notes: list[DetectedNote] = []
    n_frames = len(f0)

    # Frame times
    times = librosa.frames_to_time(np.arange(n_frames), sr=sr, hop_length=hop_length)

    # Walk through frames, grouping voiced regions with consistent pitch
    i = 0
    while i < n_frames:
        # Skip unvoiced
        if not voiced_flag[i] or np.isnan(f0[i]):
            i += 1
            continue

        # Start of a note
        start_frame = i
        current_midi = hz_to_midi(f0[i])
        confidences = [voiced_prob[i]]

        # Extend while same MIDI note and voiced
        while i < n_frames and voiced_flag[i] and not np.isnan(f0[i]):
            frame_midi = hz_to_midi(f0[i])
            if frame_midi != current_midi:
                break
            confidences.append(voiced_prob[i])
            i += 1

        end_frame = i
        start_time = float(times[start_frame])
        end_time = float(times[min(end_frame, n_frames - 1)])
        duration = end_time - start_time

        if duration < min_duration_s:
            continue

        # Velocity from mean voiced probability (0-1 → 0-127)
        mean_conf = float(np.mean(confidences))
        velocity = max(1, min(127, int(mean_conf * 127)))

        notes.append(DetectedNote(
            midi_note=current_midi,
            start_time=start_time,
            end_time=end_time,
            duration=duration,
            velocity=velocity,
            confidence=mean_conf,
        ))

    # Optional quantization
    if quantize and bpm > 0:
        grid_map = {"1/16": 0.25, "1/8": 0.5, "1/4": 1.0}
        grid_beats = grid_map.get(quantize, 0.25)
        grid_seconds = (60.0 / bpm) * grid_beats
        for note in notes:
            note.start_time = round(note.start_time / grid_seconds) * grid_seconds
            note.end_time = max(note.start_time + 0.01,
                               round(note.end_time / grid_seconds) * grid_seconds)
            note.duration = note.end_time - note.start_time

    return notes


# ── Root sample extraction ───────────────────────────────────────────────

def extract_root_sample(
    audio_path: Path,
    notes: list[DetectedNote],
    output_path: Path,
    sr: int = 22050,
    pre_attack_s: float = 0.01,
    max_duration_s: float = 2.0,
) -> tuple[Path, int]:
    """
    Extract the cleanest single note occurrence for Sampler use.

    Picks the note with highest confidence + longest sustain + highest velocity.
    Returns (output_path, root_midi_note).
    """
    if not notes:
        return output_path, 60

    # Score each note: confidence * duration * velocity
    scored = sorted(notes, key=lambda n: n.confidence * n.duration * n.velocity, reverse=True)
    best = scored[0]

    y, file_sr = librosa.load(str(audio_path), sr=None, mono=False)
    if y.ndim == 1:
        y = y[np.newaxis, :]

    start_sample = max(0, int((best.start_time - pre_attack_s) * file_sr))
    end_sample = min(y.shape[-1], int((best.start_time + max_duration_s) * file_sr))
    chunk = y[:, start_sample:end_sample]

    # Apply fade-out
    fade_samples = min(int(0.05 * file_sr), chunk.shape[-1] // 4)
    if fade_samples > 0:
        fade = np.linspace(1, 0, fade_samples)
        chunk[:, -fade_samples:] *= fade

    # Peak normalize
    peak = np.max(np.abs(chunk))
    if peak > 0:
        chunk = chunk * (0.891 / peak)  # -1dB headroom

    output_path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(output_path), chunk.T, file_sr, subtype="PCM_24")

    return output_path, best.midi_note


# ── Key detection ────────────────────────────────────────────────────────

def detect_key(audio_path: Path, sr: int = 22050) -> tuple[str, str]:
    """
    Detect song key using chroma features.

    Returns (key_name, mode) e.g. ("C", "major") or ("A", "minor").
    """
    y, sr = librosa.load(str(audio_path), sr=sr, mono=True)
    chroma = librosa.feature.chroma_cqt(y=y, sr=sr)
    chroma_mean = chroma.mean(axis=1)

    # Correlate with major and minor profiles (Krumhansl-Kessler)
    major_profile = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
    minor_profile = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])

    best_key = 0
    best_mode = "major"
    best_corr = -1

    for shift in range(12):
        shifted = np.roll(chroma_mean, -shift)
        corr_major = float(np.corrcoef(shifted, major_profile)[0, 1])
        corr_minor = float(np.corrcoef(shifted, minor_profile)[0, 1])

        if corr_major > best_corr:
            best_corr = corr_major
            best_key = shift
            best_mode = "major"
        if corr_minor > best_corr:
            best_corr = corr_minor
            best_key = shift
            best_mode = "minor"

    return NOTE_NAMES[best_key], best_mode


# ── Pad mapping generators ──────────────────────────────────────────────

def build_chromatic_pads(root_note: int, n_pads: int = 12) -> list[dict]:
    """Build chromatic pad mapping: 12 semitones starting from root."""
    pads = []
    for i in range(n_pads):
        midi = root_note + i
        pads.append({
            "pad_offset": i,
            "midi_note": midi,
            "note_name": midi_to_name(midi),
            "freq_hz": round(midi_to_hz(midi), 2),
        })
    return pads


def build_scale_pads(
    root_note: int,
    key: str,
    mode: str,
    n_pads: int = 8,
) -> list[dict]:
    """Build scale-degree pad mapping: 8 notes in the detected key."""
    # Find scale template
    if mode == "minor":
        template = SCALE_TEMPLATES["minor"]
    else:
        template = SCALE_TEMPLATES["major"]

    # Offset root to the detected key
    key_offset = NOTE_NAMES.index(key) if key in NOTE_NAMES else 0
    base = root_note - (root_note % 12) + key_offset
    if base > root_note:
        base -= 12

    pads = []
    for i in range(min(n_pads, len(template))):
        midi = base + template[i]
        degree = i + 1
        pads.append({
            "pad_offset": i,
            "midi_note": midi,
            "note_name": midi_to_name(midi),
            "freq_hz": round(midi_to_hz(midi), 2),
            "scale_degree": degree,
        })
    return pads


# ── Section-aware MIDI clip generation ───────────────────────────────────

def split_notes_by_sections(
    notes: list[DetectedNote],
    song_structure: "SongStructure | None",
    bar_times: np.ndarray | None = None,
) -> list[MIDIClip]:
    """Split detected notes into per-section MIDI clips."""
    if song_structure is None or not song_structure.segments:
        # No structure — one clip with all notes
        return [MIDIClip(section_label="full", notes=notes)]

    clips = []
    for seg in song_structure.segments:
        section_notes = [
            n for n in notes
            if n.start_time >= seg.start_time and n.start_time < seg.end_time
        ]
        if section_notes:
            # Offset note times to be relative to section start
            adjusted = []
            for n in section_notes:
                adjusted.append(DetectedNote(
                    midi_note=n.midi_note,
                    start_time=n.start_time - seg.start_time,
                    end_time=n.end_time - seg.start_time,
                    duration=n.duration,
                    velocity=n.velocity,
                    confidence=n.confidence,
                ))
            clips.append(MIDIClip(
                section_label=seg.label,
                notes=adjusted,
                duration_beats=(seg.end_time - seg.start_time),
            ))

    return clips


# ── Main extraction function ─────────────────────────────────────────────

def extract_midi(
    stem_path: Path,
    output_dir: Path,
    stem_name: str = "bass",
    bpm: float = 120.0,
    quantize: str | None = "1/16",
    chromatic_root: str = "auto",
    song_structure: "SongStructure | None" = None,
) -> MIDIExtractionResult:
    """
    Full MIDI extraction pipeline for a pitched stem.

    Args:
        stem_path: Path to the stem WAV
        output_dir: Where to write root sample + MIDI clip JSONs
        stem_name: "bass", "vocals", "other"
        bpm: Song tempo (for quantization)
        quantize: Grid quantization (None, "1/16", "1/8")
        chromatic_root: "auto" or specific note like "C2"
        song_structure: Optional SongStructure for section-aware clips

    Returns:
        MIDIExtractionResult with root sample, key, clips, and pad mappings
    """
    midi_dir = output_dir / "midi"
    midi_dir.mkdir(parents=True, exist_ok=True)

    # Step 1: Detect pitches
    f0, voiced, voiced_prob, sr = detect_pitches(stem_path, stem_name)

    # Step 2: Segment into notes
    notes = segment_notes(
        f0, voiced, voiced_prob, sr,
        quantize=quantize, bpm=bpm,
    )

    if not notes:
        return MIDIExtractionResult()

    # Step 3: Extract root sample
    root_path = midi_dir / f"{stem_name}_root.wav"
    root_path, root_midi = extract_root_sample(stem_path, notes, root_path)

    # Override root if specified
    if chromatic_root != "auto":
        # Parse note name like "C2" → MIDI number
        for i, name in enumerate(NOTE_NAMES):
            if chromatic_root.startswith(name):
                octave = int(chromatic_root[len(name):]) if len(chromatic_root) > len(name) else 2
                root_midi = (octave + 1) * 12 + i
                break

    # Step 4: Detect key
    key, mode = detect_key(stem_path)

    # Step 5: Note range
    midi_notes = [n.midi_note for n in notes]
    note_range = (min(midi_notes), max(midi_notes))

    # Step 6: Build pad mappings
    chromatic_pads = build_chromatic_pads(root_midi, n_pads=12)
    scale_pads = build_scale_pads(root_midi, key, mode, n_pads=8)

    # Step 7: Split notes by song sections
    clips = split_notes_by_sections(notes, song_structure)

    # Write MIDI clips as JSON
    for clip in clips:
        clip_path = midi_dir / f"section_{clip.section_label}.json"
        clip_path.write_text(json.dumps(clip.to_dict(), indent=2))

    # Write summary manifest
    result = MIDIExtractionResult(
        root_sample_path=root_path,
        root_note=root_midi,
        detected_key=key,
        detected_mode=mode,
        note_range=note_range,
        clips=clips,
        chromatic_pads=chromatic_pads,
        scale_pads=scale_pads,
    )

    manifest = result.to_dict()
    (midi_dir / "midi_manifest.json").write_text(json.dumps(manifest, indent=2))

    return result
