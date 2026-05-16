#!/usr/bin/env python3
"""
ep133_load_curation.py — Load a curation onto an EP-133 K.O. II over SysEx.

This is the direct-SysEx alternative to the TE Sample Tool ``.ppak`` import.
It uploads each pad's WAV to a library slot and assigns the pads — using the
same ``EP133Client`` primitives as ``ep133_load_project.py``. It never does
the full-filesystem enumeration that Sample Tool's project import livelocks
on, so it sidesteps that failure entirely.

Input is the ``*.projectspec.json`` that ``stemforge build-deck`` writes
next to its ``.ppak`` — it carries the resolved per-pad WAV path, play
mode, and source BPM. Run build-deck first, then point this at the spec:

    stemforge build-deck deck.json --out kit.ppak       # writes kit.projectspec.json
    uv run tools/ep133_load_curation.py kit.projectspec.json --project 1

Slot layout (matches the .ppak writer): group A→700.., B→720.., C→740..,
D→760.. — slot = 700 + 20*group_index + (pad_num - 1).

What this loads: samples + per-pad assignment (playmode, time mode, source
BPM). It does NOT write step-sequencer patterns or scenes — those live only
in the ``.ppak`` project tar.

Requires the ``ep133`` extra:  uv sync --extra ep133
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path

# group letter → 0-based index; slot base = START_SLOT + index * GROUP_STRIDE.
GROUPS = ("A", "B", "C", "D")
DEFAULT_START_SLOT = 700
GROUP_SLOT_STRIDE = 20  # matches stemforge.exporters.ep133 SAMPLE_SLOT_PER_GROUP


@dataclass
class LoadOp:
    """One (upload + assign) unit of work for a single pad."""

    group: str
    pad_num: int
    slot: int
    wav_path: Path
    source_bpm: float | None
    playmode: str
    time_mode: str


def _spec_song(spec: dict) -> dict:
    """Return the single song dict from a ProjectSpec, or raise."""
    songs = spec.get("songs") or []
    if not songs:
        raise ValueError("projectspec has no songs[]")
    return songs[0]


def plan_from_projectspec(
    spec: dict,
    *,
    start_slot: int = DEFAULT_START_SLOT,
    group_stride: int = GROUP_SLOT_STRIDE,
    playmode_override: str | None = None,
) -> list[LoadOp]:
    """Build the ordered upload+assign work list from a ProjectSpec dict.

    Pure function — no device I/O — so it is unit-testable. Pads with no
    ``clip`` are skipped. ``stretch_mode`` maps to the device's time mode
    ("bpm" → tempo-synced playback); a missing source BPM leaves the WAV's
    own embedded tempo to drive it.

    ``playmode_override`` forces every pad's play mode ("key" gates the
    sample to the pad hold; "oneshot" plays it through). When None each
    pad keeps the mode from the spec.
    """
    ops: list[LoadOp] = []
    for group in _spec_song(spec).get("groups", []):
        gid = str(group.get("group_id", "")).upper()
        if gid not in GROUPS:
            raise ValueError(f"unexpected group_id {gid!r} (want one of {GROUPS})")
        base = start_slot + GROUPS.index(gid) * group_stride
        for pad in group.get("pads", []):
            clip = pad.get("clip")
            if not clip or not clip.get("path"):
                continue  # empty pad — nothing to upload
            pad_num = int(pad["pad_id"])
            if not (1 <= pad_num <= 12):
                raise ValueError(f"{gid}: pad_id {pad_num} out of range 1..12")
            bpm = clip.get("source_bpm")
            ops.append(
                LoadOp(
                    group=gid,
                    pad_num=pad_num,
                    slot=base + (pad_num - 1),
                    wav_path=Path(clip["path"]),
                    source_bpm=float(bpm) if bpm else None,
                    playmode=playmode_override or str(pad.get("play_mode", "oneshot")),
                    time_mode="bpm" if pad.get("stretch_mode") == "bpm" else "off",
                )
            )
    return ops


def print_plan(ops: list[LoadOp], project: int) -> None:
    """Print the resolved plan as a table."""
    print(f"  Project P{project} — {len(ops)} pads\n")
    print(f"  {'GRP':<4}{'PAD':<5}{'SLOT':<6}{'BPM':<8}{'MODE':<14}WAV")
    for op in ops:
        bpm = f"{op.source_bpm:.1f}" if op.source_bpm else "-"
        missing = "" if op.wav_path.is_file() else "  <<< FILE MISSING"
        print(
            f"  {op.group:<4}{op.pad_num:<5}{op.slot:<6}{bpm:<8}"
            f"{op.playmode + '/' + op.time_mode:<14}{op.wav_path.name}{missing}"
        )


def _preflight(ops: list[LoadOp]) -> list[str]:
    """Return one error string per pad whose WAV is missing or empty."""
    errors: list[str] = []
    for op in ops:
        if not op.wav_path.is_file():
            errors.append(f"{op.group}{op.pad_num:02d}: file not found — {op.wav_path}")
        elif op.wav_path.stat().st_size == 0:
            errors.append(f"{op.group}{op.pad_num:02d}: file is empty — {op.wav_path}")
    return errors


def run_load(
    ops: list[LoadOp],
    project: int,
    delay_ms: int,
    *,
    assign_only: bool = False,
) -> int:
    """Upload each WAV + assign its pad. Returns the count processed.

    Mirrors ``ep133_load_project.run_load``: open one client, upload the
    sample, tag the slot with its source BPM, assign the pad. The device's
    bar inference then works at any project tempo.

    ``assign_only`` skips the sample upload and slot-BPM write — it just
    re-assigns the pads. Use it to change playback parameters (e.g. switch
    to key mode) on samples already in the device's library slots.
    """
    from stemforge.exporters.ep133 import EP133Client
    from stemforge.exporters.ep133.commands import TE_SYSEX_FILE
    from stemforge.exporters.ep133.payloads import (
        PadParams,
        SampleParams,
        build_slot_metadata_set,
    )

    loaded = 0
    with EP133Client.open(inter_message_delay_s=delay_ms / 1000.0) as client:
        for i, op in enumerate(ops):
            t0 = time.monotonic()
            verb = "assigning" if assign_only else "uploading"
            print(
                f"  [{i + 1:>2}/{len(ops)}] {op.group}{op.pad_num:02d} "
                f"slot {op.slot}  {verb} {op.wav_path.name} "
                f"({op.playmode}) ...",
                end=" ",
                flush=True,
            )
            if not assign_only:
                client.upload_sample(op.wav_path, slot=op.slot)
                if op.source_bpm is not None:
                    payload = build_slot_metadata_set(
                        op.slot,
                        SampleParams(bpm=op.source_bpm, time_mode=op.time_mode),
                    )
                    rid = client._send(TE_SYSEX_FILE, payload)
                    client._await_response(rid, timeout=5.0)

            # PadParams auto-pairs envelope.release with playmode
            # (key↔15, oneshot↔255) — required or gating silently fails.
            client.assign_pad(
                project=project,
                group=op.group,
                pad_num=op.pad_num,
                slot=op.slot,
                params=PadParams(playmode=op.playmode, time_mode=op.time_mode),
            )
            print(f"done ({time.monotonic() - t0:.1f}s)", flush=True)
            loaded += 1
    return loaded


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("projectspec", type=Path, help="Path to a *.projectspec.json (from build-deck)")
    ap.add_argument("--project", type=int, default=1, choices=range(1, 10), help="Target project slot 1..9")
    ap.add_argument("--start-slot", type=int, default=DEFAULT_START_SLOT, help="Library slot base for group A")
    ap.add_argument("--delay-ms", type=int, default=10, help="Inter-message delay")
    ap.add_argument(
        "--playmode",
        choices=("oneshot", "key", "legato"),
        default=None,
        help="Override every pad's play mode ('key' = gated to pad hold)",
    )
    ap.add_argument(
        "--assign-only",
        action="store_true",
        help="Skip sample upload; only re-assign pads (e.g. to change play mode)",
    )
    ap.add_argument("--dry-run", action="store_true", help="Print the plan; perform no MIDI I/O")
    args = ap.parse_args(argv)

    if not args.projectspec.is_file():
        print(f"error: projectspec not found: {args.projectspec}", file=sys.stderr)
        return 2
    try:
        spec = json.loads(args.projectspec.read_text())
        ops = plan_from_projectspec(
            spec, start_slot=args.start_slot, playmode_override=args.playmode
        )
    except (ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"error: bad projectspec: {exc}", file=sys.stderr)
        return 2

    if not ops:
        print("error: projectspec has no populated pads — nothing to load", file=sys.stderr)
        return 2

    mode = "re-assign pads only" if args.assign_only else "upload + assign"
    print(f"\n  StemForge — load curation to EP-133 (SysEx) — {mode}")
    print(f"  Spec: {args.projectspec}\n")
    print_plan(ops, args.project)

    # Sample files only need to exist when we're actually uploading them.
    if not args.assign_only:
        errors = _preflight(ops)
        if errors:
            print("\n  unexportable pads:")
            for e in errors:
                print(f"    - {e}")
            print("\n  Fix the WAVs and re-run.", file=sys.stderr)
            return 1

    if args.dry_run:
        print("\n  DRY RUN — no device I/O performed.")
        return 0

    print()
    try:
        loaded = run_load(
            ops, args.project, args.delay_ms, assign_only=args.assign_only
        )
    except ImportError:
        print(
            "error: EP-133 SysEx deps missing — run:  uv sync --extra ep133",
            file=sys.stderr,
        )
        return 2
    print(f"\n  Loaded {loaded}/{len(ops)} pads to project P{args.project}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
