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
        progress.emit("validate.demucs", 10,
                      "skipped: in-graph export blocked (see blocker.md)")

    report["passed"] = all(m["passed"] for m in report["models"])

    config.A0_STATE_DIR.mkdir(parents=True, exist_ok=True)
    with open(config.STATE_VALIDATION_REPORT, "w") as fh:
        json.dump(report, fh, indent=2)
        fh.write("\n")

    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
