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
