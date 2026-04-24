#!/usr/bin/env python3
"""
ep133_load_project.py — Bulk-load one song's curated stems into an EP-133 project.

Reads a StemForge curated manifest.json, uploads the first N bar-loops of
each mapped stem group to sequential library slots, then assigns the pads
in the target project/group to those slots.

Pad layout (ascending from bottom-left, physical keypad order):
    bar_001 → label "."     pad_num 10
    bar_002 → label "0"     pad_num 11
    bar_003 → label "ENTER" pad_num 12
    bar_004 → label "1"     pad_num 7
    bar_005 → label "2"     pad_num 8
    bar_006 → label "3"     pad_num 9
    bar_007 → label "4"     pad_num 4
    bar_008 → label "5"     pad_num 5
    bar_009 → label "6"     pad_num 6
    bar_010 → label "7"     pad_num 1
    bar_011 → label "8"     pad_num 2
    bar_012 → label "9"     pad_num 3

Usage:
    uv run tools/ep133_load_project.py /path/to/curated/manifest.json \\
        --project 8 --groups A=drums B=bass C=other D=vocals \\
        --start-slot 701 [--pads 12] [--delay-ms 10] [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

# Bar index (0-based) → pad_num (visual position, 1-indexed top-to-bottom left-to-right).
# Encoding: ascending bar number maps to bottom-left first, matching physical keypad layout.
#   row 3 (bottom): .=10  0=11  ENTER=12
#   row 2:          1=7   2=8   3=9
#   row 1:          4=4   5=5   6=6
#   row 0 (top):    7=1   8=2   9=3
BAR_INDEX_TO_PAD_NUM = [10, 11, 12, 7, 8, 9, 4, 5, 6, 1, 2, 3]
BAR_INDEX_TO_LABEL   = [".", "0", "ENTER", "1", "2", "3", "4", "5", "6", "7", "8", "9"]


def parse_groups(group_args: list[str]) -> list[tuple[str, str]]:
    """Parse ['A=drums', 'B=bass', ...] → [('A', 'drums'), ...]."""
    result = []
    for arg in group_args:
        if "=" not in arg:
            raise ValueError(f"--groups entries must be GROUP=stem (got {arg!r})")
        group, stem = arg.split("=", 1)
        group = group.upper()
        if group not in "ABCD":
            raise ValueError(f"group must be A-D (got {group!r})")
        result.append((group, stem))
    return result


def load_manifest(manifest_path: Path) -> dict:
    with manifest_path.open() as f:
        return json.load(f)


def get_stem_loops(manifest: dict, stem_name: str) -> list[dict]:
    """Extract the loops list for a stem from the manifest.

    Handles both manifest formats:
      v1: stems[name] = [loop, ...]          (plain list)
      v2: stems[name] = {loops: [...], ...}  (dict with loops key)
    """
    stems = manifest.get("stems", {})
    if stem_name not in stems:
        available = list(stems.keys())
        raise KeyError(f"stem {stem_name!r} not in manifest (available: {available})")
    val = stems[stem_name]
    if isinstance(val, list):
        return val
    return val.get("loops", [])


def plan_load(
    manifest: dict,
    groups: list[tuple[str, str]],
    project: int,
    start_slot: int,
    n_pads: int,
) -> list[dict]:
    """Build the full operation plan without doing any I/O.

    Returns a list of dicts, one per (upload + assign) pair:
        {group, stem, bar_index, pad_num, pad_label, slot, wav_path}
    """
    ops = []
    for g_idx, (group, stem_name) in enumerate(groups):
        loops = get_stem_loops(manifest, stem_name)
        loops_sorted = sorted(loops, key=lambda l: l["position"])[:n_pads]
        if len(loops_sorted) < n_pads:
            print(
                f"  WARNING: stem {stem_name!r} only has {len(loops_sorted)} loops "
                f"(wanted {n_pads}); loading all of them",
                file=sys.stderr,
            )
        for bar_i, loop in enumerate(loops_sorted):
            slot = start_slot + g_idx * n_pads + bar_i
            ops.append({
                "group":     group,
                "stem":      stem_name,
                "bar_index": bar_i,
                "pad_num":   BAR_INDEX_TO_PAD_NUM[bar_i],
                "pad_label": BAR_INDEX_TO_LABEL[bar_i],
                "slot":      slot,
                "wav_path":  Path(loop["file"]),
            })
    return ops


def print_plan(ops: list[dict], project: int, track: str) -> None:
    print(f"\n  EP-133 load plan — {track!r}  →  Project {project}")
    print(f"  {'Group':<6} {'Stem':<10} {'Bar':<6} {'Pad':<7} {'Slot':<6} {'File'}")
    print(f"  {'-'*5} {'-'*9} {'-'*5} {'-'*6} {'-'*5} {'-'*30}")
    for op in ops:
        print(
            f"  {op['group']:<6} {op['stem']:<10} "
            f"bar_{op['bar_index']+1:03d}  "
            f"{op['pad_label']:<7} "
            f"{op['slot']:<6} "
            f"{op['wav_path'].name}"
        )
    print()


def run_load(
    ops: list[dict],
    project: int,
    delay_ms: int,
    dry_run: bool,
) -> list[dict]:
    """Execute uploads + pad assignments. Returns ops annotated with timing."""
    if dry_run:
        print("  DRY RUN — no device I/O performed\n")
        return ops

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from stemforge.exporters.ep133 import EP133Client

    results = []
    with EP133Client.open(inter_message_delay_s=delay_ms / 1000.0) as client:
        for i, op in enumerate(ops):
            wav = op["wav_path"]
            slot = op["slot"]
            group = op["group"]
            pad_num = op["pad_num"]

            t0 = time.monotonic()

            print(
                f"  [{i+1:>2}/{len(ops)}] uploading {wav.name}"
                f"  →  slot {slot} ...",
                end=" ",
                flush=True,
            )
            client.upload_sample(wav, slot=slot)
            print(f"done  ({time.monotonic()-t0:.1f}s)", flush=True)

            print(
                f"           assigning  P{project} {group}-{op['pad_label']}"
                f"  (pad_num={pad_num})  →  slot {slot} ...",
                end=" ",
                flush=True,
            )
            t1 = time.monotonic()
            client.assign_pad(project=project, group=group, pad_num=pad_num, slot=slot)
            print(f"done  ({time.monotonic()-t1:.1f}s)", flush=True)

            results.append({**op, "wav_path": str(op["wav_path"]), "ok": True})

    return results


def run_update_params(
    ops: list[dict],
    project: int,
    bpm: float | None,
    playmode: str | None,
    delay_ms: int,
    dry_run: bool,
) -> list[dict]:
    """Send metadata-only pad updates (no audio upload)."""
    kwargs = {}
    if bpm is not None:
        kwargs["time_mode"] = "bpm"
        kwargs["time_bpm"] = bpm
    if playmode is not None:
        kwargs["playmode"] = playmode

    desc = "  ".join(
        ([f"playmode={playmode}"] if playmode else [])
        + ([f"time_mode=bpm  {bpm:.2f} BPM"] if bpm else [])
    ) or "no changes"

    if dry_run:
        print(f"  DRY RUN — would set {desc} on {len(ops)} pads\n")
        return ops

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from stemforge.exporters.ep133 import EP133Client
    from stemforge.exporters.ep133.payloads import PadParams

    params = PadParams(**kwargs)
    results = []
    with EP133Client.open(inter_message_delay_s=delay_ms / 1000.0) as client:
        for i, op in enumerate(ops):
            slot = op["slot"]
            group = op["group"]
            pad_num = op["pad_num"]

            print(
                f"  [{i+1:>2}/{len(ops)}] P{project} {group}-{op['pad_label']}"
                f"  (pad_num={pad_num})  slot {slot}  →  {desc} ...",
                end=" ",
                flush=True,
            )
            t0 = time.monotonic()
            client.assign_pad(
                project=project, group=group, pad_num=pad_num, slot=slot, params=params
            )
            print(f"done  ({time.monotonic()-t0:.2f}s)", flush=True)
            results.append({**op, "wav_path": str(op["wav_path"]), "ok": True})

    return results


def write_report(
    ops: list[dict],
    manifest_path: Path,
    project: int,
    track: str,
    dry_run: bool,
) -> Path:
    report = {
        "track":     track,
        "project":   project,
        "dry_run":   dry_run,
        "loaded_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "ops": [
            {k: str(v) if isinstance(v, Path) else v for k, v in op.items()}
            for op in ops
        ],
    }
    stem = f"ep133_p{project}_{track}"
    report_path = manifest_path.parent / f"{stem}_load_report.json"
    report_path.write_text(json.dumps(report, indent=2))
    return report_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Bulk-load StemForge curated stems into an EP-133 project.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("manifest", type=Path, help="Path to curated manifest.json")
    parser.add_argument("--project",    "-P", type=int, default=8,
                        help="EP-133 project number (default: 8)")
    parser.add_argument("--groups",     "-g", nargs="+", required=True,
                        metavar="GROUP=stem",
                        help="Group→stem mappings, e.g. A=drums B=bass C=other D=vocals")
    parser.add_argument("--start-slot", "-s", type=int, default=701,
                        help="First library slot (default: 701)")
    parser.add_argument("--pads",       "-n", type=int, default=12,
                        help="Bars/pads to load per group (1-12, default: 12)")
    parser.add_argument("--delay-ms",      type=int, default=10,
                        help="Inter-message delay in ms (default: 10)")
    parser.add_argument("--dry-run",       action="store_true",
                        help="Print the plan without touching the device")
    parser.add_argument("--update-params", action="store_true",
                        help="Skip uploads; only push pad metadata to already-loaded slots")
    parser.add_argument("--playmode", choices=["oneshot", "key", "legato"], default=None,
                        help="Set playback mode on all pads (key=gate, stops when finger lifts)")
    args = parser.parse_args()

    if not (1 <= args.pads <= 12):
        parser.error("--pads must be 1-12")

    manifest_path = args.manifest.resolve()
    if not manifest_path.exists():
        parser.error(f"manifest not found: {manifest_path}")

    manifest = load_manifest(manifest_path)
    track = manifest.get("track", manifest_path.parent.parent.name)

    try:
        groups = parse_groups(args.groups)
    except ValueError as e:
        parser.error(str(e))

    try:
        ops = plan_load(manifest, groups, args.project, args.start_slot, args.pads)
    except KeyError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    bpm = manifest.get("bpm")

    print_plan(ops, args.project, track)
    if args.update_params:
        bpm_str = f"BPM={bpm:.2f}" if bpm else "no BPM"
        pm_str = f"playmode={args.playmode}" if args.playmode else "no playmode change"
        print(f"  Mode: --update-params  (metadata only, no uploads)  {pm_str}  {bpm_str}\n")

    try:
        if args.update_params:
            results = run_update_params(
                ops, args.project, bpm, args.playmode, args.delay_ms, args.dry_run
            )
        else:
            results = run_load(ops, args.project, args.delay_ms, args.dry_run)
    except Exception as e:
        print(f"\nERROR: {e}", file=sys.stderr)
        sys.exit(1)

    report_path = write_report(results, manifest_path, args.project, track, args.dry_run)
    print(f"  {'[DRY RUN] ' if args.dry_run else ''}report written → {report_path}")

    n_ops = len([r for r in results if isinstance(r.get("ok"), bool)])
    slots_used = f"{args.start_slot}–{args.start_slot + len(groups) * args.pads - 1}"
    print(f"\n  {n_ops} ops  |  slots {slots_used}  |  Project {args.project}")
    if not args.dry_run:
        print("  All done.")


if __name__ == "__main__":
    main()
