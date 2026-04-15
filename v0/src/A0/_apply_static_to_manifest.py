"""
In-place manifest patch: flip Demucs entries to load the static-shape ONNX
files we re-exported, and set ``coreml_ep_supported: true``.

Strategy: REPLACE existing Demucs entries (path/sha256/size/precision/
coreml_ep_supported) so the existing C++ binary picks up the new files
without any source change to the dispatcher / lookup keys (which are
``htdemucs``, ``htdemucs_6s``, ``htdemucs_ft_head{0..3}``).

The original dynamic-shape ONNX files are LEFT IN PLACE on disk so a
caller can roll back by running this script with ``--mode dynamic``.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

# Path to the *source* manifest in the worktree under feat/v0-coreml-opt.
WORKTREE = Path("/Users/zak/zacharysbrown/stemforge/.claude/worktrees/agent-aeafbfd6")
SRC_MANIFEST = WORKTREE / "v0/build/models/manifest.json"

# Path that the binary actually reads at runtime (resolved through symlink).
APP_SUPPORT_MODELS = Path.home() / "Library/Application Support/StemForge/models"

# Layout of static files in the worktree.
STATIC_FILES_WORKTREE = {
    "htdemucs":          ("htdemucs",     "htdemucs_static.onnx"),
    "htdemucs_6s":       ("htdemucs_6s",  "htdemucs_6s_static.onnx"),
    "htdemucs_ft_head0": ("htdemucs_ft",  "htdemucs_ft.head0_static.onnx"),
    "htdemucs_ft_head1": ("htdemucs_ft",  "htdemucs_ft.head1_static.onnx"),
    "htdemucs_ft_head2": ("htdemucs_ft",  "htdemucs_ft.head2_static.onnx"),
    "htdemucs_ft_head3": ("htdemucs_ft",  "htdemucs_ft.head3_static.onnx"),
}

# Original dynamic file basenames, for rollback or reference.
DYNAMIC_FILES = {
    "htdemucs":          "htdemucs.onnx",
    "htdemucs_6s":       "htdemucs_6s.onnx",
    "htdemucs_ft_head0": "htdemucs_ft.head0.onnx",
    "htdemucs_ft_head1": "htdemucs_ft.head1.onnx",
    "htdemucs_ft_head2": "htdemucs_ft.head2.onnx",
    "htdemucs_ft_head3": "htdemucs_ft.head3.onnx",
}


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def patch_manifest(mode: str = "static",
                   target_manifest: Path | None = None,
                   physical_root: Path | None = None) -> Path:
    """
    Update one manifest.json file in place.

    ``physical_root`` is where the .onnx files live on disk (used to compute
    sha256 + size). ``target_manifest`` is the .json file to write back.
    """
    target_manifest = target_manifest or SRC_MANIFEST
    physical_root = physical_root or (WORKTREE / "v0/build/models")

    doc = json.loads(target_manifest.read_text())
    models = doc.get("models", {})

    for key, (subdir, static_basename) in STATIC_FILES_WORKTREE.items():
        if key not in models:
            print(f"  skip {key}: not in manifest", file=sys.stderr)
            continue
        if mode == "static":
            basename = static_basename
        elif mode == "dynamic":
            basename = DYNAMIC_FILES[key]
        else:
            raise ValueError(f"bad mode: {mode}")

        physical_path = physical_root / subdir / basename
        if not physical_path.exists():
            print(f"  WARN: physical file missing: {physical_path}",
                  file=sys.stderr)
            continue

        size = physical_path.stat().st_size
        sha = _sha256(physical_path)
        rel = f"v0/build/models/{subdir}/{basename}"

        entry = models[key]
        entry["path"] = rel
        entry["sha256"] = sha
        entry["size"] = size
        entry["coreml_ep_supported"] = (mode == "static")
        entry["input_shape_locked"] = (mode == "static")
        entry.setdefault("notes", "")
        if mode == "static":
            entry["notes"] = (
                "STATIC-SHAPE export — all dims (batch=1, channels=2, "
                "samples=343980, frames=336) baked as constants. CoreML EP "
                "MLProgram supports 1446/1500 nodes (96.4 %). Per-segment "
                "latency on M-series ~0.55 s vs CPU ~2.0 s. Caller pipeline "
                "(STFT, CAC pack, iSTFT) unchanged. See "
                "v0/state/A0/coreml_report.md for measurements."
            )

        # Update output_shape / input_shape from the new file at write time
        # if the binary reads them. (Not strictly needed — the binary doesn't
        # use these shapes, but keep them consistent for future tooling.)
        try:
            import onnx
            m = onnx.load(str(physical_path), load_external_data=False)
            def _shape(t):
                dims = []
                for d in t.type.tensor_type.shape.dim:
                    if d.HasField("dim_value"):
                        dims.append(int(d.dim_value))
                    else:
                        dims.append(d.dim_param or "dynamic")
                return dims
            entry["input_shape"] = {t.name: _shape(t) for t in m.graph.input}
            entry["output_shape"] = {t.name: _shape(t) for t in m.graph.output}
        except Exception as e:
            print(f"  warn: could not refresh I/O shapes for {key}: {e!s}",
                  file=sys.stderr)

        print(f"  {key} → {rel} sha={sha[:12]} size={size/1e6:.1f}MB "
              f"coreml={entry['coreml_ep_supported']}")

    target_manifest.write_text(json.dumps(doc, indent=2) + "\n")
    print(f"\nwrote {target_manifest}")
    return target_manifest


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--mode", choices=["static", "dynamic"], default="static")
    p.add_argument("--target",
                   choices=["worktree", "app-support", "both"],
                   default="worktree")
    args = p.parse_args(argv)

    targets = []
    if args.target in ("worktree", "both"):
        targets.append(("worktree", SRC_MANIFEST,
                        WORKTREE / "v0/build/models"))
    if args.target in ("app-support", "both"):
        # The app-support manifest is normally a symlink — we want to write
        # a real file at the symlink location's resolution.
        app_manifest = APP_SUPPORT_MODELS / "manifest.json"
        # If it's a symlink to another worktree's manifest, that's fine —
        # we'll edit the file the symlink points to (the app-support copy
        # IS the C++ binary's source of truth).
        # But to prevent cross-worktree pollution, prefer to drop a real
        # file in the worktree's models dir and point the symlink at it.
        targets.append(("app-support", app_manifest, APP_SUPPORT_MODELS))

    for label, mfp, root in targets:
        print(f"\n=== {label}: {mfp}")
        if not mfp.exists() and not mfp.is_symlink():
            print(f"  skip: not present", file=sys.stderr)
            continue
        # If it's a symlink, follow + edit (matches caller intent: update
        # whatever the binary actually reads).
        if mfp.is_symlink():
            real = mfp.resolve()
            print(f"  symlink → {real} (editing target)")
            patch_manifest(mode=args.mode, target_manifest=real,
                           physical_root=real.parent)
        else:
            patch_manifest(mode=args.mode, target_manifest=mfp,
                           physical_root=root)
    return 0


if __name__ == "__main__":
    sys.exit(main())
