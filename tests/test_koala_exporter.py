"""
Tests for the Koala exporter.

Builds a synthetic `curated/` directory matching the structure documented in
the bel/ README, then exercises the exporter against it. No real audio
content is needed — the exporter does file copy + zip, never decodes audio.
"""

from __future__ import annotations

import json
import wave
import zipfile
from pathlib import Path

import pytest

from stemforge.exporters.koala import (
    LOOPS_BANK_PADS,
    PADS_PER_BANK,
    KoalaExportConfig,
    export_koala,
)


# ------------------------- fixture builder -------------------------


def _write_silent_wav(path: Path, duration_sec: float = 0.1) -> None:
    """Write a minimal valid WAV file (silent, mono, 16-bit, 44.1k)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    sample_rate = 44100
    n_frames = int(sample_rate * duration_sec)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(b"\x00\x00" * n_frames)


@pytest.fixture
def curated_dir(tmp_path: Path) -> Path:
    """
    Build a synthetic processed/bel/curated/ matching the bel README layout.

    Includes:
      - 14 loops per stem (the README says n_bars=14)
      - drum substems (5 parts)
      - oneshots: 12 kicks, 8 snares, 6 hihats, 3 toms, 4 cymbals
      - manifest.json in shape A (stems-keyed dict)
    """
    project = tmp_path / "processed" / "bel"
    curated = project / "curated"

    stems = ("drums", "bass", "other", "vocals")
    loops_per_stem = 14

    manifest_stems: dict[str, list[dict]] = {s: [] for s in stems}
    for stem in stems:
        for i in range(1, loops_per_stem + 1):
            fname = f"{stem}_loop_{i:02d}.wav"
            _write_silent_wav(curated / stem / fname)
            manifest_stems[stem].append({"file": fname, "rank": i})

    # Drum substems
    for part in ("kick", "snare", "hihat", "toms", "cymbals"):
        _write_silent_wav(curated / "drum_substems" / f"{part}.wav")

    # Oneshots — uneven counts to exercise the "pack to fill" logic
    oneshot_counts = {"kick": 12, "snare": 8, "hihat": 6, "toms": 3, "cymbals": 4}
    for part, count in oneshot_counts.items():
        for i in range(1, count + 1):
            _write_silent_wav(
                curated / f"{part}_oneshots" / f"{part}_oneshot_{i:03d}.wav"
            )

    manifest = {"bpm": 126.05, "n_bars": loops_per_stem, "stems": manifest_stems}
    (curated / "manifest.json").write_text(json.dumps(manifest, indent=2))

    return curated


# ------------------------- tests -------------------------


def test_export_produces_zip(curated_dir: Path, tmp_path: Path) -> None:
    config = KoalaExportConfig(output_dir=tmp_path / "out")
    zip_path = export_koala(curated_dir, config)

    assert zip_path.exists()
    assert zip_path.suffix == ".zip"
    assert zip_path.name == "bel_koala.zip"


def test_zip_contains_both_banks(curated_dir: Path, tmp_path: Path) -> None:
    config = KoalaExportConfig(output_dir=tmp_path / "out")
    zip_path = export_koala(curated_dir, config)

    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()

    assert any("bank_01_loops/" in n for n in names)
    assert any("bank_02_kit/" in n for n in names)
    assert any("README.txt" in n for n in names)


def test_bank_01_uses_correct_pad_layout(curated_dir: Path, tmp_path: Path) -> None:
    """4 stems × 4 loops = pads 01..16, with stem-grouped rows."""
    config = KoalaExportConfig(loops_per_stem=4, output_dir=tmp_path / "out")
    zip_path = export_koala(curated_dir, config)

    with zipfile.ZipFile(zip_path) as zf:
        bank_01 = sorted(n for n in zf.namelist() if "bank_01_loops/" in n and n.endswith(".wav"))

    bank_01_basenames = [Path(n).name for n in bank_01]
    # Drums on pads 01-04
    assert bank_01_basenames[0].startswith("01_drums")
    assert bank_01_basenames[3].startswith("04_drums")
    # Bass on 05-08
    assert bank_01_basenames[4].startswith("05_bass")
    assert bank_01_basenames[7].startswith("08_bass")
    # Vocals on 13-16
    assert bank_01_basenames[12].startswith("13_vocals")
    assert bank_01_basenames[15].startswith("16_vocals")


def test_bank_02_substems_first_then_oneshots(
    curated_dir: Path, tmp_path: Path
) -> None:
    config = KoalaExportConfig(output_dir=tmp_path / "out")
    zip_path = export_koala(curated_dir, config)

    with zipfile.ZipFile(zip_path) as zf:
        bank_02 = sorted(n for n in zf.namelist() if "bank_02_kit/" in n and n.endswith(".wav"))

    basenames = [Path(n).name for n in bank_02]
    # Pads 1-5 are substems
    assert basenames[0] == "01_kick.wav"
    assert basenames[1] == "02_snare.wav"
    assert basenames[2] == "03_hihat.wav"
    assert basenames[3] == "04_toms.wav"
    assert basenames[4] == "05_cymbals.wav"
    # Pad 6+ are oneshots
    assert "oneshot" in basenames[5]


def test_bank_02_does_not_exceed_pad_limit(curated_dir: Path, tmp_path: Path) -> None:
    config = KoalaExportConfig(output_dir=tmp_path / "out")
    zip_path = export_koala(curated_dir, config)

    with zipfile.ZipFile(zip_path) as zf:
        bank_02_files = [n for n in zf.namelist() if "bank_02_kit/" in n and n.endswith(".wav")]

    assert len(bank_02_files) <= PADS_PER_BANK


def test_loops_per_stem_validation(curated_dir: Path, tmp_path: Path) -> None:
    """4 stems × 5 = 20 > 16 pads → should raise."""
    config = KoalaExportConfig(loops_per_stem=5, output_dir=tmp_path / "out")
    with pytest.raises(ValueError, match="exceeds"):
        export_koala(curated_dir, config)


def test_missing_manifest_raises(tmp_path: Path) -> None:
    empty_curated = tmp_path / "empty" / "curated"
    empty_curated.mkdir(parents=True)
    with pytest.raises(FileNotFoundError, match="manifest.json"):
        export_koala(empty_curated, KoalaExportConfig(output_dir=tmp_path / "out"))


def test_keep_unzipped_leaves_staging(curated_dir: Path, tmp_path: Path) -> None:
    out = tmp_path / "out"
    config = KoalaExportConfig(output_dir=out, keep_unzipped=True)
    export_koala(curated_dir, config)

    assert (out / "bel_koala").is_dir()
    assert (out / "bel_koala" / "bank_01_loops").is_dir()


def test_oneshots_per_part_cap(curated_dir: Path, tmp_path: Path) -> None:
    config = KoalaExportConfig(oneshots_per_part=2, output_dir=tmp_path / "out")
    zip_path = export_koala(curated_dir, config)

    with zipfile.ZipFile(zip_path) as zf:
        kick_oneshots = [n for n in zf.namelist() if "kick_oneshot" in n]

    assert len(kick_oneshots) == 2


def test_readme_includes_bpm(curated_dir: Path, tmp_path: Path) -> None:
    config = KoalaExportConfig(output_dir=tmp_path / "out")
    zip_path = export_koala(curated_dir, config)

    with zipfile.ZipFile(zip_path) as zf:
        readme = zf.read(next(n for n in zf.namelist() if n.endswith("README.txt")))

    assert b"126.05" in readme
