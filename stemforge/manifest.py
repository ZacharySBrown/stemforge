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
