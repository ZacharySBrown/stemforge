#!/usr/bin/env python3
import json, re, sys
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

import click
from rich.console import Console
from rich.rule import Rule

from .audit import with_audit


NON_WAV_FORMATS = {".mp3", ".m4a", ".aac", ".ogg", ".flac", ".aiff", ".wma", ".opus"}


def ensure_wav(audio_path: Path, console: Console = None) -> tuple[Path, bool]:
    """Convert non-WAV audio to WAV via ffmpeg. Returns (wav_path, was_converted)."""
    if audio_path.suffix.lower() == ".wav":
        return audio_path, False

    if not shutil.which("ffmpeg"):
        raise click.UsageError(
            f"Cannot convert {audio_path.suffix} — ffmpeg not installed.\n  brew install ffmpeg"
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
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise click.UsageError(f"ffmpeg conversion failed:\n{result.stderr[-500:]}")

    if console:
        console.print(f"  [dim]Converted: {wav_path.name}[/dim]")
    return wav_path, True


from .backends.demucs import DemucsBackend
from .slicer import (
    detect_bpm_and_beats,
    slice_at_beats,
    slice_at_bars,
    slice_at_bars_from_analysis,
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
    PROCESSED_DIR,
    DEMUCS_MODELS,
)

console = Console()


@click.group()
def cli():
    """StemForge — stem splitting + beat slicing for Ableton Live."""
    pass


@cli.command()
@click.argument("audio_file", type=click.Path(exists=True, path_type=Path))
@click.option(
    "--model", "-m", default="default", help=f"Demucs model key: {', '.join(DEMUCS_MODELS)}."
)
@click.option(
    "--pipeline",
    "-p",
    default="default",
    help="Pipeline name from pipelines/default.yaml (written to manifest).",
)
@click.option(
    "--output",
    "-o",
    default=None,
    type=click.Path(path_type=Path),
    help=f"Output root directory. Default: {PROCESSED_DIR}",
)
@click.option("--no-slice", is_flag=True, default=False, help="Skip beat slicing. Full stems only.")
@click.option(
    "--no-normalize",
    is_flag=True,
    default=False,
    help="Skip peak normalization of stems before slicing.",
)
@click.option(
    "--silence-threshold",
    "-t",
    default=1e-3,
    type=float,
    help="RMS threshold below which beat slices are discarded. Default: 0.001",
)
@click.option(
    "--bpm",
    "bpm_override",
    type=float,
    default=None,
    help="Manual BPM override. Bypasses auto-detection. Pair with --first-downbeat for full manual control.",
)
@click.option(
    "--first-downbeat",
    "first_downbeat_override",
    type=float,
    default=None,
    help="Manual first-downbeat-time override (seconds). Where bar 1 starts in the source audio.",
)
@click.option(
    "--refine-downbeat",
    is_flag=True,
    default=False,
    help="Sub-beat refinement of auto-detected first_downbeat via kick-onset cross-correlation. "
    "Opt-in: assumes kick is ON the downbeat (fails for tracks where bar 1 is implied).",
)
@click.option(
    "--pre-bars",
    type=int,
    default=None,
    help="Bars of intro material BEFORE bar 1 to include as additional chunks at the same bar grid. "
    "Default: auto-fill the intro (= floor(first_downbeat / bar_period / bars) × bars) when "
    "first_downbeat > 0. Pass 0 to drop the intro entirely.",
)
@click.option(
    "--pad-pre-bars",
    type=int,
    default=1,
    help="Bars of pre-pad inside each chunk WAV (audio BEFORE the loop region) "
    "for drag-extending the loop start backwards in Ableton. Default 1 bar. "
    "Set 0 if you want chunk WAV frame 0 to BE bar 1 of that chunk's content "
    "(no leading prior-bar audio).",
)
@click.option(
    "--pad-post-bars",
    type=int,
    default=1,
    help="Bars of post-pad inside each chunk WAV (audio AFTER the loop region). "
    "Default 1 — useful for drag-extending forward + crossfade headroom at the seam.",
)
@click.option(
    "--emit-partial/--no-emit-partial",
    default=True,
    help="Emit a leading partial chunk_001 when the user-supplied / detected "
    "downbeat leaves a sub-chunk-period intro before bar 1. Default: True.",
)
@click.option(
    "--time-sig",
    "time_sig",
    default="4/4",
    help="Time signature N/D — parity flag with `stemforge forge`. Affects the "
    "downstream bar-grid (prechop's beats_per_bar) so 7/4 / 3/4 / 6/8 chunks "
    "are bar-sized correctly. Does NOT influence beat-this neural detection "
    "(beat-this returns BPM independent of meter); the bar-grid hint is "
    "applied to the librosa fallback path and to the prechop step.",
)
def split(
    audio_file,
    model,
    pipeline,
    output,
    no_slice,
    no_normalize,
    silence_threshold,
    bpm_override,
    first_downbeat_override,
    refine_downbeat,
    pre_bars,
    pad_pre_bars,
    pad_post_bars,
    emit_partial,
    time_sig,
):
    """
    Split an audio file into stems and slice at beat boundaries.

    \b
    Examples:
      stemforge split track.wav                          # default Demucs model
      stemforge split track.wav --model 6stem            # 6-stem Demucs model
      stemforge split track.wav --pipeline glitch        # use 'glitch' pipeline config
      stemforge split track.wav --no-slice               # full stems, no beat files
      stemforge split track.mp3                          # auto-converts to WAV
      stemforge split track.wav --bpm 85.11 --first-downbeat 0.1   # known-good manual values
    """
    # ── Auto-convert to WAV if needed ────────────────────────────────────────
    audio_file, _ = ensure_wav(audio_file, console)

    # ── Parse --time-sig (N/D) ────────────────────────────────────────────────
    # Affects prechop's bar-grid (beats_per_bar = numerator) so non-4/4 content
    # (7/4, 3/4, 6/8) chunks at the right bar length. beat-this is unaffected —
    # the neural detector returns BPM independent of meter. The numerator is
    # what we plumb downstream; the denominator is parsed for validation only
    # (Live's clock is quarter-note based, prechop has no use for it today).
    try:
        num_str, den_str = time_sig.split("/")
        fallback_numerator = int(num_str)
        _fallback_denominator = int(den_str)  # parsed for validation only
        if fallback_numerator < 1 or _fallback_denominator < 1:
            raise ValueError
    except (ValueError, AttributeError):
        raise click.BadParameter(
            f"--time-sig must be N/D with positive ints (e.g. 7/4), got {time_sig!r}",
            param_hint="--time-sig",
        ) from None

    # ── Backend (Demucs only) ────────────────────────────────────────────────
    backend = "demucs"
    be = DemucsBackend()

    # ── Output dir ───────────────────────────────────────────────────────────
    out_root = output or PROCESSED_DIR
    track_name = to_snake_case(audio_file.stem)
    track_out = out_root / track_name
    track_out.mkdir(parents=True, exist_ok=True)

    backend_kwargs = {"model": model}

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
    drums_stem = stem_paths.get("drums") or stem_paths.get("drum")
    bpm_source = drums_stem or stem_paths.get("bass") or next(iter(stem_paths.values()))

    from .tempo_reconciler import reconcile_tempo

    # Always run reconciler — even when overrides are present — so the manifest
    # records what auto-detection said vs what the user override was. That
    # comparison is the labeled-example data we need to keep improving the
    # detector. Skipping it would save ~10s but cost the future-fix signal.
    reconciled = reconcile_tempo(
        mix_path=audio_file,
        drums_path=drums_stem,
        kick_tiebreaker=True,
        kick_workdir=track_out / "tempo_substems",
    )
    auto_bpm = reconciled.bpm
    auto_beats = reconciled.beat_times
    auto_downbeats = reconciled.downbeat_times
    auto_first_downbeat = float(auto_downbeats[0]) if len(auto_downbeats) > 0 else 0.0

    # Apply manual overrides. When BPM is overridden we resynthesize the
    # beat grid at the user's tempo, anchored on whichever first_downbeat
    # is in effect — overridden if given, else auto-detected.
    overrides_active = (bpm_override is not None) or (first_downbeat_override is not None)
    bpm = bpm_override if bpm_override is not None else auto_bpm
    first_downbeat_sec = (
        first_downbeat_override if first_downbeat_override is not None else auto_first_downbeat
    )

    if bpm_override is not None:
        # Synthesize beats at the override tempo, anchored on first_downbeat_sec.
        import soundfile as _sf

        duration = float(_sf.info(str(audio_file)).duration)
        beat_times = np.arange(first_downbeat_sec, duration, 60.0 / bpm)
        downbeat_times = beat_times[::4]
    else:
        beat_times = auto_beats
        downbeat_times = auto_downbeats

    # Sub-beat refinement (opt-in). Only useful when the user did NOT pass an
    # explicit --first-downbeat — if they did, they trust their value over
    # any algorithmic refinement.
    if refine_downbeat and first_downbeat_override is None:
        from .tempo_reconciler import refine_first_downbeat

        refined = refine_first_downbeat(audio_file, bpm, first_downbeat_sec)
        delta = refined - first_downbeat_sec
        console.print(
            f"  [cyan]--refine-downbeat[/cyan] shifted first_downbeat: "
            f"{first_downbeat_sec:.4f}s → {refined:.4f}s (Δ {delta:+.4f}s)"
        )
        first_downbeat_sec = refined

    # BPM refinement (always-on unless user passed --bpm override).
    # The reconciler's bar-period mean estimator still has ~0.1-0.4%
    # residual error from beat-this's per-frame downbeat quantization
    # (Definition 2026-05-06: estimator gave 89.98 vs truth 89.88,
    # accumulating to ~120ms drift by bar 12). refine_bpm cross-correlates
    # a full-song bar-comb against kick onsets and recovers the true BPM
    # to within ~0.01 BPM, dropping accumulated drift to ~10ms.
    if bpm_override is None:
        from .tempo_reconciler import refine_bpm

        refined_bpm = refine_bpm(audio_file, bpm, first_downbeat_sec)
        bpm_delta = refined_bpm - bpm
        if abs(bpm_delta) >= 0.005:
            console.print(
                f"  [cyan]refine-bpm[/cyan] shifted BPM: "
                f"{bpm:.4f} → {refined_bpm:.4f} (Δ {bpm_delta:+.4f})"
            )
        bpm = refined_bpm

    # Fallback: if reconciler returned no usable beats (very short clip,
    # detector silently failed), revive the legacy librosa path so the CLI
    # never returns an empty result.
    if len(beat_times) == 0:
        bpm, beat_times = detect_bpm_and_beats(bpm_source)

    src_color = (
        "green"
        if (overrides_active or reconciled.confidence == "high")
        else ("yellow" if reconciled.confidence == "medium" else "red")
    )
    console.print(
        f"  BPM: [bold cyan]{bpm:.2f}[/bold cyan]  "
        f"first_downbeat: {first_downbeat_sec:.3f}s  |  "
        f"{len(beat_times)} beats, {len(downbeat_times)} downbeats"
    )
    if overrides_active:
        diff_bpm = (bpm - auto_bpm) if bpm_override is not None else 0.0
        diff_dn = (
            (first_downbeat_sec - auto_first_downbeat)
            if first_downbeat_override is not None
            else 0.0
        )
        console.print(
            f"  Source: [green]user-override[/green]  "
            f"(detector said BPM={auto_bpm:.2f} Δ{diff_bpm:+.2f}, "
            f"first_downbeat={auto_first_downbeat:.3f}s Δ{diff_dn:+.3f}s)"
        )
    else:
        console.print(
            f"  Source: [{src_color}]{reconciled.source}[/{src_color}] "
            f"(confidence: {reconciled.confidence})"
        )
        if reconciled.warning:
            console.print(f"  [yellow]warn:[/yellow] {reconciled.warning}")

        # Loud, actionable hint when the underlying issue is "venv missing
        # the optional `beat` extra" — the reconciler silently degrades to
        # librosa-only, which has no idea how to handle half-time hip-hop
        # and never returns a first_downbeat. Hit hard 2026-05-03 after a
        # uv-sync drift; the symptom (Definition's BPM coming back doubled
        # at 120 instead of 90) was indistinguishable from a real DSP bug.
        if (reconciled.warning or "").startswith("beat-this unavailable"):
            console.print(Rule("[bold red]beat-this is not installed[/bold red]"))
            console.print(
                "  The neural downbeat detector is the half-time-hip-hop fix; "
                "without it, BPM\n"
                "  on tracks like Definition / DnB / trap will come back doubled, "
                "and no\n"
                "  first_downbeat will be detected on any track. Install with:\n\n"
                "    [cyan]uv sync --extra beat --extra native[/cyan]\n\n"
                "  Then re-run this split — the dirs you've already produced "
                "have low-confidence\n"
                "  metadata and should be re-stemmed for accurate detection."
            )
            console.print(Rule())

    slice_counts = {}
    if not no_slice:
        for stem_name, stem_path in stem_paths.items():
            if stem_name == "residual":
                continue
            slices = slice_at_beats(
                stem_path,
                beat_times,
                track_out,
                stem_name,
                silence_threshold=silence_threshold,
                normalize=not no_normalize,
            )
            slice_counts[stem_name] = len(slices)
            console.print(f"  {stem_name}: {len(slices)} beat files → {stem_name}_beats/")

    # ── 3. Write manifest ─────────────────────────────────────────────────────
    console.print()
    console.print("[bold]3/3  Writing stems.json manifest[/bold]")
    from .manifest import TempoProvenance

    if overrides_active:
        # Build a warning that captures the detector vs override delta — that
        # comparison is the labeled-example data we want to preserve.
        override_warning_parts = []
        if bpm_override is not None:
            override_warning_parts.append(
                f"bpm override {bpm_override:.3f} (detector said {auto_bpm:.3f})"
            )
        if first_downbeat_override is not None:
            override_warning_parts.append(
                f"first_downbeat override {first_downbeat_override:.3f}s "
                f"(detector said {auto_first_downbeat:.3f}s)"
            )
        override_warning = " ; ".join(override_warning_parts)
        if reconciled.warning:
            override_warning = f"{override_warning} | detector_warning: {reconciled.warning}"
        tempo_provenance = TempoProvenance(
            source="user-override",
            confidence="high",
            first_downbeat_sec=float(first_downbeat_sec),
            n_downbeats=int(len(downbeat_times)),
            warning=override_warning,
            all_estimates=[e.to_dict() for e in reconciled.all_estimates],
        )
    else:
        tempo_provenance = TempoProvenance(
            source=reconciled.source,
            confidence=reconciled.confidence,
            first_downbeat_sec=(float(downbeat_times[0]) if len(downbeat_times) > 0 else None),
            n_downbeats=int(len(downbeat_times)),
            warning=reconciled.warning,
            all_estimates=[e.to_dict() for e in reconciled.all_estimates],
        )
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
        tempo=tempo_provenance,
    )
    console.print(f"  Written: {manifest_path}")

    # ── Pipeline post-split steps (e.g. arrangement-mode prechop) ─────────────
    from .pipelines import load_pipeline, run_post_split_steps

    try:
        pipeline_cfg = load_pipeline(pipeline)
    except Exception as e:
        console.print(f"  [yellow]warn:[/yellow] pipeline {pipeline!r} load failed: {e}")
        pipeline_cfg = None

    if pipeline_cfg is not None and pipeline_cfg.prechop is not None:
        # When the user supplied an explicit --time-sig (non-default), let the
        # numerator override the pipeline's prechop.beats_per_bar so 7/4, 3/4,
        # 6/8 chunks land on real musical-bar boundaries instead of 4-beat
        # grids. Default 4/4 leaves the pipeline config untouched.
        if fallback_numerator != 4:
            pipeline_cfg.prechop.beats_per_bar = fallback_numerator

        # Resolve pre_bars: explicit value, or auto-fill the intro to keep
        # all preceding bars as chunks on the same bar grid (the user almost
        # never wants to silently drop 22 seconds of intro audio).
        bars_per_chunk = pipeline_cfg.prechop.bars
        bar_period_sec = bars_per_chunk * pipeline_cfg.prechop.beats_per_bar * 60.0 / bpm
        if pre_bars is None:
            # Auto: round DOWN to a whole-chunk count of intro bars.
            n_pre_chunks = int(first_downbeat_sec // bar_period_sec)
            resolved_pre_bars = n_pre_chunks * bars_per_chunk
        else:
            resolved_pre_bars = max(0, pre_bars)

        console.print()
        console.print(
            f"[bold]Prechop[/bold]  bars={pipeline_cfg.prechop.bars} "
            f"pad_bars={pipeline_cfg.prechop.pad_bars} "
            f"pad_last={pipeline_cfg.prechop.pad_last} "
            f"first_downbeat={first_downbeat_sec:.3f}s "
            f"pre_bars={resolved_pre_bars}"
        )
        try:
            status_post = run_post_split_steps(
                pipeline_cfg,
                stem_paths,
                track_out,
                bpm=bpm,
                first_downbeat_sec=first_downbeat_sec,
                pre_bars=resolved_pre_bars,
                pad_pre_bars=pad_pre_bars,
                pad_post_bars=pad_post_bars,
                emit_partial=emit_partial,
            )
            pc = status_post.get("prechop", {})
            if pc:
                console.print(f"  Written: {pc['manifest']}")
        except Exception as e:
            console.print(f"  [red]prechop failed:[/red] {e}")

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
    console.print("\n[dim]The M4L device in Ableton will detect stems.json automatically.[/dim]")
    console.print("[dim]Or: Ableton browser → Places → stemforge/processed → drag files.[/dim]")

    # If auto-detection wasn't high-confidence, surface the re-anchor escape
    # hatch — it's the difference between a 30s re-forge and a sub-second fix.
    if not overrides_active and reconciled.confidence != "high":
        console.print()
        console.print("[yellow]Detection confidence was not high.[/yellow] If chunks look")
        console.print("misaligned in arrangement view:")
        console.print(
            f"  1. [cyan]uv run python tools/probe_loop.py {audio_file} "
            f"--bpm BPM --first-downbeat DN --start-bar 28[/cyan]"
        )
        console.print("     iterate BPM + DN until the loop seam is clean and kick is on bar 1")
        console.print(
            f"  2. [cyan]stemforge re-anchor {track_out} --bpm BPM --first-downbeat DN[/cyan]"
        )
        console.print("     rewrites prechop in-place; no Demucs re-run needed (~1s).")


@cli.command("re-anchor")
@click.argument("track_dir", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--bpm", type=float, required=True, help="Manual BPM override.")
@click.option(
    "--first-downbeat",
    "first_downbeat",
    type=float,
    required=True,
    help="Where bar 1 starts in the source audio (seconds).",
)
@click.option(
    "--pre-bars",
    type=int,
    default=None,
    help="Bars of intro material BEFORE bar 1 to include as additional chunks at the same bar grid. "
    "Default: auto-fill the intro. Pass 0 to drop the intro entirely.",
)
@click.option(
    "--pad-pre-bars",
    type=int,
    default=1,
    help="Bars of pre-pad inside each chunk WAV (default 1 = drag-extend headroom backward).",
)
@click.option(
    "--pad-post-bars",
    type=int,
    default=1,
    help="Bars of post-pad inside each chunk WAV (default 1 = drag-extend headroom forward).",
)
@click.option(
    "--emit-partial/--no-emit-partial",
    default=True,
    help="Emit a leading partial chunk_001 capturing the sub-chunk-period "
    "intro material between source frame 0 and bar 1. Default: True. "
    "Pass --no-emit-partial to drop the intro entirely (the prior auto-gate "
    "behavior, removed because RMS-based gating flipped binary on sub-dB "
    "noise-floor drift between Demucs runs).",
)
@click.option(
    "--keep-old",
    is_flag=True,
    default=False,
    help="Keep the previous prechop output as `<stem>_prechop.bak/` instead of overwriting.",
)
@click.option(
    "--then-curate/--no-then-curate",
    default=False,
    help="After re-anchoring, run a fresh curation pass at the new anchor — "
    "picks new bars by diversity selection rather than just re-cutting the "
    "existing picks. Replays strategy/n_bars from the existing curated/manifest.json. "
    "Default (--no-then-curate) preserves the legacy behavior: reslice-only, "
    "keeps user picks. Has no effect when curated/ is absent.",
)
@with_audit("re-anchor")
def re_anchor(
    track_dir,
    bpm,
    first_downbeat,
    pre_bars,
    pad_pre_bars,
    pad_post_bars,
    emit_partial,
    keep_old,
    then_curate,
):
    """
    Re-cut the prechop chunks of an already-forged track at user-supplied
    BPM + first_downbeat. Skips Demucs re-run (~30 s saved) — only re-runs
    the chunk extraction step. Use after `probe_loop.py` confirms values.

    \b
    Iteration loop when auto-detection fails:
      1. stemforge split track.wav --pipeline arrangement
      2. drag a chunk into Ableton — kicks off bar grid?
      3. uv run python tools/probe_loop.py track.wav \\
              --bpm 85.11 --first-downbeat 0.1 --start-bar 28
         (iterate BPM + DN until loop is seamless and kick on bar 1)
      4. stemforge re-anchor PROCESSED/track --bpm 85.11 --first-downbeat 0.1
         → done in ~1 s, no Demucs.

    \b
    What gets rewritten:
      - <stem>_prechop/ (recut at new BPM/downbeat)
      - prechop_manifest.json
      - stems.json (tempo provenance updated with re-anchor history)

    \b
    What stays put:
      - drums.wav / bass.wav / vocals.wav / other.wav (Demucs output unchanged)
      - <stem>_beats/ (per-beat slices unchanged)
      - input_audio fingerprint (sha256 + sample_rate + duration_samples)
    """
    import json
    from .manifest import TempoProvenance, _input_audio_for, write_manifest
    from .pipelines import load_pipeline, run_post_split_steps

    if bpm <= 0:
        console.print(f"[red]--bpm must be > 0, got {bpm}[/red]")
        sys.exit(1)
    if first_downbeat < 0:
        console.print(f"[red]--first-downbeat must be >= 0, got {first_downbeat}[/red]")
        sys.exit(1)

    stems_json = track_dir / "stems.json"
    if not stems_json.exists():
        console.print(f"[red]No stems.json at {stems_json}[/red]")
        sys.exit(1)

    sj = json.loads(stems_json.read_text())
    track_name = sj["track_name"]
    pipeline_name = sj.get("pipeline", "default")
    backend = sj.get("backend", "demucs")

    # Reconstruct stem_paths from stems.json
    stem_paths = {}
    for s in sj["stems"]:
        wav = Path(s["wav_path"])
        if not wav.exists():
            console.print(f"[red]Missing stem WAV: {wav}[/red]")
            sys.exit(1)
        stem_paths[s["name"]] = wav

    console.print(Rule(f"[bold cyan]StemForge re-anchor[/bold cyan] — {track_name}"))
    console.print(f"  Track dir:      {track_dir}")
    console.print(f"  Old BPM:        [yellow]{sj['bpm']}[/yellow]")
    console.print(f"  New BPM:        [green]{bpm}[/green]")
    if sj.get("tempo"):
        old_dn = sj["tempo"].get("first_downbeat_sec")
        console.print(
            f"  Old first_downbeat: [yellow]{old_dn}s[/yellow]"
            if old_dn is not None
            else "  Old first_downbeat: [dim]none recorded[/dim]"
        )
    console.print(f"  New first_downbeat: [green]{first_downbeat}s[/green]")

    # Backup or wipe old prechop dirs
    import shutil as _sh

    for stem_name in stem_paths:
        old_dir = track_dir / f"{stem_name}_prechop"
        if not old_dir.exists():
            continue
        if keep_old:
            bak = track_dir / f"{stem_name}_prechop.bak"
            if bak.exists():
                _sh.rmtree(bak)
            old_dir.rename(bak)
            console.print(f"  [dim]backed up {old_dir.name} → {bak.name}[/dim]")
        else:
            _sh.rmtree(old_dir)

    old_manifest = track_dir / "prechop_manifest.json"
    if old_manifest.exists() and keep_old:
        old_manifest.rename(track_dir / "prechop_manifest.bak.json")

    # Synthesize beat times from override values for the slice_at_beats path
    # we don't actually rerun (we'd need duration here only for stems.json).
    # The reconciler is also skipped — re-anchor trusts the user's values
    # by definition.

    # Re-run prechop with overrides
    pipeline_cfg = load_pipeline(pipeline_name)
    if pipeline_cfg is None or pipeline_cfg.prechop is None:
        console.print(
            f"[yellow]Pipeline {pipeline_name!r} has no prechop block — nothing to re-anchor.[/yellow]"
        )
        sys.exit(0)

    # BPM refinement (always-on). The user passes Live's session tempo via
    # --bpm, but Live's tempo often inherits the original beat-this estimate
    # which has ~0.1-0.4% residual bias (Definition 2026-05-06: estimate
    # 90.23 vs truth 89.88). Cross-correlation of a bar-comb against kick
    # onsets in the drums stem recovers the true BPM to ~0.01 BPM accuracy.
    # The user's --first-downbeat is held fixed (it's their locator-anchored
    # bar 1 — the trustworthy axis to refine BPM around).
    drums_path = stem_paths.get("drums")
    if drums_path and drums_path.exists():
        from .tempo_reconciler import refine_bpm

        refined_bpm = refine_bpm(drums_path, bpm, first_downbeat)
        bpm_delta = refined_bpm - bpm
        if abs(bpm_delta) >= 0.005:
            console.print(
                f"  [cyan]refine-bpm[/cyan] shifted BPM: "
                f"{bpm:.4f} → {refined_bpm:.4f} (Δ {bpm_delta:+.4f})"
            )
            bpm = refined_bpm

    bars_per_chunk = pipeline_cfg.prechop.bars
    bar_period_sec = bars_per_chunk * pipeline_cfg.prechop.beats_per_bar * 60.0 / bpm
    if pre_bars is None:
        n_pre_chunks = int(first_downbeat // bar_period_sec)
        resolved_pre_bars = n_pre_chunks * bars_per_chunk
    else:
        resolved_pre_bars = max(0, pre_bars)

    console.print()
    console.print(
        f"[bold]Re-cutting prechop[/bold]  bars={pipeline_cfg.prechop.bars} "
        f"pad_bars={pipeline_cfg.prechop.pad_bars} "
        f"first_downbeat={first_downbeat}s "
        f"pre_bars={resolved_pre_bars}"
    )
    status = run_post_split_steps(
        pipeline_cfg,
        stem_paths,
        track_dir,
        bpm=bpm,
        first_downbeat_sec=first_downbeat,
        pre_bars=resolved_pre_bars,
        pad_pre_bars=pad_pre_bars,
        pad_post_bars=pad_post_bars,
        emit_partial=emit_partial,
    )
    pc = status.get("prechop", {})
    if pc:
        console.print(f"  Written: {pc['manifest']}")

    # Update stems.json's tempo provenance to reflect the re-anchor
    prior_source = sj.get("tempo", {}).get("source", "unknown")
    prior_bpm = sj.get("bpm")
    prior_dn = sj.get("tempo", {}).get("first_downbeat_sec")
    reanchor_warning = (
        f"re-anchored from bpm={prior_bpm} first_downbeat={prior_dn}s "
        f"(prior source: {prior_source})"
    )
    if sj.get("tempo", {}).get("warning"):
        reanchor_warning = f"{reanchor_warning} | prior: {sj['tempo']['warning']}"

    tempo_provenance = TempoProvenance(
        source="user-override",
        confidence="high",
        first_downbeat_sec=float(first_downbeat),
        n_downbeats=int((sj.get("tempo") or {}).get("n_downbeats", 0)),
        warning=reanchor_warning,
        all_estimates=(sj.get("tempo") or {}).get("all_estimates", []),
    )

    # Re-write stems.json (preserve audio fingerprint, slice counts unchanged)
    slice_counts = {s["name"]: s["beat_count"] for s in sj["stems"]}
    source_file = Path(sj["source_file"])
    input_audio = None
    if sj.get("input_audio"):
        from .manifest import InputAudio

        ia = sj["input_audio"]
        input_audio = InputAudio(
            sample_rate=ia["sample_rate"],
            duration_samples=ia["duration_samples"],
            sha256=ia["sha256"],
        )
    elif source_file.exists():
        input_audio = _input_audio_for(source_file)

    write_manifest(
        output_dir=track_dir,
        track_name=track_name,
        source_file=source_file,
        backend=backend,
        bpm=bpm,
        beat_count=sj.get("beat_count", 0),
        stem_paths=stem_paths,
        slice_counts=slice_counts,
        pipeline=pipeline_name,
        tempo=tempo_provenance,
        input_audio=input_audio,
    )

    # Keep curated bars in sync with the new anchor (loops only — one-shots
    # are peak-anchored and grid-independent). Skip silently if no curated
    # output exists for this track.
    #
    # Two modes:
    #   default (--no-then-curate): --reslice-only — preserves user picks,
    #     re-cuts the existing curated/<stem>/bar_NNN.wav set at the new
    #     grid. Cheap, fast, no LarsNet rerun.
    #   --then-curate: full diversity-selection pass at the new anchor.
    #     Discards existing picks and replays strategy/n_bars from the
    #     curated manifest. Used when the user wants the configurator's
    #     "re-anchoring auto-triggers curation re-run" workflow.
    curated_manifest_path = track_dir / "curated" / "manifest.json"
    if curated_manifest_path.exists():
        import subprocess as _sp

        script = Path(__file__).resolve().parents[1] / "v0/src/stemforge_curate_bars.py"
        if not script.exists():
            console.print(
                f"  [yellow]curate script not found at {script}; curated/ left untouched.[/yellow]"
            )
        elif then_curate:
            existing = json.loads(curated_manifest_path.read_text())
            replay_strategy = existing.get("strategy", "max-diversity")
            replay_n_bars = int(existing.get("n_bars", 16))
            replay_time_sig = int(existing.get("time_signature_numerator", 4))
            console.print()
            console.print(
                "[bold]Fresh curation pass[/bold] at new anchor "
                f"[dim](strategy={replay_strategy}, n_bars={replay_n_bars}, time_sig={replay_time_sig})[/dim]"
            )
            _r = _sp.run(
                [
                    sys.executable,
                    str(script),
                    "--stems-dir",
                    str(track_dir),
                    "--strategy",
                    replay_strategy,
                    "--n-bars",
                    str(replay_n_bars),
                    "--time-sig",
                    str(replay_time_sig),
                ],
                check=False,
            )
            if _r.returncode != 0:
                console.print(
                    "  [yellow]curate exited non-zero — curated loops may be "
                    "stale; run `stemforge forge --curation ...` to retry.[/yellow]"
                )
            else:
                console.print("  curated/manifest.json + bar WAVs replaced with fresh picks.")
        else:
            console.print()
            console.print(
                "[bold]Re-slicing curated loops[/bold] at new anchor "
                f"[dim](preserving picks from {curated_manifest_path.name})[/dim]"
            )
            _r = _sp.run(
                [
                    sys.executable,
                    str(script),
                    "--stems-dir",
                    str(track_dir),
                    "--reslice-only",
                ],
                check=False,
            )
            if _r.returncode != 0:
                console.print(
                    "  [yellow]reslice exited non-zero — curated loops may be "
                    "stale; run `stemforge re-curate` if needed.[/yellow]"
                )
            else:
                console.print("  curated/manifest.json + bar WAVs updated.")

    # ── New-shape configurator manifests (Phase 1A) ──
    # When curated/ exists, project it into the new two-file shape so the
    # configurator + popup consumers see the post-anchor bpm + clips.
    if curated_manifest_path.exists():
        try:
            from .forge import (
                build_empty_arrangement,
                build_from_curated_dict,
                write_arrangement,
                write_auto_curation,
            )

            _curated_dict = json.loads(curated_manifest_path.read_text())
            _fm = build_from_curated_dict(
                slug=track_name,
                forge_dir=track_dir,
                curated=_curated_dict,
                bpm=float(bpm),
                first_downbeat_sec=float(first_downbeat),
            )
            write_auto_curation(track_dir, _fm)
            _am = build_empty_arrangement(
                slug=track_name,
                source_audio=str(source_file),
                bpm=float(bpm),
                first_downbeat_sec=float(first_downbeat),
            )
            write_arrangement(track_dir, _am)
        except Exception as exc:  # noqa: BLE001 — non-fatal during re-anchor
            console.print(f"  [yellow]configurator manifests not refreshed: {exc}[/yellow]")

    console.print()
    console.print(Rule("[bold green]Re-anchored[/bold green]"))
    console.print(f"  BPM: [cyan]{bpm}[/cyan]  first_downbeat: [cyan]{first_downbeat}s[/cyan]")
    console.print("  stems.json + prechop_manifest.json updated.")
    if curated_manifest_path.exists():
        if then_curate:
            console.print("  curated/ rebuilt with fresh diversity picks at new anchor.")
        else:
            console.print("  curated/ re-sliced at new anchor.")
        console.print("  auto_curation_manifest.json + arrangement_manifest.json refreshed.")
    if keep_old:
        console.print("  [dim]Old chunks preserved at <stem>_prechop.bak/.[/dim]")


@cli.command("reslice-curated")
@click.argument("track_dir", type=click.Path(exists=True, file_okay=False, path_type=Path))
@with_audit("reslice-curated")
def reslice_curated(track_dir):
    """
    Re-cut curated bar loops at the current stems.json anchor.

    Use after `stemforge re-anchor` if you skipped the auto-reslice
    (or pre-PR, when re-anchor didn't sync curated/). Rewrites every
    curated/<stem>/bar_NNN.wav from the original stem at the new BPM +
    first_downbeat, preserving the user's picks (source_bar_index,
    one-shots, drum substems). One-shots are peak-anchored and stay
    untouched.

    For a fresh diversity selection (different picks, not just a different
    grid), run `stemforge forge --curation ...` instead.
    """
    import subprocess as _sp

    stems_json = track_dir / "stems.json"
    curated = track_dir / "curated" / "manifest.json"
    if not stems_json.exists():
        console.print(f"[red]No stems.json at {stems_json}[/red]")
        sys.exit(1)
    if not curated.exists():
        console.print(f"[red]No curated/manifest.json at {curated} — nothing to re-slice.[/red]")
        sys.exit(1)

    script = Path(__file__).resolve().parents[1] / "v0/src/stemforge_curate_bars.py"
    if not script.exists():
        console.print(f"[red]curate script missing at {script}[/red]")
        sys.exit(1)

    console.print(Rule(f"[bold cyan]StemForge reslice-curated[/bold cyan] — {track_dir.name}"))
    result = _sp.run(
        [sys.executable, str(script), "--stems-dir", str(track_dir), "--reslice-only"],
        check=False,
    )
    if result.returncode != 0:
        console.print(f"[red]reslice exited {result.returncode}[/red]")
        sys.exit(1)

    # Refresh the new-shape configurator manifests (Phase 1A) so the popup
    # sees the post-reslice clip set with a fresh manifest_hash.
    try:
        from .forge import (
            build_empty_arrangement,
            build_from_curated_dict,
            write_arrangement,
            write_auto_curation,
        )

        _stems = json.loads(stems_json.read_text())
        _curated_dict = json.loads(curated.read_text())
        _bpm = float(_curated_dict.get("bpm") or _stems.get("bpm") or 120.0)
        _dn = float((_stems.get("tempo") or {}).get("first_downbeat_sec") or 0.0)
        _slug = _stems.get("track_name") or track_dir.name
        _fm = build_from_curated_dict(
            slug=_slug,
            forge_dir=track_dir,
            curated=_curated_dict,
            bpm=_bpm,
            first_downbeat_sec=_dn,
        )
        write_auto_curation(track_dir, _fm)
        _src = _stems.get("source_file") or str(track_dir)
        write_arrangement(
            track_dir,
            build_empty_arrangement(
                slug=_slug,
                source_audio=_src,
                bpm=_bpm,
                first_downbeat_sec=_dn,
            ),
        )
    except Exception as exc:  # noqa: BLE001
        console.print(f"[yellow]configurator manifests not refreshed: {exc}[/yellow]")

    console.print(Rule("[bold green]Resliced[/bold green]"))


# ── Configurator v1 (Phase 1A) — forge file-shape commands ──────────────────


def _resolve_forge_dir(slug_or_path: str | Path) -> tuple[str, Path]:
    """Resolve a slug/path arg into (slug, forge_dir).

    Accepts either a bare slug (`my_track`) → resolves under PROCESSED_DIR,
    or an explicit path (`./processed/my_track`) → uses the basename as
    the slug. Raises ClickException when the dir is missing.
    """
    p = Path(slug_or_path)
    if p.exists() and p.is_dir():
        return p.name, p
    # Treat as slug under PROCESSED_DIR
    forge_dir = PROCESSED_DIR / str(slug_or_path)
    if not forge_dir.exists():
        raise click.ClickException(
            f"forge `{slug_or_path}` not found "
            f"(looked for path `{p}` and slug under `{PROCESSED_DIR}`)"
        )
    return forge_dir.name, forge_dir


@cli.command("migrate-forge")
@click.argument("slug")
@with_audit("migrate-forge")
def migrate_forge(slug):
    """
    Migrate a forge's legacy ``curated/manifest.json`` to the new file shape.

    Reads ``~/stemforge/processed/<slug>/curated/manifest.json`` and writes
    two sibling files at the forge root:

      - ``auto_curation_manifest.json`` (ForgeManifest with manifest_hash)
      - ``arrangement_manifest.json`` (ArrangementManifest, chunks may be
        empty when the legacy file lacked arrangement data)

    Both writes are atomic (.tmp + os.replace). The legacy file is left in
    place for one release for compat; a follow-up cleanup will drop it.

    Argument can be either a forge slug (`my_track`) or an explicit
    forge-dir path (`./processed/my_track`).
    """
    from .forge import (
        ForgeManifestError,
        legacy_manifest_exists,
        migrate_legacy,
        new_manifest_exists,
    )

    slug, forge_dir = _resolve_forge_dir(slug)

    if new_manifest_exists(forge_dir) and not legacy_manifest_exists(forge_dir):
        console.print(f"[yellow]forge `{slug}` already on new shape; nothing to migrate.[/yellow]")
        return
    if not legacy_manifest_exists(forge_dir):
        raise click.ClickException(
            f"forge `{slug}` has no curated/manifest.json to migrate (forge dir: {forge_dir})"
        )

    try:
        fm_path, am_path = migrate_legacy(slug, forge_dir)
    except ForgeManifestError as exc:
        raise click.ClickException(str(exc)) from exc

    console.print(Rule(f"[bold cyan]migrate-forge[/bold cyan] — {slug}"))
    console.print(f"  wrote {fm_path.relative_to(forge_dir)}")
    console.print(f"  wrote {am_path.relative_to(forge_dir)}")
    console.print("  [dim]legacy curated/manifest.json left in place for one-release compat[/dim]")


@cli.command("re-curate")
@click.argument("slug")
@click.option(
    "--strategy",
    "-s",
    default=None,
    type=click.Choice(["max-diversity", "rhythm-taxonomy", "sectional"]),
    help="Override curation strategy. Default: re-use whatever the legacy manifest recorded.",
)
@click.option(
    "--n-bars",
    "-n",
    default=None,
    type=int,
    help="Override the number of bars curated. Default: re-use legacy manifest value.",
)
@with_audit("re-curate")
def re_curate(slug, strategy, n_bars):
    """
    Re-run auto-curation only — no stem separation.

    Reads existing stems from ``~/stemforge/processed/<slug>/`` (drums.wav,
    bass.wav, etc. already on disk from a prior ``stemforge forge`` or
    ``split``), runs the curator across the existing bar-slices, and
    writes a fresh ``auto_curation_manifest.json`` with a new
    ``manifest_hash``.

    Phase 4B's stale-detection hangs off this hash mutating: rerun this
    command after editing the curation pipeline YAML to force every
    curation that references this forge to surface a "stale" badge.
    """
    from .forge import (
        ForgeManifestError,
        build_empty_arrangement,
        build_from_curated_dict,
        write_arrangement,
        write_auto_curation,
    )

    slug, forge_dir = _resolve_forge_dir(slug)

    stems_json = forge_dir / "stems.json"
    if not stems_json.exists():
        raise click.ClickException(
            f"forge `{slug}` has no stems.json at {stems_json} — run `stemforge split` first."
        )

    script = Path(__file__).resolve().parents[1] / "v0/src/stemforge_curate_bars.py"
    if not script.exists():
        raise click.ClickException(f"curate script not found at {script}")

    # Replay strategy/n_bars from the existing manifest unless overridden.
    legacy_path = forge_dir / "curated" / "manifest.json"
    legacy_data: dict = {}
    if legacy_path.exists():
        try:
            legacy_data = json.loads(legacy_path.read_text())
        except json.JSONDecodeError:
            legacy_data = {}

    replay_strategy = strategy or legacy_data.get("strategy") or "max-diversity"
    replay_n_bars = n_bars if n_bars is not None else int(legacy_data.get("n_bars") or 16)
    replay_time_sig = int(legacy_data.get("time_signature_numerator") or 4)

    console.print(Rule(f"[bold cyan]re-curate[/bold cyan] — {slug}"))
    console.print(
        f"  strategy=[cyan]{replay_strategy}[/cyan] "
        f"n_bars=[cyan]{replay_n_bars}[/cyan] time_sig=[cyan]{replay_time_sig}[/cyan]"
    )

    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--stems-dir",
            str(forge_dir),
            "--strategy",
            replay_strategy,
            "--n-bars",
            str(replay_n_bars),
            "--time-sig",
            str(replay_time_sig),
        ],
        check=False,
    )
    if result.returncode != 0:
        raise click.ClickException(f"v0/src/stemforge_curate_bars.py exited {result.returncode}")

    if not legacy_path.exists():
        raise click.ClickException(
            f"curate script ran but no {legacy_path} appeared — cannot project new shape."
        )

    try:
        curated_dict = json.loads(legacy_path.read_text())
    except json.JSONDecodeError as exc:
        raise click.ClickException(f"re-curate wrote a malformed legacy manifest: {exc}") from exc

    stems_data = json.loads(stems_json.read_text())
    bpm_val = float(curated_dict.get("bpm") or stems_data.get("bpm") or 120.0)
    dn_val = float((stems_data.get("tempo") or {}).get("first_downbeat_sec") or 0.0)
    source_audio = curated_dict.get("source_audio") or stems_data.get("source_file") or ""

    try:
        fm = build_from_curated_dict(
            slug=slug,
            forge_dir=forge_dir,
            curated=curated_dict,
            bpm=bpm_val,
            first_downbeat_sec=dn_val,
        )
        fm_path = write_auto_curation(forge_dir, fm)
        am = build_empty_arrangement(
            slug=slug,
            source_audio=source_audio,
            bpm=bpm_val,
            first_downbeat_sec=dn_val,
        )
        am_path = write_arrangement(forge_dir, am)
    except ForgeManifestError as exc:
        raise click.ClickException(str(exc)) from exc

    console.print(f"  wrote {fm_path.relative_to(forge_dir)}")
    console.print(f"  wrote {am_path.relative_to(forge_dir)}")
    console.print(f"  manifest_hash=[green]{fm.manifest_hash[:16]}..[/green]")


@cli.command("list")
def list_options():
    """Show available Demucs models."""
    console.print("\n[bold]Demucs models:[/bold]")
    descs = {
        "default": "htdemucs — drums, bass, vocals, other (fast, ~1x realtime on M2)",
        "fine": "htdemucs_ft — same 4 stems, better quality, 4x slower",
        "6stem": "htdemucs_6s — adds guitar + piano (best for IDM sampling)",
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
    try:
        import socket

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(1.0)
        # OSC message: /live/song/trigger_builder (custom, requires M4L listener)
        # For now, just check if AbletonOSC is reachable
        sock.sendto(b"\x00", ("127.0.0.1", 11000))
        sock.close()
        console.print("[green]AbletonOSC detected on port 11000[/green]")
        console.print("[dim]Trigger the builder from the M4L device in Ableton.[/dim]")
    except Exception:
        pass

    console.print(Rule("[bold cyan]StemForge Template Builder[/bold cyan]"))
    console.print()

    tracks = [
        ("SF | Drums Raw", "Audio", "Red", "Compressor → EQ Eight"),
        (
            "SF | Drums Crushed",
            "Audio",
            "Red (dark)",
            "LO-FI-AF → Decapitator → Compressor → EchoBoy Jr",
        ),
        ("SF | Bass", "Audio", "Blue", "EQ Eight → Compressor → LO-FI-AF → Decapitator"),
        ("SF | Texture Verb", "Audio", "Green", "PhaseMistress → EchoBoy → Reverb → LO-FI-AF"),
        ("SF | Texture Crystallized", "Audio", "Teal", "Crystallizer → Reverb → Utility"),
        ("SF | Vocals", "Audio", "Orange", "EQ Eight → Compressor → LO-FI-AF → EchoBoy"),
        ("SF | Beat Chop Simpler", "MIDI", "Red", "Simpler → Decapitator → PrimalTap"),
    ]

    console.print("[bold]Automated setup (recommended):[/bold]")
    console.print("  1. Open your StemForge Templates set in Ableton")
    console.print("  2. Create a MIDI track → drag Max Instrument onto it")
    console.print("  3. Open Max editor → add [js stemforge_template_builder.js]")
    console.print("  4. Wire a [button] to inlet, [textedit] to outlet 0")
    console.print("  5. Click the button — all 7 tracks are built automatically")
    console.print("  6. Dial in VST3 params per setup.md, then Cmd+G to group")
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
@click.option(
    "--json-out", is_flag=True, default=False, help="Output raw JSON instead of formatted table."
)
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
    conf_color = (
        "green"
        if profile.genre_confidence > 0.6
        else "yellow"
        if profile.genre_confidence > 0.4
        else "red"
    )
    console.print(
        f"  Genre:      [bold cyan]{profile.genre}[/bold cyan]  "
        f"[{conf_color}]({profile.genre_confidence:.0%} confidence)[/{conf_color}]"
    )
    console.print(f"  BPM:        [cyan]{profile.bpm}[/cyan]")
    console.print()

    # ── Genre scores ──────────────────────────────────────────────────────
    console.print("[bold]Genre Scores (CLAP)[/bold]")
    sorted_genres = sorted(profile.genre_scores.items(), key=lambda x: x[1], reverse=True)
    for label, score in sorted_genres[:5]:
        bar = "█" * int(score * 40)
        console.print(f"  {label:<28s} {bar:<40s} {score:.1%}")
    console.print()

    # ── Instruments detected ───────────────────────────────────────────────
    console.print("[bold]Instruments Detected (AST)[/bold]")
    if profile.instruments_detected:
        for instr in profile.instruments_detected[:8]:
            score = profile.instrument_scores.get(instr, 0)
            bar = "█" * int(score * 40)
            console.print(f"  {instr:<35s} {bar:<40s} {score:.1%}")
    else:
        console.print("  [dim]No instruments detected above threshold[/dim]")
    console.print()

    # ── Spectral profile ───────────────────────────────────────────────────
    console.print("[bold]Spectral Profile (librosa)[/bold]")
    console.print(
        f"  Bass energy:    {'█' * int(profile.bass_ratio * 30):<30s} {profile.bass_ratio:.1%}"
    )
    console.print(
        f"  Mid energy:     {'█' * int(profile.mid_ratio * 30):<30s} {profile.mid_ratio:.1%}"
    )
    console.print(
        f"  High energy:    {'█' * int(profile.high_ratio * 30):<30s} {profile.high_ratio:.1%}"
    )
    console.print(
        f"  Percussive:     {'█' * int(profile.percussive_ratio * 30):<30s} {profile.percussive_ratio:.1%}"
    )
    console.print(
        f"  Complexity:     {'█' * int(profile.spectral_complexity * 30):<30s} {profile.spectral_complexity:.1%}"
    )
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
    model_key = {"htdemucs": "default", "htdemucs_ft": "fine", "htdemucs_6s": "6stem"}.get(
        profile.recommended_model, "default"
    )
    cmd = f"stemforge split {audio_file} --model {model_key}"
    console.print(f"  [bold]Run:[/bold]  [green]{cmd}[/green]")
    console.print()


@cli.command("clean-beats")
@click.option(
    "--threshold",
    "-t",
    default=1e-3,
    type=float,
    help="RMS threshold. Beats below this are deleted. Default: 0.001",
)
@click.option(
    "--dir",
    "-d",
    "target_dir",
    default=None,
    type=click.Path(path_type=Path),
    help=f"Directory to clean. Default: {PROCESSED_DIR}",
)
@click.option(
    "--dry-run", is_flag=True, default=False, help="Show what would be deleted without deleting."
)
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
            rms = float(np.sqrt(np.mean(data**2)))
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
                f"  {beat_dir.relative_to(base)}: [red]{action} {deleted}[/red] / kept {kept}"
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
            console.print(
                f"[green]OK[/green] {yaml_file.name} → {json_file.name} [dim](preset)[/dim]"
            )

    console.print("\nRestart or reload the M4L device to pick up changes.")


@cli.command()
@click.argument("audio_file", type=click.Path(exists=True, path_type=Path))
@click.option(
    "--analysis",
    type=click.Path(exists=True, path_type=Path),
    default=None,
    help="Ableton analysis JSON. If omitted, uses librosa beat detection.",
)
@click.option("--model", "-m", default="default")
@click.option(
    "--strategy",
    "-s",
    default="max-diversity",
    type=click.Choice(["max-diversity", "rhythm-taxonomy", "sectional"]),
)
@click.option("--n-bars", "-n", default=14, type=int, help="Number of bars to curate.")
@click.option(
    "--time-sig",
    default="4/4",
    help="Time signature (librosa fallback only). Format: numerator/denominator.",
)
@click.option("--output", "-o", default=None, type=click.Path(path_type=Path))
@click.option(
    "--curation",
    type=click.Path(exists=True, path_type=Path),
    default=None,
    help="Curation config YAML (e.g. pipelines/curation.yaml). When provided, "
    "delegates bar-slicing + curation to v0/src/stemforge_curate_bars.py and "
    "produces a production-mode manifest (layout_mode=production, version=2). "
    "Omit to use forge's built-in v1 curation path.",
)
@with_audit("forge")
def forge(audio_file, analysis, model, strategy, n_bars, time_sig, output, curation):
    backend = "demucs"
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

    emit(
        "started",
        track=track_name,
        audio=str(audio_file),
        backend=backend,
        strategy=strategy,
        n_bars=n_bars,
        output_dir=str(track_out),
    )

    # ── 1. Separation ──
    emit("progress", phase="splitting", pct=0)
    be = DemucsBackend()
    try:
        stem_paths = be.separate(audio_file, track_out, model=model)
    except Exception as e:
        emit("error", phase="splitting", message=str(e))
        sys.exit(1)
    emit("progress", phase="splitting", pct=100, stems=[str(p) for p in stem_paths.values()])

    # ── 2+3. Production curation (opt-in via --curation) ──
    # When a curation config is provided, delegate bar-slicing + curation to
    # v0/src/stemforge_curate_bars.py which writes a production-mode manifest
    # (layout_mode=production, version=2, drum oneshots, phrase structure).
    # When omitted, falls through to forge's legacy inline curator below.
    if curation is not None:
        import subprocess

        script = Path(__file__).resolve().parents[1] / "v0/src/stemforge_curate_bars.py"
        if not script.exists():
            emit(
                "error", phase="curating", message=f"stemforge_curate_bars.py not found at {script}"
            )
            sys.exit(1)
        result = subprocess.run(
            [
                sys.executable,
                str(script),
                "--stems-dir",
                str(track_out),
                "--curation",
                str(curation),
                "--json-events",
                "--n-bars",
                str(n_bars),
                "--strategy",
                strategy,
                "--time-sig",
                str(fallback_numerator),
            ],
            check=False,
        )
        if result.returncode != 0:
            emit(
                "error",
                phase="curating",
                message=f"stemforge_curate_bars.py exited {result.returncode}",
            )
            sys.exit(1)
        manifest_path = track_out / "curated" / "manifest.json"

        # ── 3.5 Mirror to new-shape configurator manifests (Phase 1A) ──
        # The v0 production curator writes the legacy single-file manifest;
        # we read it back and project into the new two-file shape so
        # downstream configurator consumers see the same data.
        from .forge import (
            build_empty_arrangement,
            build_from_curated_dict,
            write_arrangement,
            write_auto_curation,
        )

        _curated_dict: dict = {}
        try:
            _curated_dict = json.loads(manifest_path.read_text())
        except (OSError, json.JSONDecodeError):
            _curated_dict = {}
        _bpm_for_forge = (
            _curated_dict.get("bpm") if isinstance(_curated_dict.get("bpm"), (int, float)) else None
        )
        _fm = build_from_curated_dict(
            slug=track_name,
            forge_dir=track_out,
            curated=_curated_dict,
            bpm=_bpm_for_forge,
            first_downbeat_sec=float(_curated_dict.get("first_downbeat_sec", 0.0) or 0.0),
        )
        _fm_path = write_auto_curation(track_out, _fm)
        _am = build_empty_arrangement(
            slug=track_name,
            source_audio=str(audio_file),
            bpm=_fm.bpm,
            first_downbeat_sec=_fm.first_downbeat_sec,
        )
        _am_path = write_arrangement(track_out, _am)

        emit(
            "complete",
            output_dir=str(manifest_path.parent),
            manifest=str(manifest_path),
            auto_curation_manifest=str(_fm_path),
            arrangement_manifest=str(_am_path),
            manifest_hash=_fm.manifest_hash,
            bars=n_bars,
            mode="production",
        )
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
    reconciled_for_forge = None
    if analysis_data is None:
        drums_stem_f = stem_paths.get("drums") or stem_paths.get("drum")
        from .tempo_reconciler import reconcile_tempo as _reconcile

        reconciled_for_forge = _reconcile(
            mix_path=audio_file,
            drums_path=drums_stem_f,
            kick_tiebreaker=True,
            kick_workdir=track_out / "tempo_substems",
        )
        detected_bpm = reconciled_for_forge.bpm
        shared_beat_times = reconciled_for_forge.beat_times
        if shared_beat_times is None or len(shared_beat_times) == 0:
            # Reconciler had no usable beats — fall back to librosa.
            bpm_source = drums_stem_f or next(iter(stem_paths.values()))
            detected_bpm, shared_beat_times = detect_bpm_and_beats(bpm_source)
    else:
        # Ableton analysis JSON carries the project tempo at the top level.
        ab_bpm = analysis_data.get("bpm") or analysis_data.get("tempo")
        if ab_bpm is not None:
            detected_bpm = float(ab_bpm)

    for i, (stem_name, stem_path) in enumerate(non_residual):
        if analysis_data is not None:
            bars = slice_at_bars_from_analysis(
                stem_path,
                analysis_data,
                track_out,
                stem_name,
            )
        else:
            bars = slice_at_bars(
                stem_path,
                track_out,
                stem_name,
                time_sig_numerator=fallback_numerator,
                beat_times=shared_beat_times,
            )
        stem_bar_paths[stem_name] = sorted(bars)
        pct = int(((i + 1) / len(non_residual)) * 100)
        emit("progress", phase="slicing", pct=pct, stem=stem_name, bars=len(bars))

    total_bars = len(stem_bar_paths.get("drums", next(iter(stem_bar_paths.values()), [])))
    emit("progress", phase="slicing", pct=100, bars=total_bars)

    # ── 3. Curation on drums stem ──
    emit("progress", phase="curating", pct=0)
    curation_source = "drums" if "drums" in stem_bar_paths else next(iter(stem_bar_paths))
    drums_bar_dir = track_out / f"{curation_source}_bars"

    selected_drum_paths = _curator.curate(
        drums_bar_dir,
        n_bars=n_bars,
        strategy=strategy,
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
            analysis_data["time_signature"]["numerator"] if analysis_data else fallback_numerator
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
            entries.append(
                {
                    "position": pos,
                    "source_bar_index": src_idx,
                    "file": str(dest.relative_to(track_out)),
                }
            )
        curated_manifest["stems"][stem_name] = entries

    manifest_path = curated_root / "manifest.json"
    manifest_path.write_text(json.dumps(curated_manifest, indent=2))

    # ── 3.5 Emit new-shape configurator manifests (Phase 1A) ──
    # `auto_curation_manifest.json` + `arrangement_manifest.json` live at the
    # forge root next to `stems.json`. The legacy `curated/manifest.json` is
    # left in place for one release for backward compatibility with existing
    # exporters/readers; the compat shim in `stemforge.forge.manifest_io`
    # accepts both shapes.
    from .forge import (
        build_empty_arrangement,
        build_from_curated_dict,
        write_arrangement,
        write_auto_curation,
    )

    _forge_dn = (
        float(reconciled_for_forge.first_downbeat_sec)
        if reconciled_for_forge is not None and reconciled_for_forge.first_downbeat_sec is not None
        else 0.0
    )
    _fm = build_from_curated_dict(
        slug=track_name,
        forge_dir=track_out,
        curated=curated_manifest,
        bpm=detected_bpm,
        first_downbeat_sec=_forge_dn,
    )
    _fm_path = write_auto_curation(track_out, _fm)
    _am = build_empty_arrangement(
        slug=track_name,
        source_audio=str(audio_file),
        bpm=_fm.bpm,
        first_downbeat_sec=_forge_dn,
    )
    _am_path = write_arrangement(track_out, _am)

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
                BAR_INDEX_TO_LABEL[pad_idx] if pad_idx < len(BAR_INDEX_TO_LABEL) else None
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
            batch_samples.append(
                meta.model_copy(
                    update={
                        "file": str(wav_abs.relative_to(curated_root)),
                    }
                )
            )

    batch = BatchManifest(
        version=1,
        track=track_name,
        bpm=detected_bpm,
        samples=batch_samples,
    )
    batch_path = write_batch(curated_root, batch)

    emit("progress", phase="curating", pct=100, selected=len(selected_indices))
    emit(
        "complete",
        output_dir=str(curated_root),
        manifest=str(manifest_path),
        auto_curation_manifest=str(_fm_path),
        arrangement_manifest=str(_am_path),
        manifest_hash=_fm.manifest_hash,
        batch_manifest=str(batch_path),
        sidecars=len(batch_samples),
        bars=len(selected_indices),
    )


@cli.command()
@click.argument(
    "input_path", required=False, default=None, type=click.Path(exists=True, path_type=Path)
)
@click.option(
    "--target",
    "-t",
    required=True,
    type=click.Choice(["ep133", "chompi", "both"]),
    help="Target device.",
)
@click.option(
    "--workflow",
    "-w",
    default="compose",
    type=click.Choice(["compose", "perform"]),
    help="compose=single track deep, perform=multi-track curated.",
)
@click.option(
    "--output", "-o", default=None, type=click.Path(path_type=Path), help="Output directory."
)
@click.option(
    "--budget",
    is_flag=True,
    default=False,
    help="EP-133: render at 22050 Hz to double memory capacity.",
)
@click.option(
    "--firmware",
    default="tempo",
    type=click.Choice(["tempo", "tape"]),
    help="Chompi firmware variant.",
)
@click.option("--dry-run", is_flag=True, default=False, help="Show plan without writing files.")
@click.option(
    "--upload",
    is_flag=True,
    default=False,
    help="EP-133: upload samples via USB-MIDI SysEx after export.",
)
@click.option(
    "--start-slot", default=1, type=int, help="EP-133: starting sound slot for upload (default: 1)."
)
@click.option(
    "--manifest",
    default=None,
    type=click.Path(exists=True, path_type=Path),
    help="EP-133 v2 manifest-driven export. When provided, loads a curated "
    "manifest.json (Curation Stage v2 schema) and produces per-loop "
    "WAVs + SETUP.md sized for EP Sample Tool. Skips legacy "
    "directory-scan. Pairs with --config.",
)
@click.option(
    "--config",
    "config_path",
    default=None,
    type=click.Path(exists=True, path_type=Path),
    help="EP-133 v2 curation config YAML (e.g. pipelines/curation.yaml). "
    "Reads the `ep133_export:` block. Used with --manifest.",
)
def export(
    input_path,
    target,
    workflow,
    output,
    budget,
    firmware,
    dry_run,
    upload,
    start_slot,
    manifest,
    config_path,
):
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
            raise click.UsageError("--manifest is EP-133-specific; use --target ep133.")
        if input_path is not None:
            console.print("[yellow]--manifest provided; ignoring positional INPUT_PATH.[/yellow]")
        from .exporters.ep133_v2 import export_from_manifest

        out_root = Path(output) if output else Path("./export/ep133")
        if dry_run:
            console.print(f"[dim]DRY RUN: would export manifest {manifest} → {out_root}[/dim]")
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
            console.print(f"  [green]OK[/green] ep133 v2: {r['loops_exported']} loops → {song_out}")
            for w in r.get("warnings", []):
                console.print(f"  [yellow]warn:[/yellow] {w}")
        else:
            console.print(f"  [green]OK[/green] ep133 v2: → {song_out}")
        return

    # ── Legacy directory-scan path ────────────────────────────────────────────
    if input_path is None:
        raise click.UsageError("INPUT_PATH is required unless --manifest is provided.")

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


@cli.command("export-song")
@click.option(
    "--arrangement",
    "arrangement_path",
    required=True,
    type=click.Path(exists=True, path_type=Path),
    help="snapshot.json from the M4L arrangement reader (Track B output).",
)
@click.option(
    "--manifest",
    "manifest_path",
    required=True,
    type=click.Path(exists=True, path_type=Path),
    help="stems.json with a session_tracks block.",
)
@click.option(
    "--reference-template",
    required=False,
    type=click.Path(exists=True, path_type=Path),
    default=None,
    help="Captured reference .ppak used as a byte template by the writer.",
)
@click.option(
    "--project",
    "project_slot",
    default=1,
    type=click.IntRange(1, 9),
    help="EP-133 project slot (1..9). Default: 1.",
)
@click.option(
    "--out", "out_path", required=True, type=click.Path(path_type=Path), help="Output .ppak path."
)
@click.option(
    "--mode",
    default="locator",
    type=click.Choice(["locator"]),
    help="Scene-derivation mode. v1 only supports 'locator'.",
)
@click.option(
    "--write-spec/--no-write-spec",
    default=False,
    help=(
        "Also write the abstract ProjectSpec JSON next to the .ppak with "
        "suffix '.projectspec.json'. Useful for the configurator popup and "
        "for diffing arrangement → projection."
    ),
)
@with_audit("export-song")
def export_song(
    arrangement_path,
    manifest_path,
    reference_template,
    project_slot,
    out_path,
    mode,
    write_spec,
):
    """
    Build an EP-133 K.O. II song-mode .ppak from an Ableton arrangement snapshot.

    \b
    Pipeline:
      arrangement.json + stems.json → resolve_scenes → synthesize → build_ppak

    \b
    Example:
      stemforge export-song \\
        --arrangement snapshot.json \\
        --manifest stems.json \\
        --reference-template tests/ep133/fixtures/reference.ppak \\
        --project 1 \\
        --out song.ppak
    """

    from .exporters.ep133.projector import Ep133Projector

    console.print(Rule(f"[bold cyan]StemForge[/bold cyan] — export-song (mode={mode})"))
    console.print(f"  Arrangement: {arrangement_path}")
    console.print(f"  Manifest:    {manifest_path}")
    console.print(f"  Project:     [cyan]{project_slot}[/cyan]")
    console.print(f"  Output:      {out_path}")
    if reference_template:
        console.print(f"  Template:    {reference_template}")
    else:
        console.print(
            "  Template:    [yellow]<none>[/yellow] — synthesizing minimal template "
            "(device boots, but pad metadata is zero-filled). Pass "
            "--reference-template for a real device capture."
        )

    arrangement = json.loads(Path(arrangement_path).read_text())
    manifest = json.loads(Path(manifest_path).read_text())

    # Phase-2 schema (v2): unwrap songs[0] if the JS reader emitted the wrapped
    # shape. Legacy flat snapshots (existing fixtures, older .als exports) pass
    # through unchanged. Multi-song UI is v2 of the spec; v1 always reads index 0.
    songs_field = arrangement.get("songs")
    if isinstance(songs_field, list) and songs_field:
        arrangement = songs_field[0]

    bpm = float(arrangement.get("tempo", 120.0))
    sig_raw = arrangement.get("time_sig", [4, 4])
    time_sig = (int(sig_raw[0]), int(sig_raw[1]))

    console.print(
        f"  Tempo:       [cyan]{bpm:.2f}[/cyan]  Time sig: [cyan]{time_sig[0]}/{time_sig[1]}[/cyan]"
    )

    arrangement_length_sec = arrangement.get("arrangement_length_sec")
    projector = Ep133Projector()
    for warning in projector.validate(arrangement, manifest, project_slot=int(project_slot)):
        console.print(f"  [yellow]warn:[/yellow] {warning}")
    spec = projector.synthesize_spec(
        arrangement,
        manifest,
        project_bpm=bpm,
        time_sig=time_sig,
        project_slot=int(project_slot),
        arrangement_length_sec=(
            float(arrangement_length_sec) if arrangement_length_sec is not None else None
        ),
    )

    console.print(
        f"  Scenes:      [cyan]{len(spec.scenes)}[/cyan]  "
        f"Patterns: [cyan]{len(spec.patterns)}[/cyan]  "
        f"Pads: [cyan]{len(spec.pads)}[/cyan]  "
        f"Sounds: [cyan]{len(spec.sounds)}[/cyan]"
    )

    # PHASE 3 CLEANUP: this two-step (synthesize_spec → build_bytes_from_spec)
    # is the legacy direct path. Phase 3 should:
    #   1. Always build the Project (the --write-spec branch below).
    #   2. Drive bytes via ``projector.project_from_spec(project, manifest, ...)``.
    #   3. Drop the synthesize_spec + build_bytes_from_spec calls + the spec
    #      local; --write-spec becomes default-on (or the only mode).
    # Byte identity is pinned by tests/ep133/test_projector_spec_parity.py so
    # the swap is mechanically safe.
    payload = projector.build_bytes_from_spec(
        spec,
        reference_template=Path(reference_template) if reference_template else None,
    )
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(payload)

    if write_spec:
        # Phase-2: dump the abstract ProjectSpec next to the .ppak. Bytes-
        # identical to the direct path is enforced by test_projector_spec_parity.
        from .exporters.ep133.project_translator import (
            project_from_arrangement_and_manifest,
        )
        from .scene_model import project_to_path

        spec_out_path = out_path.with_suffix(".projectspec.json")
        project = project_from_arrangement_and_manifest(arrangement, manifest)
        for warning in projector.validate_spec(project):
            console.print(f"  [yellow]warn(spec):[/yellow] {warning}")
        project_to_path(project, spec_out_path)
        console.print(f"  Spec:        [green]{spec_out_path}[/green]")

    kb = len(payload) / 1024.0
    console.print(Rule("[bold green]Done![/bold green]"))
    console.print(f"  Wrote [bold]{out_path}[/bold] ({kb:.1f} KB)")


@cli.command("deck-from-manifest")
@click.argument(
    "manifest_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option(
    "--out",
    "out_path",
    type=click.Path(path_type=Path),
    default=None,
    help="Where to write the deck plan. Default: deck.yaml next to the manifest.",
)
@click.option(
    "--project",
    "project_name",
    default=None,
    help="Project name. Default: derived from manifest filename / directory.",
)
@click.option(
    "--project-slot",
    type=click.IntRange(1, 9),
    default=8,
    show_default=True,
    help="EP-133 project slot.",
)
@click.option(
    "--project-bpm",
    type=float,
    default=None,
    help="Project BPM. Default: read from manifest's `bpm` field, fallback 92.",
)
@click.option(
    "--format",
    "out_format",
    type=click.Choice(["yaml", "json"]),
    default="yaml",
    show_default=True,
    help="Output format.",
)
@click.option(
    "--edit-after/--no-edit-after",
    default=False,
    help="Open the generated deck plan in $EDITOR after writing.",
)
@click.option(
    "--profile",
    "force_profile",
    type=click.Choice(["vocal", "drum", "texture", "preserve_source"]),
    default=None,
    help=(
        "Override format_profile on every group (replaces the default "
        "vocal/vocal/drum/texture layout). Useful for single-source decks "
        "like an all-drum breakbeats kit."
    ),
)
@click.option(
    "--all-drum",
    "all_drum",
    is_flag=True,
    default=False,
    help="Shortcut for `--profile drum`. Mutually exclusive with --profile.",
)
@click.option(
    "--play-mode",
    "force_play_mode",
    type=click.Choice(["oneshot", "key", "loop"]),
    default=None,
    help=(
        "Override play_mode on every pad row (replaces the per-profile "
        "default — oneshot for vocal/texture, key for drum)."
    ),
)
def deck_from_manifest_cmd(
    manifest_path,
    out_path,
    project_name,
    project_slot,
    project_bpm,
    out_format,
    edit_after,
    force_profile,
    all_drum,
    force_play_mode,
):
    """
    Generate a starter deck plan from a curated manifest.

    \b
    Reads the manifest's `session_tracks` block and emits a deck.yaml
    where each group's entries map to EP-133 group A/B/C/D pads 1..12.
    Format profiles default to: A=vocal, B=vocal, C=drum, D=texture.
    Group A overflow (>12 entries) spills forward to B (and so on).

    \b
    Workflow:
      1. COMMIT in the forge device to write `curated/manifest.json`.
      2. stemforge deck-from-manifest curated/manifest.json
      3. Edit the resulting deck.yaml (project name, slot, pad swaps).
      4. stemforge build-deck deck.yaml --out verse_swap.ppak
    """
    import os
    import subprocess

    from .exporters.ep133.deck_autogen import (
        deck_from_manifest,
        to_json_string,
        to_yaml_string,
    )

    console.print(Rule("[bold cyan]StemForge[/bold cyan] — deck-from-manifest"))
    console.print(f"  Manifest:    {manifest_path}")

    manifest = json.loads(Path(manifest_path).read_text())

    if project_name is None:
        parent = manifest_path.parent
        if parent.name == "curated":
            project_name = parent.parent.name or "deck"
        else:
            project_name = parent.name or manifest_path.stem

    # Resolve --profile / --all-drum (mutually exclusive).
    if all_drum and force_profile and force_profile != "drum":
        raise click.BadParameter(
            "--all-drum and --profile are mutually exclusive (and --all-drum "
            f"implies drum; got --profile={force_profile})."
        )
    effective_profile = force_profile or ("drum" if all_drum else None)
    if effective_profile:
        console.print(
            f"  [yellow]Forcing format_profile=[/yellow][cyan]{effective_profile}[/cyan]"
            " on every group"
        )
    if force_play_mode:
        console.print(
            f"  [yellow]Forcing play_mode=[/yellow][cyan]{force_play_mode}[/cyan] on every pad"
        )

    plan = deck_from_manifest(
        manifest,
        manifest_path,
        project_name=project_name,
        project_slot=project_slot,
        project_bpm=project_bpm,
        force_format_profile=effective_profile,
        force_play_mode=force_play_mode,
    )

    # Surface the layout decisions so the user knows what to edit.
    in_counts = {
        g: len((manifest.get("session_tracks") or {}).get(g) or []) for g in ("A", "B", "C", "D")
    }
    out_counts = {g: len(plan["groups"].get(g, {}).get("pads", [])) for g in ("A", "B", "C", "D")}
    total_in = sum(in_counts.values())
    total_out = sum(out_counts.values())
    console.print(f"  Input:       {total_in} clips ({in_counts})")
    console.print(f"  Output:      {total_out} pads   ({out_counts})")
    if total_out < total_in:
        dropped = total_in - total_out
        console.print(
            f"  [yellow]Dropped {dropped} clip(s):[/yellow] no pad capacity. "
            "Trim the manifest or accept the truncation."
        )
    for g in ("A", "B", "C", "D"):
        if g in plan["groups"]:
            profile = plan["groups"][g]["format_profile"]
            console.print(f"  Group {g}:     {out_counts[g]} pads, format=[cyan]{profile}[/cyan]")

    if out_path is None:
        out_path = manifest_path.parent / ("deck.yaml" if out_format == "yaml" else "deck.json")

    text = to_yaml_string(plan) if out_format == "yaml" else to_json_string(plan)
    out_path.write_text(text)
    console.print(Rule("[bold green]Done![/bold green]"))
    console.print(f"  Wrote [bold]{out_path}[/bold]")
    console.print(
        f"  [dim]Next:[/dim] [bold]stemforge build-deck {out_path} --out deck.ppak[/bold]"
    )

    if edit_after:
        editor = os.environ.get("EDITOR") or os.environ.get("VISUAL") or "vi"
        subprocess.run([editor, str(out_path)], check=False)


@cli.command("build-deck")
@click.argument(
    "deck_plan",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option(
    "--out",
    "out_path",
    required=True,
    type=click.Path(path_type=Path),
    help="Output .ppak path.",
)
@click.option(
    "--reference-template",
    required=False,
    type=click.Path(exists=True, path_type=Path),
    default=None,
    help="Captured reference .ppak for byte-template fields.",
)
@click.option(
    "--project",
    "project_slot_override",
    type=click.IntRange(1, 9),
    default=None,
    help="Override the project slot from the plan (1..9).",
)
@click.option(
    "--write-spec/--no-write-spec",
    default=True,
    show_default=True,
    help="Also write the abstract ProjectSpec JSON next to the .ppak.",
)
@with_audit("build-deck")
def build_deck(deck_plan, out_path, reference_template, project_slot_override, write_spec):
    """
    Build a multi-source EP-133 kit (.ppak) from a deck plan.

    \b
    Workflow B / single-scene kit (configurator spec v4 Decision 12):
    one project, four groups × twelve pads, clips federated across N
    forge runs. Honors per-group format_profile (Decision 16) so a
    24-verse vocal deck fits inside the 64 MB device cap.

    \b
    Example deck plan (JSON):
      {
        "project": "verse_swap_deck_v1",
        "project_slot": 8,
        "project_bpm": 92,
        "groups": {
          "A": {"format_profile": "vocal", "pads": [
            {"pad": 1, "path": "verses/v1.wav", "source_bpm": 88}
          ]},
          "C": {"format_profile": "drum", "pads": [
            {"pad": 1, "source": "songs/01/curated/manifest.json", "clip": "slot:0", "group": "A"}
          ]}
        }
      }

    \b
    Example:
      stemforge build-deck deck.json \\
        --out verse_swap.ppak \\
        --reference-template tests/ep133/fixtures/reference.ppak
    """
    from .exporters.ep133.deck_plan import load_deck_plan, project_from_deck_plan
    from .exporters.ep133.projector import (
        EP133_MEMORY_CAP_BYTES,
        Ep133Projector,
    )
    from .scene_model import project_to_path

    console.print(Rule("[bold cyan]StemForge[/bold cyan] — build-deck"))
    console.print(f"  Plan:        {deck_plan}")
    console.print(f"  Output:      {out_path}")
    if reference_template:
        console.print(f"  Template:    {reference_template}")
    else:
        console.print("  Template:    [yellow]<none>[/yellow] — synthesizing minimal template")

    plan = load_deck_plan(deck_plan)
    plan_dir = deck_plan.parent
    project, clip_index = project_from_deck_plan(plan, plan_dir=plan_dir)

    project_slot = (
        project_slot_override
        if project_slot_override is not None
        else int(plan.get("project_slot", 1))
    )

    projector = Ep133Projector()
    warnings = projector.validate_spec(project)
    if warnings:
        for w in warnings:
            console.print(f"  [yellow]warn:[/yellow] {w}")

    memory_bytes = projector.estimate_memory_bytes(project)
    used_mb = memory_bytes / (1024 * 1024)
    cap_mb = EP133_MEMORY_CAP_BYTES / (1024 * 1024)
    if memory_bytes > EP133_MEMORY_CAP_BYTES:
        console.print(f"  Memory:      [red]{used_mb:.1f} / {cap_mb:.0f} MB — OVER CAP[/red]")
    else:
        headroom_mb = cap_mb - used_mb
        console.print(
            f"  Memory:      [green]{used_mb:.1f} / {cap_mb:.0f} MB[/green] "
            f"({headroom_mb:.1f} MB headroom)"
        )

    # 2026-05-11: surface synthesizer warnings (e.g. "pad X: source > 20s,
    # skipped") on the Rich console. Python's default handler prints to
    # stderr but Click captures stderr; without this wrap, the user has
    # no visible signal that pads were dropped during the build.
    import warnings as _warnings

    with _warnings.catch_warnings(record=True) as build_warnings:
        _warnings.simplefilter("always")
        payload = projector.project_kit(
            project,
            clip_index,
            project_slot=project_slot,
            reference_template=reference_template,
        )
    for w in build_warnings:
        console.print(f"  [yellow]warn:[/yellow] {w.message}")
    out_path.write_bytes(payload)

    if write_spec:
        spec_out_path = out_path.with_suffix(".projectspec.json")
        project_to_path(project, spec_out_path)
        console.print(f"  Spec:        [green]{spec_out_path}[/green]")

    kb = len(payload) / 1024.0
    console.print(Rule("[bold green]Done![/bold green]"))
    console.print(f"  Wrote [bold]{out_path}[/bold] ({kb:.1f} KB)")


# ── EP-133 live-device pad clear ──────────────────────────────────────────────


_EP133_GROUPS = ("A", "B", "C", "D")


def _parse_pad_coord(pad: str) -> tuple[str, int]:
    """Parse a pad coordinate string into (group, pad_num).

    Accepts two equivalent forms:

      - Letter+visual-position (recommended): ``A1`` .. ``D12``.
        Group = A/B/C/D, pad_num = 1..12 in visual top-to-bottom,
        left-to-right order (pad_num=10 is the bottom-left "." key).
      - Numeric 1..48: groups concatenated A=1..12, B=13..24, C=25..36, D=37..48.

    Returns ``(group, pad_num)`` where group ∈ {A,B,C,D} and pad_num ∈ 1..12.
    """
    if not pad:
        raise click.BadParameter("PAD must be a non-empty coordinate like A1 or 1..48")
    s = pad.strip().upper()

    # Numeric form: 1..48
    if s.isdigit():
        n = int(s)
        if not (1 <= n <= 48):
            raise click.BadParameter(
                f"numeric PAD must be 1..48 (groups A=1..12, B=13..24, C=25..36, D=37..48); got {n}"
            )
        group_idx = (n - 1) // 12
        pad_num = ((n - 1) % 12) + 1
        return _EP133_GROUPS[group_idx], pad_num

    # Letter+number form: A1..D12
    group_letter = s[0]
    if group_letter not in _EP133_GROUPS:
        raise click.BadParameter(
            f"PAD group must be one of A/B/C/D, got {group_letter!r} (from {pad!r})"
        )
    rest = s[1:]
    if not rest.isdigit():
        raise click.BadParameter(f"PAD pad number must be 1..12, got {rest!r} (from {pad!r})")
    pad_num = int(rest)
    if not (1 <= pad_num <= 12):
        raise click.BadParameter(f"PAD pad number must be 1..12, got {pad_num}")
    return group_letter, pad_num


@cli.command("ep133-clear-pad")
@click.argument("project_slot", type=click.IntRange(1, 9))
@click.argument("pad", type=str)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Build and print the SysEx frame in hex without opening the MIDI device. "
    "Use this to verify byte structure when no EP-133 is plugged in.",
)
def ep133_clear_pad(project_slot: int, pad: str, dry_run: bool) -> None:
    """
    Clear a single pad's sample slot on a connected EP-133 K.O. II.

    \b
    PROJECT_SLOT is the 1-based project number on the device (1..9).
    PAD coordinate accepts two equivalent forms:
      - Letter+visual-position (recommended): A1 .. D12. Pad numbers are
        visual top-to-bottom, left-to-right (pad_num=10 = bottom-left ".").
      - Numeric 1..48: A=1..12, B=13..24, C=25..36, D=37..48.

    \b
    Examples:
      stemforge ep133-clear-pad 8 A1            # group A, top-left pad
      stemforge ep133-clear-pad 8 D12 --dry-run # print SysEx hex, no MIDI I/O
      stemforge ep133-clear-pad 3 25            # numeric form: C1

    \b
    Implementation note (needs hardware validation):
      The clear is performed by writing {"sym":0} to the pad's fileId via the
      already-tested FILE_METADATA_SET path — the same primitive `build-deck`
      uses for pad assignments. Slot 0 is the device's unassigned sentinel.
      The pad's playback parameters (envelope, time mode, etc.) are NOT
      touched — only the slot binding is removed. Byte structure is
      regression-tested; behavior on a live device against a populated pad
      was not re-validated as part of this change.
    """
    from .exporters.ep133.payloads import build_assign_pad
    from .exporters.ep133.sysex import RequestIdAllocator, build_sysex

    group, pad_num = _parse_pad_coord(pad)

    console.print(Rule("[bold cyan]StemForge[/bold cyan] — ep133-clear-pad"))
    console.print(f"  Project: [cyan]{project_slot}[/cyan]")
    console.print(f"  Pad:     [cyan]{group}{pad_num}[/cyan]  (group={group}, pad_num={pad_num})")
    console.print('  Action:  write {"sym":0} to pad fileId (unassign)')

    payload = build_assign_pad(project_slot, group, pad_num, slot=0)

    if dry_run:
        # Synthesize a frame with a deterministic request_id so the hex
        # output is reproducible — handy for diffing against device captures.
        # Real sends will allocate a fresh random request_id.
        from .exporters.ep133.commands import TE_SYSEX_FILE

        frame = build_sysex(TE_SYSEX_FILE, payload, request_id=1)
        console.print()
        console.print("[bold]Dry-run SysEx frame[/bold] (request_id=1):")
        console.print(f"  payload (raw): {payload.hex()}")
        console.print(f"  frame  (wire): {frame.hex()}")
        console.print(f"  byte length:   payload={len(payload)}  frame={len(frame)}")
        console.print()
        console.print("[yellow]--dry-run set: no MIDI I/O.[/yellow]")
        return

    # Live send. Open the device, run the same assign_pad path build-deck uses.
    from .exporters.ep133.client import EP133Client, EP133UploadError
    from .exporters.ep133.transport import EP133PortNotFound

    # request_id allocator is constructed inside the client; reference it here
    # only to silence lint about the import. (left unused intentionally)
    _ = RequestIdAllocator

    try:
        with EP133Client.open() as client:
            client.clear_pad(project_slot, group, pad_num)
    except EP133PortNotFound as e:
        raise click.ClickException(f"EP-133 not found: {e}") from e
    except EP133UploadError as e:
        raise click.ClickException(f"EP-133 rejected clear-pad: {e}") from e

    console.print(Rule("[bold green]Done![/bold green]"))
    console.print(f"  Cleared pad {group}{pad_num} on project {project_slot}.")


if __name__ == "__main__":
    cli()


@cli.command("export-koala")
@click.argument(
    "project_dir",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
)
@click.option(
    "--loops-per-stem",
    type=int,
    default=4,
    show_default=True,
    help="Loops per stem in bank 1 (4 stems × N must be ≤ 16).",
)
@click.option(
    "--oneshots-per-part",
    type=int,
    default=None,
    help="Cap oneshots per drum part. Default: pack to fill bank 2 evenly.",
)
@click.option(
    "--output-dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=Path("koala_exports"),
    show_default=True,
    help="Where to write the .zip.",
)
@click.option(
    "--keep-unzipped",
    is_flag=True,
    help="Leave the staging folder next to the zip (debugging).",
)
def export_koala_cmd(
    project_dir: Path,
    loops_per_stem: int,
    oneshots_per_part: int | None,
    output_dir: Path,
    keep_unzipped: bool,
) -> None:
    """
    Export a curated stemforge project as a Koala Sampler bank set (.zip).

    \b
    PROJECT_DIR can be either:
      - the project root (e.g. processed/bel/) — we'll find curated/ inside it
      - the curated dir directly (e.g. processed/bel/curated/)

    \b
    Example:
        stemforge export-koala processed/bel
        # → koala_exports/bel_koala.zip
    """
    from .exporters.koala import KoalaExportConfig, export_koala

    if (project_dir / "curated").exists():
        curated_dir = project_dir / "curated"
    elif project_dir.name == "curated":
        curated_dir = project_dir
    else:
        raise click.ClickException(
            f"{project_dir} is not a stemforge project (no curated/ subdir) "
            f"nor a curated/ dir itself."
        )

    config = KoalaExportConfig(
        loops_per_stem=loops_per_stem,
        oneshots_per_part=oneshots_per_part,
        output_dir=output_dir,
        keep_unzipped=keep_unzipped,
    )

    click.echo(f"Building Koala export from {curated_dir}...")
    zip_path = export_koala(curated_dir, config)
    click.echo(f"✓ {zip_path} ({zip_path.stat().st_size / 1024 / 1024:.1f} MB)")
    click.echo("AirDrop to phone → share to 'Send to Koala Sampler' Shortcut.")
