#!/usr/bin/env python3
"""Upload a hybrid-session manifest to the EP-133 K.O. II.

Reads `session_tracks` from a curated manifest (produced by the COMMIT
button in the StemForge M4L device), bakes per-clip WAVs from the source
material, and uploads them with the EP-133 hybrid layout:

  Group A (slots 100-111): drum hits 1-4 (oneshots) + drum loops 5-8
  Group B (slots 120-127): bass key chops, time.mode=off, rootnote=60
  Group C (slots 140-151): vocal key chops, time.mode=off, rootnote=60
  Group D (slots 160-171): one-shot FX, time.mode=off

Per-clip behavior controlled by manifest.session_tracks[letter][i].mode:
  - "rotate": rotate the source WAV so start_offset_sec becomes sample 0;
              tail (the originally-pre-start audio) moves to the end.
              Same total length. Loops cleanly. Used for Group A drum loops.
  - "trim":   slice the source WAV from start_offset_sec to end_offset_sec.
              Shorter output. Used for Group B/C key chops, Group D FX.

Slot assignments map directly from session_tracks order:
  - A clips at slot 1 → slot_base+0; slot 2 → slot_base+1; etc.
  - Same for B/C/D within their slot ranges.

Usage:
    uv run python tools/ep133_load_hybrid_session.py \\
        /Users/zak/stemforge/processed/smack_my_bitch_up/curated/manifest.json \\
        [--project 1] [--dry-run] [--delay-ms 50]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import soundfile as sf


# Layout: per-letter slot_base + role/mute_group/time_mode rules.
LAYOUT = {
    "A": {
        "group": "A",
        "slot_base": 100,
        # First N pads = drum hits (no time stretch). Remaining pads = drum
        # loops (bar mode, 2 bars, mute group so only one loop plays at once).
        # Configurable threshold:
        "hits_until_pad": 4,
        "hit_rule": {"time_mode": "off", "time_bars": None, "mute_group": False, "kind": "hit"},
        "loop_rule": {"time_mode": "bar", "time_bars": 2.0, "mute_group": False, "kind": "loop"},
    },
    "B": {
        "group": "B",
        "slot_base": 120,
        # All slots = bass key chops, time.mode=off, mono mute group.
        # rootnote=60 (C4) so when KEYS is engaged on a B pad, the natural-
        # pitch pad (bottom-left per device convention) plays the chop
        # untransposed; pads ascend chromatically up the grid.
        "default_rule": {"time_mode": "off", "time_bars": None, "mute_group": True,
                         "kind": "key", "rootnote": 60},
    },
    "C": {
        "group": "C",
        "slot_base": 140,
        # All slots = vocal key chops, time.mode=off, no mute group (let them stack).
        "default_rule": {"time_mode": "off", "time_bars": None, "mute_group": False,
                         "kind": "key", "rootnote": 60},
    },
    "D": {
        "group": "D",
        "slot_base": 160,
        # All slots = one-shot FX, time.mode=off, no mute group
        "default_rule": {"time_mode": "off", "time_bars": None, "mute_group": False, "kind": "fx"},
    },
}


def rule_for_slot(letter: str, slot_idx: int) -> dict:
    cfg = LAYOUT[letter]
    # Group A uses hits_until_pad threshold to switch hit→loop rules.
    if "hits_until_pad" in cfg:
        if slot_idx < cfg["hits_until_pad"]:
            return cfg["hit_rule"]
        return cfg["loop_rule"]
    return cfg.get("default_rule", {"time_mode": "off", "time_bars": None, "mute_group": False, "kind": "key"})


def bottom_up_pad_num(n: int) -> int:
    """Map user-friendly pad N (1-12, fills bottom-left first) to the
    device's internal pad_num.

    Device internal pad_num grid (per ep133_protocol_spec.md §2):
        row 0 (top):    pad 1, pad 2, pad 3        (keys "7", "8", "9")
        row 1:          pad 4, pad 5, pad 6        (keys "4", "5", "6")
        row 2:          pad 7, pad 8, pad 9        (keys "1", "2", "3")
        row 3 (bottom): pad 10, pad 11, pad 12     (keys ".", "0", "E")

    User-friendly numbering fills bottom-up:
        N=1..3   → bottom row    (device 10, 11, 12)
        N=4..6   → row 2         (device 7, 8, 9)
        N=7..9   → row 1         (device 4, 5, 6)
        N=10..12 → top row       (device 1, 2, 3)
    """
    if n < 1 or n > 12:
        return n  # leave out-of-range alone — caller should validate
    row_from_bottom = (n - 1) // 3   # 0..3
    col = (n - 1) % 3                # 0..2
    return 10 - 3 * row_from_bottom + col


def detect_bars_value(dur_sec: float, bpm: float, tolerance_ms: float = 400.0) -> int | None:
    """If dur_sec is within tolerance of N bars at the given BPM (for
    N ∈ {1, 2, 4, 8}), return N; else None.

    Default 400ms tolerance forgives typical hand-drag imprecision in
    Ableton (a deliberate 2-bar trim often lands ~50-300ms off the bar
    boundary). The trade-off: EP-133 will time-stretch by up to ~10% to
    fit the target bar count, which is audible as a slight tempo/pitch
    bend but keeps the loop on the project's bar grid (which matters more
    for performance than exact pitch).
    """
    bar_dur = 60.0 * 4.0 / bpm
    for bars in (1, 2, 4, 8):
        if abs(dur_sec - bars * bar_dur) <= tolerance_ms / 1000.0:
            return bars
    return None


def per_clip_time_mode(rule: dict, baked_dur_sec: float, bpm: float) -> tuple[str, float | None]:
    """Pick (time_mode, time_bars) for the EP-133 metadata write based on
    the rule's intent AND the baked clip's actual duration.

    Logic:
      - Hits / chops / FX (rule says time.mode=off): always off.
      - Loops (rule says time.mode=bar): the bake step snaps to an exact
        bar count (1 or 2 for Group A loops), so the baked WAV is
        guaranteed to be N bars long. Tight tolerance (25ms) catches it
        cleanly; falls back to off only if something pathological.
    """
    if rule.get("time_mode") != "bar":
        return rule.get("time_mode", "off"), None
    # Loops: tight tolerance — bake snapped to exact bars already.
    bars = detect_bars_value(baked_dur_sec, bpm, tolerance_ms=25.0)
    if bars is None:
        return "off", None
    return "bar", float(bars)


def bake_clip(src_wav: Path, dst_wav: Path, entry: dict, rule: dict, bpm: float) -> tuple[int, int]:
    """Bake a session_tracks entry into a single WAV.

    `entry` has start_offset_sec, end_offset_sec, clip_length_sec, mode.
    `rule` carries the kind ("hit"/"loop"/"key"/"fx") which decides the
    bake strategy:

      - kind="loop": SNAP-TO-BAR. Take user's start_offset as the trigger
        point. Compute the user's intended bar count from the trimmed
        length (snap to 1 or 2 bars — Group A cap). Slice audio for
        exactly N bars starting at start_offset. Pad with silence if the
        slice would run past the source. This produces a clean N-bar
        loop with no time-stretch needed.

      - kind="hit"/"key"/"fx": TRIM (or ROTATE for full-length entries).
        Pure user-region slice; no bar snap. Hits are typically already
        at sample 0 with end at natural length → no transform.

    Returns (input_frames, output_frames).
    """
    info = sf.info(str(src_wav))
    sr = info.samplerate
    total = info.frames

    start_sec = float(entry.get("start_offset_sec", 0.0))
    end_sec = float(entry.get("end_offset_sec", entry.get("clip_length_sec", total / sr)))
    mode = entry.get("mode", "trim")
    bar_dur_sec = 60.0 * 4.0 / bpm

    if rule.get("kind") == "loop":
        # Snap-to-bar: pick 1 or 2 bars whichever is closer to the user's
        # trimmed length. Cap at 2 — Group A loops are intended to be
        # short, performable building blocks (longer loops on B/C/D get
        # different rules).
        trim_sec = max(0.0, end_sec - start_sec)
        ratio = trim_sec / bar_dur_sec if bar_dur_sec > 0 else 1.0
        snap_bars = max(1, min(2, int(round(ratio))))
        target_sec = snap_bars * bar_dur_sec
        start_frame = max(0, min(total, int(round(start_sec * sr))))
        target_frames = int(round(target_sec * sr))
        end_frame = min(total, start_frame + target_frames)
        data, _ = sf.read(str(src_wav), start=start_frame, stop=end_frame, always_2d=True)
        # If we ran out of source, pad the tail with silence so the
        # output is exactly N bars long.
        if data.shape[0] < target_frames:
            pad = np.zeros((target_frames - data.shape[0], data.shape[1]),
                           dtype=data.dtype)
            data = np.concatenate([data, pad], axis=0)
        out = data
    elif mode == "rotate":
        # Same total length: take [start..end] then prepend [0..start]
        data, _ = sf.read(str(src_wav), always_2d=True)
        start_frame = max(0, min(total, int(round(start_sec * sr))))
        if start_frame == 0:
            out = data
        else:
            out = np.concatenate([data[start_frame:], data[:start_frame]], axis=0)
    else:
        # Trim: just the chosen window
        start_frame = max(0, min(total, int(round(start_sec * sr))))
        end_frame = max(start_frame, min(total, int(round(end_sec * sr))))
        data, _ = sf.read(str(src_wav), start=start_frame, stop=end_frame, always_2d=True)
        out = data

    dst_wav.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(dst_wav), out, sr, subtype="PCM_24")
    return total, out.shape[0]


def build_plan(manifest: dict, manifest_path: Path) -> list[dict]:
    """Walk session_tracks; build the upload plan."""
    bake_root = manifest_path.parent / "ep133_hybrid"
    session = manifest.get("session_tracks") or {}
    bpm = float(manifest.get("bpm") or 120.0)

    plan = []
    for letter in ["A", "B", "C", "D"]:
        cfg = LAYOUT[letter]
        entries = session.get(letter, [])
        # Sort by slot_idx so pad numbering is deterministic
        entries = sorted(entries, key=lambda e: e.get("slot", 0))
        for k_idx, e in enumerate(entries):
            if k_idx >= 12:
                print(f"  WARN: more than 12 clips on Track {letter}, dropping rest")
                break
            rule = rule_for_slot(letter, k_idx)
            src = Path(e["file"])
            if not src.exists():
                print(f"  SKIP {letter}{k_idx+1}: source missing {src}")
                continue
            slot = cfg["slot_base"] + k_idx
            dst = bake_root / letter / f"pad_{k_idx+1:02d}_{rule['kind']}.wav"
            plan.append({
                "letter": letter,
                "group": cfg["group"],
                "pad_num": k_idx + 1,
                "slot": slot,
                "src": src,
                "dst": dst,
                "entry": e,
                "rule": rule,
                "bpm": bpm,
            })
    return plan


def print_plan(plan: list[dict]) -> None:
    print(f"\n{'pad':>5} {'slot':>5} {'kind':>5} {'mode':>7} {'baked':>7} "
          f"{'tmode':>5} {'bars':>5} {'mute':>5}  src")
    print("-" * 95)
    for p in plan:
        r = p["rule"]
        e = p["entry"]
        bpm = p["bpm"]
        bar_dur = 60.0 * 4.0 / bpm
        # Predict baked duration to match what bake_clip will produce.
        if r.get("kind") == "loop":
            trim_sec = max(0.0, e["end_offset_sec"] - e["start_offset_sec"])
            snap_bars = max(1, min(2, int(round(trim_sec / bar_dur))))
            est_dur = snap_bars * bar_dur
        elif e["mode"] == "rotate":
            est_dur = e.get("clip_length_sec", 0.0)
        else:
            est_dur = max(0.0, e["end_offset_sec"] - e["start_offset_sec"])
        eff_tmode, eff_bars = per_clip_time_mode(r, est_dur, bpm)
        bars_str = f"{eff_bars:.0f}" if eff_bars is not None else "-"
        print(f"{p['group']}{p['pad_num']:<4} {p['slot']:>5} {r['kind']:>5} "
              f"{e['mode']:>7} {est_dur:>6.3f}s {eff_tmode:>5} {bars_str:>5} "
              f"{('yes' if r['mute_group'] else 'no'):>5}  {p['src'].name}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("manifest", type=Path)
    ap.add_argument("--project", type=int, default=1)
    ap.add_argument("--delay-ms", type=int, default=50)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--skip-upload", action="store_true",
                    help="Bake WAVs but skip device upload (for inspection)")
    args = ap.parse_args()

    if not args.manifest.exists():
        raise SystemExit(f"manifest not found: {args.manifest}")
    mf = json.loads(args.manifest.read_text())

    if "session_tracks" not in mf:
        raise SystemExit("manifest has no session_tracks block — did you "
                         "click COMMIT in the device with clips on tracks A/B/C/D?")

    plan = build_plan(mf, args.manifest)
    print_plan(plan)

    if not plan:
        raise SystemExit("\nno clips on A/B/C/D — nothing to upload")
    print(f"\n{len(plan)} clips to bake + upload")

    # ── Bake stage ──────────────────────────────────────────────────────
    print("\n--- baking ---")
    for p in plan:
        in_n, out_n = bake_clip(p["src"], p["dst"], p["entry"], p["rule"], p["bpm"])
        out_dur = out_n / sf.info(str(p["dst"])).samplerate
        print(f"  {p['group']}{p['pad_num']:<4} {p['entry']['mode']:>7}  "
              f"{out_dur:.3f}s ({out_n}/{in_n} frames)  → {p['dst'].name}")

    if args.dry_run or args.skip_upload:
        msg = "--dry-run" if args.dry_run else "--skip-upload"
        print(f"\n{msg}: not uploading to device")
        return

    # ── Upload stage ────────────────────────────────────────────────────
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from stemforge.exporters.ep133 import EP133Client
    from stemforge.exporters.ep133.commands import TE_SYSEX_FILE
    from stemforge.exporters.ep133.payloads import (
        PadParams, SampleParams, build_slot_metadata_set,
    )

    print(f"\nconnecting to EP-133 (delay {args.delay_ms}ms)...")
    with EP133Client.open(inter_message_delay_s=args.delay_ms / 1000.0) as client:
        print("connected.\n")
        for i, p in enumerate(plan):
            tag = f"[{i+1:>2}/{len(plan)}] {p['group']}{p['pad_num']}"
            print(f"\n{tag}  →  slot {p['slot']}")

            # 1. Upload baked WAV
            t0 = time.monotonic()
            print(f"  upload {p['dst'].name}...", end=" ", flush=True)
            client.upload_sample(p["dst"], slot=p["slot"])
            print(f"done ({time.monotonic()-t0:.1f}s)")

            # 2. Slot-level meta: bpm + time.mode + bars (per-clip resolved)
            #    Use the baked WAV's actual duration to pick time.mode, so
            #    a 1-bar trim of a "loop" pad gets bars=1 (not the rule's
            #    nominal bars=2 which would force half-tempo stretching).
            t1 = time.monotonic()
            r = p["rule"]
            baked_info = sf.info(str(p["dst"]))
            baked_dur = baked_info.frames / float(baked_info.samplerate)
            eff_tmode, eff_bars = per_clip_time_mode(r, baked_dur, p["bpm"])
            slot_kwargs = {"bpm": p["bpm"], "time_mode": eff_tmode}
            if eff_bars is not None:
                slot_kwargs["bars"] = eff_bars
            # Key-mode pads need an explicit rootnote so the EP-133 places
            # the natural-pitch pad at the bottom-left of the grid (the "."
            # key) when KEYS is engaged.
            if r.get("rootnote") is not None:
                slot_kwargs["rootnote"] = int(r["rootnote"])
            print(f"  slot meta: time.mode={eff_tmode}"
                  + (f" bars={eff_bars:.0f}" if eff_bars else "")
                  + (f" rootnote={r['rootnote']}" if r.get("rootnote") is not None else "")
                  + "...",
                  end=" ", flush=True)
            slot_params = SampleParams(**slot_kwargs)
            payload = build_slot_metadata_set(p["slot"], slot_params)
            request_id = client._send(TE_SYSEX_FILE, payload)
            client._await_response(request_id, timeout=5.0)
            print(f"done ({time.monotonic()-t1:.2f}s)")

            # 3. Pad assign: playmode=oneshot, time.mode mirror, mutegroup.
            # Remap user-friendly pad_num (1..12, fills bottom-left first)
            # to the device's internal pad_num (1=top-left, 10=bottom-left).
            t2 = time.monotonic()
            device_pad = bottom_up_pad_num(p["pad_num"])
            print(f"  assign P{args.project} {p['group']}-pad{p['pad_num']} "
                  f"(device pad {device_pad}, playmode=oneshot, mute={r['mute_group']})...",
                  end=" ", flush=True)
            pad_params = PadParams(
                playmode="oneshot",
                sample_start=0,
                sample_end=None,
                time_mode=eff_tmode,
                mutegroup=bool(r["mute_group"]),
            )
            client.assign_pad(
                project=args.project,
                group=p["group"],
                pad_num=device_pad,
                slot=p["slot"],
                params=pad_params,
            )
            print(f"done ({time.monotonic()-t2:.1f}s)")

    print(f"\n✓ Loaded {len(plan)} pads to project {args.project}.")


if __name__ == "__main__":
    main()
