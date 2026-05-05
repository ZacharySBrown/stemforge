"""
Koala Sampler exporter.

Takes a stemforge `curated/` directory (the output of `stemforge curate`) and
produces a zip ready for one-tap iOS import via the "Send to Koala Sampler"
Shortcut (https://routinehub.co/shortcut/7308/) or AirDrop → Files.app.

The zip contains two bank-folders, each laid out so that filename order
controls Koala pad assignment:

    {project}_koala/
    ├── bank_01_loops/      ← 4-bar curated loops, 4 stems × up to 4 each = 16 pads
    │   ├── 01_drums_01.wav
    │   ├── 02_drums_02.wav
    │   ├── ...
    │   └── 16_vocals_04.wav
    ├── bank_02_kit/        ← drum substems (5) + oneshots filling to 64 pads
    │   ├── 01_kick.wav
    │   ├── 02_snare.wav
    │   ├── 03_hihat.wav
    │   ├── 04_toms.wav
    │   ├── 05_cymbals.wav
    │   ├── 06_kick_oneshot_01.wav
    │   └── ... (oneshots, ranked, capped to fill the bank)
    └── README.txt

Koala loads any audio format the OS can play, so we passthrough the curated
WAVs untouched (no resample, no bit-depth change). Filenames are zero-padded
2-digit numbered prefixes which give Koala a deterministic pad assignment
when the user multi-selects the folder contents and drags onto the top-left
empty pad in the Samples Browser.
"""

from __future__ import annotations

import json
import shutil
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

# Koala hard limits (per the manual)
PADS_PER_BANK = 64
LOOPS_BANK_PADS = 16  # we use the first 4×4 grid for loops; visually one "screen"

# Pad layout for bank 1: 4 stems × 4 loops each = 16 pads
STEM_ORDER = ("drums", "bass", "other", "vocals")
LOOPS_PER_STEM_DEFAULT = 4

# Pad layout for bank 2: 5 substems on pads 1-5, oneshots fill 6-64
SUBSTEM_ORDER = ("kick", "snare", "hihat", "toms", "cymbals")


@dataclass
class KoalaExportConfig:
    """Configuration for a single Koala export run."""

    loops_per_stem: int = LOOPS_PER_STEM_DEFAULT
    """Max loops per stem in bank 1. 4 stems × N must be ≤ 16."""

    oneshots_per_part: int | None = None
    """Cap oneshots per drum part. None = pack as many as fit (capped by bank size)."""

    output_dir: Path = field(default_factory=lambda: Path("koala_exports"))
    """Where to write the zip."""

    keep_unzipped: bool = False
    """If True, leave the staging folder next to the zip (handy for debugging)."""


def export_koala(curated_dir: Path, config: KoalaExportConfig | None = None) -> Path:
    """
    Build a Koala-ready zip from a stemforge curated/ directory.

    Args:
        curated_dir: Path to `processed/{project}/curated/`
        config: Export config (uses defaults if None)

    Returns:
        Path to the produced .zip file.

    Raises:
        FileNotFoundError: if curated_dir or its manifest is missing
        ValueError: if loops_per_stem × len(STEM_ORDER) > LOOPS_BANK_PADS
    """
    config = config or KoalaExportConfig()

    if not curated_dir.exists():
        raise FileNotFoundError(f"curated_dir does not exist: {curated_dir}")
    if config.loops_per_stem * len(STEM_ORDER) > LOOPS_BANK_PADS:
        raise ValueError(
            f"loops_per_stem={config.loops_per_stem} × {len(STEM_ORDER)} stems "
            f"exceeds {LOOPS_BANK_PADS} pads in bank 1"
        )

    manifest = _load_manifest(curated_dir)
    project_name = curated_dir.parent.name
    config.output_dir.mkdir(parents=True, exist_ok=True)

    staging = config.output_dir / f"{project_name}_koala"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir()

    # Bank 1: curated loops (4 stems × N loops)
    bank_01 = staging / "bank_01_loops"
    bank_01.mkdir()
    bank_01_count = _build_bank_01_loops(curated_dir, bank_01, manifest, config)

    # Bank 2: drum kit (substems + oneshots)
    bank_02 = staging / "bank_02_kit"
    bank_02.mkdir()
    bank_02_count = _build_bank_02_kit(curated_dir, bank_02, config)

    # README for the human at the other end of the AirDrop
    _write_readme(staging, project_name, manifest, bank_01_count, bank_02_count, config)

    # Zip it
    zip_path = config.output_dir / f"{project_name}_koala.zip"
    if zip_path.exists():
        zip_path.unlink()
    _zip_directory(staging, zip_path)

    if not config.keep_unzipped:
        shutil.rmtree(staging)

    return zip_path


# ------------------------- bank builders -------------------------


def _build_bank_01_loops(
    curated_dir: Path,
    bank_dir: Path,
    manifest: dict,
    config: KoalaExportConfig,
) -> int:
    """
    Bank 1: 4 stems × loops_per_stem, numbered 01..16.

    Pad layout when loops_per_stem=4:
        Pads 1-4   = drums  loops (top-N by manifest ranking)
        Pads 5-8   = bass   loops
        Pads 9-12  = other  loops
        Pads 13-16 = vocals loops

    If a stem has fewer loops than loops_per_stem, the remaining pad slots in
    that stem's row are simply skipped (filename indices have gaps). This
    keeps the visual 4×4 grid alignment stable across exports — drums always
    on row 1, bass always on row 2, etc.
    """
    files_copied = 0

    for row, stem in enumerate(STEM_ORDER):
        stem_dir = curated_dir / stem
        # Row anchor: drums → 1, bass → 5, other → 9, vocals → 13
        row_start = row * config.loops_per_stem + 1

        # Get top-N loops for this stem, ranked
        loops = _ranked_loops_for_stem(manifest, stem, limit=config.loops_per_stem)

        for slot, loop_filename in enumerate(loops):
            # Resolve: file may be absolute (curation v2), relative-from-curated
            # (curation v1: "curated/drums/bar_01.wav"), or just a basename.
            candidate = Path(loop_filename)
            if candidate.is_absolute():
                src = candidate
            else:
                # Try relative-from-curated_dir's parent first (handles
                # "curated/drums/bar_01.wav" form), then stem_dir (basename),
                # then curated_dir (relative-from-here).
                src = curated_dir.parent / loop_filename
                if not src.exists():
                    src = stem_dir / Path(loop_filename).name
                if not src.exists():
                    src = curated_dir / loop_filename
            if not src.exists():
                print(f"  warning: {loop_filename} referenced in manifest but missing, skipping")
                continue
            pad = row_start + slot
            dest_name = f"{pad:02d}_{stem}_{slot + 1:02d}.wav"
            shutil.copy2(src, bank_dir / dest_name)
            files_copied += 1

    return files_copied


def _build_bank_02_kit(
    curated_dir: Path,
    bank_dir: Path,
    config: KoalaExportConfig,
) -> int:
    """
    Bank 2: drum substems on pads 1-5, oneshots filling 6-64.

    Substems are the full drum-part loops (kick.wav, snare.wav, etc.) — these
    let the user layer rhythmic loops on top of each other for live mangling.

    Oneshots are individual hits, ordered: all kicks, then all snares, etc.,
    so that pad rows correspond to drum parts. With oneshots_per_part=None
    (default), packs evenly across parts to fill the bank.
    """
    files_copied = 0

    # Substems on pads 1-5
    substems_dir = curated_dir / "drum_substems"
    if substems_dir.exists():
        for pad, part in enumerate(SUBSTEM_ORDER, start=1):
            src = substems_dir / f"{part}.wav"
            if src.exists():
                dest_name = f"{pad:02d}_{part}.wav"
                shutil.copy2(src, bank_dir / dest_name)
                files_copied += 1

    # Oneshots fill from pad 6 onward
    pads_remaining = PADS_PER_BANK - files_copied
    oneshots_per_part = config.oneshots_per_part or (pads_remaining // len(SUBSTEM_ORDER))

    pad_cursor = files_copied + 1
    for part in SUBSTEM_ORDER:
        oneshot_dir = curated_dir / f"{part}_oneshots"
        if not oneshot_dir.exists():
            continue
        # Sorted = deterministic; assumes curator emits ranked filenames
        # (e.g. kick_oneshot_001.wav, kick_oneshot_002.wav, ...)
        oneshots = sorted(oneshot_dir.glob("*.wav"))[:oneshots_per_part]
        for i, src in enumerate(oneshots, start=1):
            if pad_cursor > PADS_PER_BANK:
                break
            dest_name = f"{pad_cursor:02d}_{part}_oneshot_{i:02d}.wav"
            shutil.copy2(src, bank_dir / dest_name)
            files_copied += 1
            pad_cursor += 1
        if pad_cursor > PADS_PER_BANK:
            break

    return files_copied


# ------------------------- helpers -------------------------


def _load_manifest(curated_dir: Path) -> dict:
    """Load curated/manifest.json, the source of truth for BPM and ranking."""
    manifest_path = curated_dir / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(
            f"No manifest.json in {curated_dir}. Did you run `stemforge curate` on this project?"
        )
    return json.loads(manifest_path.read_text())


def _ranked_loops_for_stem(manifest: dict, stem: str, limit: int) -> list[str]:
    """
    Pull the top-N loops for a stem from the manifest, ranked.

    Defensive against schema variation: tries a few likely shapes for the
    manifest before giving up. The manifest is the curator's output, so the
    shape may evolve — adapt this function if `stemforge curate` changes.
    """
    # Shape A (curation v1): {"stems": {"drums": [{"file": "...", "position": 1}, ...]}}
    # Shape A2 (curation v2): {"stems": {"drums": {"loops": [...], ...}}}
    if "stems" in manifest and stem in manifest["stems"]:
        block = manifest["stems"][stem]
        if isinstance(block, dict):
            entries = block.get("loops", [])
        else:
            entries = block
        # Filter to dict entries with file fields
        entries = [e for e in entries if isinstance(e, dict) and "file" in e]
        sorted_entries = sorted(
            entries,
            key=lambda e: e.get("rank", e.get("position", e.get("score", 0))),
        )
        return [e["file"] for e in sorted_entries[:limit]]

    # Shape B: {"loops": [{"stem": "drums", "file": "...", "rank": 1}, ...]}
    if "loops" in manifest and isinstance(manifest["loops"], list):
        entries = [e for e in manifest["loops"] if isinstance(e, dict) and e.get("stem") == stem]
        sorted_entries = sorted(
            entries,
            key=lambda e: e.get("rank", e.get("position", e.get("score", 0))),
        )
        return [e["file"] for e in sorted_entries[:limit] if "file" in e]

    # Shape C (fallback): just glob the stem dir, sorted alphabetically
    return []


def _write_readme(
    staging: Path,
    project_name: str,
    manifest: dict,
    bank_01_count: int,
    bank_02_count: int,
    config: KoalaExportConfig,
) -> None:
    bpm = manifest.get("bpm", "unknown")
    readme = f"""\
{project_name} — Koala Sampler bank set
{"=" * 60}

Source BPM: {bpm}
Bank 1 (loops): {bank_01_count} samples
Bank 2 (kit):   {bank_02_count} samples

LOADING IN KOALA
----------------
1. Get this folder onto your device:
   - iOS: AirDrop the .zip → share to "Send to Koala Sampler" Shortcut
     (install once: https://routinehub.co/shortcut/7308/)
     OR save to Files.app under "On My iPad/iPhone" (NOT iCloud)
   - Desktop: extract the .zip somewhere local

2. In Koala, tap SAMPLES (bottom right) → ADD LOCATION → pick the
   extracted folder. It now lives in your Samples Browser favorites.

3. Load a bank:
   - Tap into bank_01_loops/
   - Tap the multi-select button (top right)
   - Select all files
   - Drag onto the top-left empty pad
   - Pads fill in numerical order automatically

4. Repeat for bank_02_kit/ on a different bank slot in your song.

GOTCHAS
-------
- If samples show a "Cloud" icon instead of a waveform: the files are
  iCloud-pending. Long-press the folder → Download Now. To avoid this,
  save to "On My iPad" instead of iCloud Drive.

PAD LAYOUT
----------
Bank 1 — Loops ({config.loops_per_stem} per stem):
  Pads 1-{config.loops_per_stem}: drums
  Pads {config.loops_per_stem + 1}-{config.loops_per_stem * 2}: bass
  Pads {config.loops_per_stem * 2 + 1}-{config.loops_per_stem * 3}: other
  Pads {config.loops_per_stem * 3 + 1}-{config.loops_per_stem * 4}: vocals

Bank 2 — Kit:
  Pads 1-5: kick, snare, hihat, toms, cymbals (full substem loops)
  Pads 6+:  oneshots, grouped by part

Generated by stemforge.
"""
    (staging / "README.txt").write_text(readme)


def _zip_directory(src_dir: Path, zip_path: Path) -> None:
    """Zip src_dir's contents into zip_path, preserving the top-level folder name."""
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in src_dir.rglob("*"):
            if path.is_file():
                # arcname includes the staging dir name so the zip extracts
                # to a single top-level folder rather than splatting files
                arcname = path.relative_to(src_dir.parent)
                zf.write(path, arcname)
