"""sf_merge_setlist — fold taste's per-set/per-deck manifests into deck manifests.

taste emits one rows=1 manifest per (set, deck): `set1_A.json`, `set1_B.json`,
… `set5_D.json`. A live performance wants the whole setlist preloaded as SCENES:
each set is a scene (row), each deck column stacks its songs down the scenes.

This merges N sets into FOUR deck manifests (`deck_A.json` … `deck_D.json`), each
with `rows = N`. Every clip carries its own `name` + `color_hue` (the source set's
song identity), so loadDeck colors and labels each scene per-song rather than
per-deck. See docs/design-docs/setforge-loader.md §4.

Usage:

    uv run python tools/sf_merge_setlist.py <manifests_dir> [--out DIR] \
        [--sets set1 set2 ...]

`--sets` defaults to every `set*` prefix found, in natural order (set1..set9,
set10..). Output defaults to `<manifests_dir>/merged/`.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

DECKS = ["A", "B", "C", "D"]
STEMS = ["drums", "bass", "vocals", "other"]


def _natural_key(s: str) -> list:
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", s)]


def fold_octave(bpm: float, target: float) -> float:
    """Fold a tempo into the octave nearest `target` (tames detector 2x/½x errors).

    beat-this often reports octave errors (e.g. 271.92 for a ~136 song, 69.67 for
    ~139). Decks must agree on tempo octave or they half/double-time against each
    other. Folds by halving/doubling until within a √2 band of target. This is an
    interim heuristic — proper tempo/downbeat QA belongs in taste.
    """
    if not bpm or bpm <= 0:
        return bpm
    hi, lo = target * (2**0.5), target / (2**0.5)
    out = float(bpm)
    for _ in range(8):
        if out > hi:
            out /= 2.0
        elif out < lo:
            out *= 2.0
        else:
            break
    return round(out, 3)


def read_song_analysis(audio_path: str) -> dict:
    """Pull bpm + first_downbeat_sec from the song's stems.json (next to the wav).

    Returns {} when absent so the loader falls back to Live's auto-warp.
    """
    sj = Path(audio_path).parent / "stems.json"
    if not sj.is_file():
        return {}
    try:
        d = json.loads(sj.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    tempo = d.get("tempo") or {}
    out = {}
    if d.get("bpm"):
        out["bpm"] = float(d["bpm"])
    if tempo.get("first_downbeat_sec") is not None:
        out["downbeat_sec"] = float(tempo["first_downbeat_sec"])
    if tempo.get("confidence"):
        out["tempo_confidence"] = tempo["confidence"]
    return out


def discover_sets(mdir: Path) -> list[str]:
    """Every `<prefix>_A.json` → prefix, natural-sorted."""
    prefixes = sorted(
        {p.name[: -len("_A.json")] for p in mdir.glob("*_A.json")},
        key=_natural_key,
    )
    return prefixes


def merge(mdir: Path, sets: list[str], out: Path, fold_target: float) -> int:
    out.mkdir(parents=True, exist_ok=True)
    rows = len(sets)
    if rows == 0:
        print(f"error: no sets found in {mdir}", file=sys.stderr)
        return 2

    for deck in DECKS:
        # Load each set's manifest for this deck up front so a missing one fails
        # before we write anything.
        srcs = []
        for setname in sets:
            p = mdir / f"{setname}_{deck}.json"
            if not p.is_file():
                print(f"error: missing {p}", file=sys.stderr)
                return 2
            srcs.append(json.loads(p.read_text()))

        stems_out: dict[str, dict] = {}
        for stem in STEMS:
            clips = []
            for slot, src in enumerate(srcs):
                src_clip = src["stems"][stem]["clips"][0]  # taste manifests are rows=1
                song = src.get("song", {})
                ap = src_clip["audio_path"]
                clip = {
                    "slot": slot,
                    "audio_path": ap,
                    "name": song.get("name", f"set{slot + 1}"),
                    "color_hue": song.get("color_hue", 0.0),
                }
                # Beat-match data from taste's per-song analysis (shared by all 4
                # stems → they lock to each other). Octave-folded so decks agree.
                analysis = read_song_analysis(ap)
                if "bpm" in analysis:
                    clip["bpm"] = (
                        fold_octave(analysis["bpm"], fold_target)
                        if fold_target
                        else round(analysis["bpm"], 3)
                    )
                    clip["bpm_raw"] = round(analysis["bpm"], 3)
                if "downbeat_sec" in analysis:
                    clip["downbeat_sec"] = round(analysis["downbeat_sec"], 4)
                if "tempo_confidence" in analysis:
                    clip["tempo_confidence"] = analysis["tempo_confidence"]
                clips.append(clip)
            stems_out[stem] = {"clips": clips}

        # Deck-level song.* is only a fallback (per-clip identity wins); set it to
        # the first set's deck song so single-tool inspection still reads sanely.
        first_song = srcs[0].get("song", {})
        deck_mf = {
            "version": 1,
            "deck": deck,
            "rows": rows,
            "song": {
                "name": f"Deck {deck} setlist",
                "color_hue": first_song.get("color_hue", 0.0),
            },
            "bpm": srcs[0].get("bpm", 120.0),
            "stems": stems_out,
        }
        dst = out / f"deck_{deck}.json"
        dst.write_text(json.dumps(deck_mf, indent=2) + "\n")
        print(f"  wrote {dst}  (rows={rows})")
        for c in stems_out["drums"]["clips"]:
            bpm = c.get("bpm", "?")
            raw = c.get("bpm_raw")
            folded = f" (raw {raw})" if raw is not None and raw != bpm else ""
            db = c.get("downbeat_sec", "?")
            conf = c.get("tempo_confidence", "?")
            print(
                f"    scene {c['slot']}: bpm={bpm}{folded} downbeat={db}s conf={conf}  {c['name']}"
            )

    print(f"→ {len(DECKS)} deck manifests in {out}  ({rows} scenes each)")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="sf-merge-setlist", description=__doc__)
    ap.add_argument("manifests_dir", help="Dir of taste per-set/per-deck manifests.")
    ap.add_argument("--out", default=None, help="Output dir (default: <manifests_dir>/merged).")
    ap.add_argument(
        "--sets",
        nargs="+",
        default=None,
        help="Ordered set prefixes (default: all set* found, natural order).",
    )
    ap.add_argument(
        "--fold-target",
        type=float,
        default=128.0,
        help="Octave-fold tempos toward this BPM (0 disables). Default 128.",
    )
    args = ap.parse_args(argv)

    mdir = Path(args.manifests_dir).expanduser()
    if not mdir.is_dir():
        print(f"error: {mdir} not a directory", file=sys.stderr)
        return 2
    out = Path(args.out).expanduser() if args.out else mdir / "merged"
    sets = args.sets or discover_sets(mdir)
    print(f"→ merging {len(sets)} sets {sets} from {mdir}")
    return merge(mdir, sets, out, args.fold_target)


if __name__ == "__main__":
    raise SystemExit(main())
