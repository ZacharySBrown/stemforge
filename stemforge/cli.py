#!/usr/bin/env python3
import json, os, re, sys, time
import numpy as np
from pathlib import Path


def to_snake_case(name: str) -> str:
    """Convert any string to snake_case: '01 Hey Mami' → 'hey_mami'."""
    # Strip leading track numbers like "01_", "01 ", "01-"
    name = re.sub(r"^\d+[\s_\-\.]*", "", name)
    # Replace non-alphanumeric with underscores
    name = re.sub(r"[^a-zA-Z0-9]+", "_", name)
    # Collapse multiple underscores and strip edges
    name = re.sub(r"_+", "_", name).strip("_")
    return name.lower()

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
@click.option("--no-normalize", is_flag=True, default=False,
              help="Skip peak normalization of stems before slicing.")
@click.option("--silence-threshold", "-t", default=1e-3, type=float,
              help="RMS threshold below which beat slices are discarded. Default: 0.001")
def split(audio_file, backend, stems, model, pipeline, output, no_slice, no_normalize, silence_threshold):
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
    track_name = to_snake_case(audio_file.stem)
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
            slices = slice_at_beats(stem_path, beat_times, track_out, stem_name,
                                   silence_threshold=silence_threshold,
                                   normalize=not no_normalize)
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


@cli.command("create-templates")
def create_templates():
    """
    Build the 7 StemForge template tracks in Ableton Live.

    \b
    If AbletonOSC is running, sends a trigger to the M4L builder device.
    Otherwise, prints step-by-step instructions.
    """
    m4l_dir = Path(__file__).parent.parent / "m4l"
    builder = m4l_dir / "stemforge_template_builder.js"

    if not builder.exists():
        console.print("[red]Builder script not found:[/red] " + str(builder))
        sys.exit(1)

    # Try OSC trigger (AbletonOSC on default port 11000)
    triggered = False
    try:
        import socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(1.0)
        # OSC message: /live/song/trigger_builder (custom, requires M4L listener)
        # For now, just check if AbletonOSC is reachable
        sock.sendto(b'\x00', ("127.0.0.1", 11000))
        sock.close()
        console.print("[green]AbletonOSC detected on port 11000[/green]")
        console.print("[dim]Trigger the builder from the M4L device in Ableton.[/dim]")
        triggered = True
    except Exception:
        pass

    console.print(Rule("[bold cyan]StemForge Template Builder[/bold cyan]"))
    console.print()

    tracks = [
        ("SF | Drums Raw",            "Audio", "Red",        "Compressor → EQ Eight"),
        ("SF | Drums Crushed",        "Audio", "Red (dark)", "LO-FI-AF → Decapitator → Compressor → EchoBoy Jr"),
        ("SF | Bass",                 "Audio", "Blue",       "EQ Eight → Compressor → LO-FI-AF → Decapitator"),
        ("SF | Texture Verb",         "Audio", "Green",      "PhaseMistress → EchoBoy → Reverb → LO-FI-AF"),
        ("SF | Texture Crystallized", "Audio", "Teal",       "Crystallizer → Reverb → Utility"),
        ("SF | Vocals",               "Audio", "Orange",     "EQ Eight → Compressor → LO-FI-AF → EchoBoy"),
        ("SF | Beat Chop Simpler",    "MIDI",  "Red",        "Simpler → Decapitator → PrimalTap"),
    ]

    console.print("[bold]Automated setup (recommended):[/bold]")
    console.print(f"  1. Open your StemForge Templates set in Ableton")
    console.print(f"  2. Create a MIDI track → drag Max Instrument onto it")
    console.print(f"  3. Open Max editor → add [js stemforge_template_builder.js]")
    console.print(f"  4. Wire a [button] to inlet, [textedit] to outlet 0")
    console.print(f"  5. Click the button — all 7 tracks are built automatically")
    console.print(f"  6. Dial in VST3 params per setup.md, then Cmd+G to group")
    console.print()
    console.print(f"  Builder script: [cyan]{builder}[/cyan]")
    console.print()

    console.print("[bold]Tracks that will be created:[/bold]")
    for i, (name, ttype, color, chain) in enumerate(tracks, 1):
        console.print(f"  {i}. [bold]{name}[/bold]  [{ttype}]  {color}")
        console.print(f"     [dim]{chain}[/dim]")

    console.print()
    console.print("[dim]See setup.md for full parameter values.[/dim]")
    console.print("[dim]See m4l/README_M4L.md for troubleshooting.[/dim]")


@cli.command("clean-beats")
@click.option("--threshold", "-t", default=1e-3, type=float,
              help="RMS threshold. Beats below this are deleted. Default: 0.001")
@click.option("--dir", "-d", "target_dir", default=None, type=click.Path(path_type=Path),
              help=f"Directory to clean. Default: {PROCESSED_DIR}")
@click.option("--dry-run", is_flag=True, default=False,
              help="Show what would be deleted without deleting.")
def clean_beats(threshold, target_dir, dry_run):
    """
    Delete silent beat slices from processed folders.

    Scans all *_beats/ directories and removes WAV files
    whose RMS is below the threshold.
    """
    import soundfile as sf_mod

    base = target_dir or PROCESSED_DIR
    beat_dirs = sorted(base.rglob("*_beats"))
    if not beat_dirs:
        console.print(f"No beat directories found in {base}")
        return

    total_deleted = 0
    total_kept = 0

    for beat_dir in beat_dirs:
        wavs = sorted(beat_dir.glob("*.wav"))
        deleted = 0
        for wav in wavs:
            data, sr = sf_mod.read(str(wav))
            rms = float(np.sqrt(np.mean(data ** 2)))
            if rms < threshold:
                if dry_run:
                    console.print(f"  [dim]would delete:[/dim] {wav.name}  (RMS={rms:.6f})")
                else:
                    wav.unlink()
                deleted += 1
        kept = len(wavs) - deleted
        total_deleted += deleted
        total_kept += kept
        if deleted > 0:
            action = "would delete" if dry_run else "deleted"
            console.print(
                f"  {beat_dir.relative_to(base)}: "
                f"[red]{action} {deleted}[/red] / kept {kept}"
            )

    prefix = "[dim](dry run)[/dim] " if dry_run else ""
    console.print(
        f"\n{prefix}[bold]{total_deleted}[/bold] silent beats removed, "
        f"[bold]{total_kept}[/bold] kept (threshold={threshold})"
    )


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


if __name__ == "__main__":
    cli()
