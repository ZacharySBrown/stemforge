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

import shutil
import subprocess
import tempfile

import click
from rich.console import Console
from rich.rule import Rule


NON_WAV_FORMATS = {".mp3", ".m4a", ".aac", ".ogg", ".flac", ".aiff", ".wma", ".opus"}


def ensure_wav(audio_path: Path, console: Console = None) -> tuple[Path, bool]:
    """Convert non-WAV audio to WAV via ffmpeg. Returns (wav_path, was_converted)."""
    if audio_path.suffix.lower() == ".wav":
        return audio_path, False

    if not shutil.which("ffmpeg"):
        raise click.UsageError(
            f"Cannot convert {audio_path.suffix} — ffmpeg not installed.\n"
            "  brew install ffmpeg"
        )

    wav_path = audio_path.with_suffix(".wav")
    if wav_path.exists():
        if console:
            console.print(f"  [dim]Using existing WAV: {wav_path.name}[/dim]")
        return wav_path, False

    if console:
        console.print(f"  [dim]Converting {audio_path.suffix} → .wav ...[/dim]")
    result = subprocess.run(
        ["ffmpeg", "-i", str(audio_path), "-y", str(wav_path)],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise click.UsageError(f"ffmpeg conversion failed:\n{result.stderr[-500:]}")

    if console:
        console.print(f"  [dim]Converted: {wav_path.name}[/dim]")
    return wav_path, True

from .backends.lalal import LalalBackend
from .backends.demucs import DemucsBackend
from .backends.musicai import MusicAiBackend
from .slicer import (
    detect_bpm_and_beats, slice_at_beats,
    slice_at_bars, slice_at_bars_from_analysis,
)
from . import curator as _curator
from .manifest import write_manifest
from .manifest_schema import (
    BAR_INDEX_TO_LABEL,
    BatchManifest,
    SampleMeta,
    display_name,
    write_batch,
    write_sidecar,
)
from .config import (
    PROCESSED_DIR, LALAL_PRESETS, LALAL_STEMS, LALAL_DEFAULT_PRESET,
    DEMUCS_MODELS, MUSIC_AI_WORKFLOWS, MUSIC_AI_DEFAULT_WORKFLOW,
)

console = Console()


@click.group()
def cli():
    """StemForge — stem splitting + beat slicing for Ableton Live."""
    pass


@cli.command()
@click.argument("audio_file", type=click.Path(exists=True, path_type=Path))
@click.option("--backend", "-b",
              type=click.Choice(["lalal", "demucs", "musicai", "auto"]),
              default="auto",
              help="'auto' uses LALAL if key is set, else Demucs.")
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
      stemforge split track.mp3                          # auto-converts to WAV
    """
    # ── Auto-convert to WAV if needed ────────────────────────────────────────
    audio_file, _ = ensure_wav(audio_file, console)

    # ── Resolve backend ──────────────────────────────────────────────────────
    if backend == "auto":
        has_lalal = bool(os.environ.get("LALAL_LICENSE_KEY", "").strip())
        has_musicai = bool(os.environ.get("MUSIC_AI_API_KEY", "").strip())
        if has_lalal:
            backend = "lalal"
        elif has_musicai:
            backend = "musicai"
        else:
            backend = "demucs"
        console.print(f"  [dim]Auto-selected backend: {backend}[/dim]")

    if backend == "lalal":
        be = LalalBackend()
    elif backend == "musicai":
        be = MusicAiBackend()
    else:
        be = DemucsBackend()

    # ── Output dir ───────────────────────────────────────────────────────────
    out_root = output or PROCESSED_DIR
    track_name = to_snake_case(audio_file.stem)
    track_out = out_root / track_name
    track_out.mkdir(parents=True, exist_ok=True)

    # ── Backend-specific kwargs ──────────────────────────────────────────────
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
    elif backend == "musicai":
        if stems and stems in MUSIC_AI_WORKFLOWS:
            backend_kwargs["workflow"] = stems
        elif stems:
            backend_kwargs["workflow"] = stems
        else:
            backend_kwargs["workflow"] = MUSIC_AI_DEFAULT_WORKFLOW
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
    console.print("\n[bold]Music.AI workflows:[/bold]")
    wf_descs = {
        "suite":  "stem-separation-suite — up to 9 stems (vocals, drums, bass, keys, strings, guitars, piano, wind, other)",
        "vocals": "stems-vocals-accompaniment — 4 stems (vocals, drums, bass, other)",
    }
    for key, desc in wf_descs.items():
        default = " [dim](default)[/dim]" if key == MUSIC_AI_DEFAULT_WORKFLOW else ""
        console.print(f"  [cyan]{key:<8}[/cyan]  {desc}{default}")


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


@cli.command()
@click.argument("audio_file", type=click.Path(exists=True, path_type=Path))
@click.option("--json-out", is_flag=True, default=False,
              help="Output raw JSON instead of formatted table.")
def analyze(audio_file, json_out):
    """
    Analyze an audio file and recommend optimal stem split settings.

    Detects genre characteristics (electronic, rock, jazz, hip hop, etc.)
    and recommends the best backend, model, and stem configuration.

    \b
    Examples:
      stemforge analyze track.wav
      stemforge analyze track.wav --json-out
      stemforge analyze track.mp3              # auto-converts to WAV
      stemforge split track.wav --auto   # analyze + split in one step
    """
    audio_file, _ = ensure_wav(audio_file, console)

    from .analyzer import analyze as run_analysis
    from dataclasses import asdict

    console.print(Rule(f"[bold cyan]StemForge Analyze[/bold cyan] — {audio_file.name}"))
    console.print()

    with console.status("[cyan]Analyzing audio...[/cyan]"):
        profile = run_analysis(audio_file)

    if json_out:
        import json as json_mod
        console.print(json_mod.dumps(asdict(profile), indent=2))
        return

    # ── Genre + confidence ─────────────────────────────────────────────────
    conf_color = "green" if profile.genre_confidence > 0.6 else "yellow" if profile.genre_confidence > 0.4 else "red"
    console.print(f"  Genre:      [bold cyan]{profile.genre}[/bold cyan]  "
                  f"[{conf_color}]({profile.genre_confidence:.0%} confidence)[/{conf_color}]")
    console.print(f"  BPM:        [cyan]{profile.bpm}[/cyan]")
    console.print()

    # ── Genre scores ──────────────────────────────────────────────────────
    console.print("[bold]Genre Scores (CLAP)[/bold]")
    sorted_genres = sorted(profile.genre_scores.items(), key=lambda x: x[1], reverse=True)
    for label, score in sorted_genres[:5]:
        bar = '█' * int(score * 40)
        console.print(f"  {label:<28s} {bar:<40s} {score:.1%}")
    console.print()

    # ── Instruments detected ───────────────────────────────────────────────
    console.print("[bold]Instruments Detected (AST)[/bold]")
    if profile.instruments_detected:
        for instr in profile.instruments_detected[:8]:
            score = profile.instrument_scores.get(instr, 0)
            bar = '█' * int(score * 40)
            console.print(f"  {instr:<35s} {bar:<40s} {score:.1%}")
    else:
        console.print("  [dim]No instruments detected above threshold[/dim]")
    console.print()

    # ── Spectral profile ───────────────────────────────────────────────────
    console.print("[bold]Spectral Profile (librosa)[/bold]")
    console.print(f"  Bass energy:    {'█' * int(profile.bass_ratio * 30):<30s} {profile.bass_ratio:.1%}")
    console.print(f"  Mid energy:     {'█' * int(profile.mid_ratio * 30):<30s} {profile.mid_ratio:.1%}")
    console.print(f"  High energy:    {'█' * int(profile.high_ratio * 30):<30s} {profile.high_ratio:.1%}")
    console.print(f"  Percussive:     {'█' * int(profile.percussive_ratio * 30):<30s} {profile.percussive_ratio:.1%}")
    console.print(f"  Complexity:     {'█' * int(profile.spectral_complexity * 30):<30s} {profile.spectral_complexity:.1%}")
    console.print(f"  Dynamic range:  {profile.dynamic_range_db:.1f} dB")
    console.print(f"  Onset density:  {profile.onset_density:.1f} / sec")
    console.print()

    # ── Recommendation ─────────────────────────────────────────────────────
    console.print(Rule("[bold]Recommendation[/bold]"))
    console.print(f"  Backend:  [bold cyan]{profile.recommended_backend}[/bold cyan]")
    console.print(f"  Model:    [cyan]{profile.recommended_model}[/cyan]")
    console.print(f"  Stems:    [cyan]{', '.join(profile.recommended_stems)}[/cyan]")
    console.print()
    console.print(f"  [dim]{profile.reason}[/dim]")
    console.print()

    # ── Quick command ──────────────────────────────────────────────────────
    if profile.recommended_backend == "demucs":
        model_key = {"htdemucs": "default", "htdemucs_ft": "fine", "htdemucs_6s": "6stem"}.get(
            profile.recommended_model, "default")
        cmd = f"stemforge split {audio_file} --backend demucs --model {model_key}"
    else:
        cmd = f"stemforge split {audio_file} --backend musicai --stems suite"
    console.print(f"  [bold]Run:[/bold]  [green]{cmd}[/green]")
    console.print()


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
    Compile YAML → JSON for M4L device.
    Processes both pipelines/ and presets/ directories.
    """
    import yaml
    repo_root = Path(__file__).parent.parent

    # Process pipelines
    p_dir = pipeline_dir or (repo_root / "pipelines")
    for yaml_file in p_dir.glob("*.yaml"):
        with open(yaml_file) as f:
            data = yaml.safe_load(f)
        json_file = yaml_file.with_suffix(".json")
        json_file.write_text(json.dumps(data, indent=2))
        console.print(f"[green]OK[/green] {yaml_file.name} → {json_file.name}")

    # Process presets
    pr_dir = repo_root / "presets"
    if pr_dir.exists():
        for yaml_file in pr_dir.glob("*.yaml"):
            with open(yaml_file) as f:
                data = yaml.safe_load(f)
            json_file = yaml_file.with_suffix(".json")
            json_file.write_text(json.dumps(data, indent=2))
            console.print(f"[green]OK[/green] {yaml_file.name} → {json_file.name} [dim](preset)[/dim]")

    console.print("\nRestart or reload the M4L device to pick up changes.")


@cli.command()
@click.argument("audio_file", type=click.Path(exists=True, path_type=Path))
@click.option("--analysis", type=click.Path(exists=True, path_type=Path), default=None,
              help="Ableton analysis JSON. If omitted, uses librosa beat detection.")
@click.option("--backend", "-b", default="demucs",
              type=click.Choice(["demucs", "lalal", "musicai"]))
@click.option("--model", "-m", default="default")
@click.option("--strategy", "-s", default="max-diversity",
              type=click.Choice(["max-diversity", "rhythm-taxonomy", "sectional"]))
@click.option("--n-bars", "-n", default=14, type=int, help="Number of bars to curate.")
@click.option("--time-sig", default="4/4",
              help="Time signature (librosa fallback only). Format: numerator/denominator.")
@click.option("--output", "-o", default=None, type=click.Path(path_type=Path))
@click.option("--curation", type=click.Path(exists=True, path_type=Path), default=None,
              help="Curation config YAML (e.g. pipelines/curation.yaml). When provided, "
                   "delegates bar-slicing + curation to v0/src/stemforge_curate_bars.py and "
                   "produces a production-mode manifest (layout_mode=production, version=2). "
                   "Omit to use forge's built-in v1 curation path.")
def forge(audio_file, analysis, backend, model, strategy, n_bars, time_sig, output, curation):
    """
    Full pipeline: split → slice at bars → curate → curated WAVs + manifest.

    Emits newline-delimited JSON events on stdout for M4L integration.
    """
    import shutil as _shutil

    def emit(event: str, **data):
        print(json.dumps({"event": event, **data}), flush=True)

    audio_file, _ = ensure_wav(audio_file, console=None)

    try:
        num_str, _den_str = time_sig.split("/")
        fallback_numerator = int(num_str)
    except Exception:
        fallback_numerator = 4

    out_root = Path(output) if output else PROCESSED_DIR
    track_name = to_snake_case(audio_file.stem)
    track_out = Path(out_root) / track_name
    track_out.mkdir(parents=True, exist_ok=True)

    emit("started", track=track_name, audio=str(audio_file),
         backend=backend, strategy=strategy, n_bars=n_bars,
         output_dir=str(track_out))

    # ── 1. Separation ──
    emit("progress", phase="splitting", pct=0)
    if backend == "lalal":
        be = LalalBackend()
    elif backend == "musicai":
        be = MusicAiBackend()
    else:
        be = DemucsBackend()
    try:
        if backend == "demucs":
            stem_paths = be.separate(audio_file, track_out, model=model)
        else:
            stem_paths = be.separate(audio_file, track_out)
    except Exception as e:
        emit("error", phase="splitting", message=str(e))
        sys.exit(1)
    emit("progress", phase="splitting", pct=100,
         stems=[str(p) for p in stem_paths.values()])

    # ── 2+3. Production curation (opt-in via --curation) ──
    # When a curation config is provided, delegate bar-slicing + curation to
    # v0/src/stemforge_curate_bars.py which writes a production-mode manifest
    # (layout_mode=production, version=2, drum oneshots, phrase structure).
    # When omitted, falls through to forge's legacy inline curator below.
    if curation is not None:
        import subprocess
        script = Path(__file__).resolve().parents[1] / "v0/src/stemforge_curate_bars.py"
        if not script.exists():
            emit("error", phase="curating",
                 message=f"stemforge_curate_bars.py not found at {script}")
            sys.exit(1)
        result = subprocess.run(
            [sys.executable, str(script),
             "--stems-dir", str(track_out),
             "--curation", str(curation),
             "--json-events",
             "--n-bars", str(n_bars),
             "--strategy", strategy,
             "--time-sig", str(fallback_numerator)],
            check=False,
        )
        if result.returncode != 0:
            emit("error", phase="curating",
                 message=f"stemforge_curate_bars.py exited {result.returncode}")
            sys.exit(1)
        manifest_path = track_out / "curated" / "manifest.json"
        emit("complete",
             output_dir=str(manifest_path.parent),
             manifest=str(manifest_path),
             bars=n_bars,
             mode="production")
        return

    # ── 2. Slicing at bar boundaries (legacy inline path) ──
    emit("progress", phase="slicing", pct=0)

    analysis_data = None
    if analysis is not None:
        analysis_data = json.loads(Path(analysis).read_text())

    stem_bar_paths: dict[str, list[Path]] = {}
    non_residual = [(n, p) for n, p in stem_paths.items() if n != "residual"]

    # When no analysis, reuse a single beat detection on drums for all stems.
    shared_beat_times = None
    detected_bpm: float | None = None
    if analysis_data is None:
        bpm_source = (stem_paths.get("drums") or stem_paths.get("drum")
                      or next(iter(stem_paths.values())))
        detected_bpm, shared_beat_times = detect_bpm_and_beats(bpm_source)
    else:
        # Ableton analysis JSON carries the project tempo at the top level.
        ab_bpm = analysis_data.get("bpm") or analysis_data.get("tempo")
        if ab_bpm is not None:
            detected_bpm = float(ab_bpm)

    for i, (stem_name, stem_path) in enumerate(non_residual):
        if analysis_data is not None:
            bars = slice_at_bars_from_analysis(
                stem_path, analysis_data, track_out, stem_name,
            )
        else:
            bars = slice_at_bars(
                stem_path, track_out, stem_name,
                time_sig_numerator=fallback_numerator,
                beat_times=shared_beat_times,
            )
        stem_bar_paths[stem_name] = sorted(bars)
        pct = int(((i + 1) / len(non_residual)) * 100)
        emit("progress", phase="slicing", pct=pct,
             stem=stem_name, bars=len(bars))

    total_bars = len(stem_bar_paths.get("drums", next(iter(stem_bar_paths.values()), [])))
    emit("progress", phase="slicing", pct=100, bars=total_bars)

    # ── 3. Curation on drums stem ──
    emit("progress", phase="curating", pct=0)
    curation_source = "drums" if "drums" in stem_bar_paths else next(iter(stem_bar_paths))
    drums_bar_dir = track_out / f"{curation_source}_bars"

    selected_drum_paths = _curator.curate(
        drums_bar_dir, n_bars=n_bars, strategy=strategy,
    )

    # Map selected drum bars back to their bar index (1-based from filename)
    import re as _re
    selected_indices: list[int] = []
    for p in selected_drum_paths:
        m = _re.search(r"_bar_(\d+)\.wav$", p.name)
        if m:
            selected_indices.append(int(m.group(1)))

    curated_root = track_out / "curated"
    curated_root.mkdir(parents=True, exist_ok=True)

    # Mirror selection across all non-residual stems.
    curated_manifest: dict = {
        "track": track_name,
        "source_audio": str(audio_file),
        "strategy": strategy,
        "n_bars": len(selected_indices),
        "analysis_source": "ableton" if analysis_data else "librosa",
        "time_signature_numerator": (
            analysis_data["time_signature"]["numerator"]
            if analysis_data else fallback_numerator
        ),
        "stems": {},
    }

    for stem_name, bar_paths in stem_bar_paths.items():
        stem_curated_dir = curated_root / stem_name
        stem_curated_dir.mkdir(parents=True, exist_ok=True)
        by_index = {}
        for bp in bar_paths:
            m = _re.search(r"_bar_(\d+)\.wav$", bp.name)
            if m:
                by_index[int(m.group(1))] = bp

        entries = []
        for pos, src_idx in enumerate(selected_indices, start=1):
            src = by_index.get(src_idx)
            if src is None or not src.exists():
                continue
            dest = stem_curated_dir / f"bar_{pos:02d}.wav"
            _shutil.copy2(src, dest)
            entries.append({
                "position": pos,
                "source_bar_index": src_idx,
                "file": str(dest.relative_to(track_out)),
            })
        curated_manifest["stems"][stem_name] = entries

    manifest_path = curated_root / "manifest.json"
    manifest_path.write_text(json.dumps(curated_manifest, indent=2))

    # ── 4. Emit per-sample sidecars + a BatchManifest (manifest-spec) ──
    # Producer-side rotation: drums→A, bass→B, vocals→C, other→D, with
    # bottom-up pad layout per BAR_INDEX_TO_LABEL. Consumers (ep133-ppak's
    # loaders) honor `suggested_pad`/`suggested_group` directly.
    STEM_TO_GROUP = {"drums": "A", "bass": "B", "vocals": "C", "other": "D"}
    PLAYMODE_BY_STEM = {"drums": "oneshot"}  # everything else defaults to "key"

    batch_samples: list[SampleMeta] = []
    for stem_name, entries in curated_manifest["stems"].items():
        group = STEM_TO_GROUP.get(stem_name)
        playmode = PLAYMODE_BY_STEM.get(stem_name, "key")

        for entry in entries:
            pos = entry["position"]
            wav_rel = Path(entry["file"])  # relative to track_out
            wav_abs = track_out / wav_rel

            pad_idx = pos - 1  # 1-based → 0-based
            suggested_pad = (
                BAR_INDEX_TO_LABEL[pad_idx]
                if pad_idx < len(BAR_INDEX_TO_LABEL) else None
            )

            meta = SampleMeta(
                name=display_name(f"{track_name} {stem_name} {pos}"),
                bpm=detected_bpm,
                time_mode="bpm" if detected_bpm is not None else None,
                bars=1.0,
                playmode=playmode,
                source_track=track_name,
                stem=stem_name if stem_name in {"drums", "bass", "vocals", "other"} else None,
                role="loop",
                suggested_group=group,
                suggested_pad=suggested_pad,
            )

            # Per-file sidecar (auto-fills file + audio_hash)
            write_sidecar(wav_abs, meta)

            # Add to batch with curated-root-relative file path
            batch_samples.append(meta.model_copy(update={
                "file": str(wav_abs.relative_to(curated_root)),
            }))

    batch = BatchManifest(
        version=1,
        track=track_name,
        bpm=detected_bpm,
        samples=batch_samples,
    )
    batch_path = write_batch(curated_root, batch)

    emit("progress", phase="curating", pct=100, selected=len(selected_indices))
    emit("complete",
         output_dir=str(curated_root),
         manifest=str(manifest_path),
         batch_manifest=str(batch_path),
         sidecars=len(batch_samples),
         bars=len(selected_indices))


@cli.command()
@click.argument("input_path", required=False, default=None,
                type=click.Path(exists=True, path_type=Path))
@click.option("--target", "-t", required=True,
              type=click.Choice(["ep133", "chompi", "both"]),
              help="Target device.")
@click.option("--workflow", "-w", default="compose",
              type=click.Choice(["compose", "perform"]),
              help="compose=single track deep, perform=multi-track curated.")
@click.option("--output", "-o", default=None, type=click.Path(path_type=Path),
              help="Output directory.")
@click.option("--budget", is_flag=True, default=False,
              help="EP-133: render at 22050 Hz to double memory capacity.")
@click.option("--firmware", default="tempo",
              type=click.Choice(["tempo", "tape"]),
              help="Chompi firmware variant.")
@click.option("--dry-run", is_flag=True, default=False,
              help="Show plan without writing files.")
@click.option("--upload", is_flag=True, default=False,
              help="EP-133: upload samples via USB-MIDI SysEx after export.")
@click.option("--start-slot", default=1, type=int,
              help="EP-133: starting sound slot for upload (default: 1).")
@click.option("--manifest", default=None, type=click.Path(exists=True, path_type=Path),
              help="EP-133 v2 manifest-driven export. When provided, loads a curated "
                   "manifest.json (Curation Stage v2 schema) and produces per-loop "
                   "WAVs + SETUP.md sized for EP Sample Tool. Skips legacy "
                   "directory-scan. Pairs with --config.")
@click.option("--config", "config_path", default=None,
              type=click.Path(exists=True, path_type=Path),
              help="EP-133 v2 curation config YAML (e.g. pipelines/curation.yaml). "
                   "Reads the `ep133_export:` block. Used with --manifest.")
def export(input_path, target, workflow, output, budget, firmware, dry_run,
           upload, start_slot, manifest, config_path):
    """
    Export stems/slices for hardware samplers.

    \b
    Examples:
      stemforge export track_dir/ --target ep133 --workflow compose
      stemforge export processed/ --target chompi --workflow perform
      stemforge export track_dir/ --target both --workflow compose
      stemforge export track_dir/ --target ep133 --workflow compose --budget

    \b
    EP-133 v2 (manifest-driven):
      stemforge export --target ep133 \\
        --manifest processed/song/curated/manifest.json \\
        --config pipelines/curation.yaml \\
        --output export/ep133/
    """
    # ── EP-133 v2 manifest-driven path ───────────────────────────────────────
    if manifest is not None:
        if target != "ep133":
            raise click.UsageError(
                "--manifest is EP-133-specific; use --target ep133."
            )
        if input_path is not None:
            console.print(
                "[yellow]--manifest provided; ignoring positional INPUT_PATH.[/yellow]"
            )
        from .exporters.ep133_v2 import export_from_manifest

        out_root = Path(output) if output else Path("./export/ep133")
        if dry_run:
            console.print(
                f"[dim]DRY RUN: would export manifest {manifest} → {out_root}[/dim]"
            )
            return

        try:
            song_out = export_from_manifest(
                manifest_path=Path(manifest),
                config_path=Path(config_path) if config_path else None,
                out_dir=Path(out_root),
            )
        except (ValueError, FileNotFoundError, OSError) as e:
            console.print(f"[red]EP-133 v2 export failed:[/red] {e}")
            sys.exit(1)

        report_file = song_out / "_ep133_export_report.json"
        if report_file.exists():
            r = json.loads(report_file.read_text())
            console.print(
                f"  [green]OK[/green] ep133 v2: "
                f"{r['loops_exported']} loops → {song_out}"
            )
            for w in r.get("warnings", []):
                console.print(f"  [yellow]warn:[/yellow] {w}")
        else:
            console.print(f"  [green]OK[/green] ep133 v2: → {song_out}")
        return

    # ── Legacy directory-scan path ────────────────────────────────────────────
    if input_path is None:
        raise click.UsageError(
            "INPUT_PATH is required unless --manifest is provided."
        )

    from .exporters.ep133 import EP133Exporter
    from .exporters.chompi import ChompiExporter

    if output is None:
        output = Path("./export")

    is_single_track = (input_path / "drums.wav").exists()
    targets = ["ep133", "chompi"] if target == "both" else [target]

    for tgt in targets:
        if tgt == "ep133":
            exporter = EP133Exporter(budget=budget)
        else:
            exporter = ChompiExporter(firmware=firmware)

        tgt_output = output / tgt
        if dry_run:
            console.print(f"[dim]DRY RUN: {tgt} {workflow} → {tgt_output}[/dim]")
            continue

        if workflow == "compose" and is_single_track:
            manifest = exporter.export_compose(input_path, tgt_output)
        elif workflow == "perform" or not is_single_track:
            manifest = exporter.export_perform(input_path, tgt_output)
        else:
            manifest = exporter.export_compose(input_path, tgt_output)

        console.print(f"  [green]OK[/green] {tgt}: {len(manifest.slots)} slots → {tgt_output}")

        # Upload to EP-133 if requested
        if upload and tgt == "ep133":
            from .exporters.ep133_upload import upload_export
            upload_export(tgt_output, start_slot=start_slot, dry_run=dry_run)


if __name__ == "__main__":
    cli()
