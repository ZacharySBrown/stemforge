"""
Standalone parity-validation CLI.

Reads `v0/build/models/manifest.json`, loads each ONNX file that is already
exported, runs the parity harness against the torch reference, writes
`v0/state/A0/validation_report.json`. Exits non-zero if any required
threshold is breached.

Usage:
    python -m v0.src.A0.validate                 # validate all models in manifest
    python -m v0.src.A0.validate --model ast     # validate one
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

from . import (ast_export, clap_export, config, demucs_export, fixtures,
               manifest, progress)


def _validate_demucs(manifest_entries: dict) -> list[dict]:
    """
    Validate each Demucs variant present in the manifest against its
    torch reference.  Returns a list of per-variant dicts ready to be
    nested under ``validation_report.models``.
    """
    from demucs.pretrained import get_model

    results = []
    variants = ("htdemucs_ft", "htdemucs_6s", "htdemucs")
    for variant in variants:
        # Collect head entries (multi-head bags have *_headN keys;
        # single-model bags have the variant as the key directly).
        head_entries = [entry for key, entry in manifest_entries.items()
                        if key == variant or key.startswith(f"{variant}_head")]
        if not head_entries:
            continue

        onnx_paths: list[Path] = []
        for entry in sorted(
                head_entries,
                key=lambda e: e.get("bag_head_index", 0)):
            p = Path(entry["path"])
            if not p.is_absolute():
                p = config.REPO_ROOT / p
            onnx_paths.append(p)

        bag = get_model(variant)
        for h in bag.models:
            h.eval()
            demucs_export._wrap_head_with_vendored_class(h)
        seg = demucs_export.segment_samples_for(bag.models[0])

        per_fx = []
        primary_pass = True
        for fx in fixtures.all_fixtures():
            p = demucs_export.validate_head(
                bag, onnx_paths, fx.samples, fx.name, variant, seg)
            per_fx.append(p.as_dict())
            if fx.name == "full_mix_30s":
                primary_pass &= p.passed
            progress.emit("validate.demucs", 50,
                          f"{variant} {fx.name}: "
                          f"rms={p.residual_rms_dbfs:+.1f}dBFS "
                          f"pass={p.passed}")
        results.append({
            "model": variant,
            "passed": primary_pass,
            "fixtures": per_fx,
            "heads": [str(p.relative_to(config.REPO_ROOT))
                      for p in onnx_paths],
        })
    return results


def _validate_ast(onnx_path: Path) -> dict:
    import librosa
    results = {"model": "ast_audioset", "fixtures": [], "passed": True}
    for fx in fixtures.all_fixtures():
        mono = fx.samples.mean(axis=0).astype(np.float32)
        y16 = librosa.resample(mono, orig_sr=fx.sr, target_sr=16_000)
        p = ast_export.validate(onnx_path, y16, fx.name)
        results["fixtures"].append(p.as_dict())
        results["passed"] &= p.passed
        progress.emit("validate.ast", 50,
                      f"{fx.name}: labels_match={p.labels_match} "
                      f"max_diff={p.max_logit_diff:.4e} pass={p.passed}")
    return results


def _validate_clap(onnx_path: Path) -> dict:
    import librosa
    results = {"model": "clap_htsat_unfused", "fixtures": [], "passed": True}
    for fx in fixtures.all_fixtures():
        mono = fx.samples.mean(axis=0).astype(np.float32)
        y48 = librosa.resample(mono, orig_sr=fx.sr, target_sr=48_000)
        p = clap_export.validate(onnx_path, y48, fx.name)
        results["fixtures"].append(p.as_dict())
        results["passed"] &= p.passed
        progress.emit("validate.clap", 50,
                      f"{fx.name}: cos={p.cosine:.6f} pass={p.passed}")
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="A0 parity validation")
    parser.add_argument("--model", choices=("ast", "clap", "demucs", "all"),
                        default="all")
    args = parser.parse_args(argv or sys.argv[1:])

    man = manifest.load()
    models = man.get("models", {})

    report = {"models": [], "passed": True}

    if args.model in ("ast", "all") and "ast_audioset" in models:
        p = Path(models["ast_audioset"]["path"])
        if not p.is_absolute():
            p = config.REPO_ROOT / p
        report["models"].append(_validate_ast(p))

    if args.model in ("clap", "all") and "clap_htsat_unfused" in models:
        p = Path(models["clap_htsat_unfused"]["path"])
        if not p.is_absolute():
            p = config.REPO_ROOT / p
        report["models"].append(_validate_clap(p))

    if args.model in ("demucs", "all"):
        try:
            demucs_results = _validate_demucs(models)
            report["models"].extend(demucs_results)
        except Exception as e:  # pragma: no cover
            progress.emit("validate.demucs", 0, f"error: {e!s}")

    report["passed"] = all(m["passed"] for m in report["models"])

    config.A0_STATE_DIR.mkdir(parents=True, exist_ok=True)
    with open(config.STATE_VALIDATION_REPORT, "w") as fh:
        json.dump(report, fh, indent=2)
        fh.write("\n")

    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
