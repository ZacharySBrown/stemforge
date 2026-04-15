"""
fp16 export + null-test residual harness.

PIVOT §E requirements for A0.7:

  * Attempt fp16 export via `onnxconverter_common.float16.convert_float_to_float16`.
  * Null-test: invert fp16 output against fp32 output, RMS of residual must
    be < -60 dB. If pass → ship fp16 and record `precision: "fp16"` in
    manifest. If fail → ship fp32 and write `fp16_report.md` explaining
    which stems/labels degraded.

For classifiers (CLAP, AST) the null-test morphs into "top-1 accuracy within
1% on ≥200-sample eval set". Callers pass the appropriate metric.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

import numpy as np


NULL_TEST_FLOOR_DBFS = -60.0


@dataclass
class NullTestResult:
    model_name: str
    fixture: str
    rms_dbfs: float
    peak_abs: float
    passed: bool
    threshold_dbfs: float = NULL_TEST_FLOOR_DBFS

    def as_dict(self) -> dict[str, Any]:
        return {
            "model_name": self.model_name,
            "fixture": self.fixture,
            "rms_dbfs": round(self.rms_dbfs, 3),
            "peak_abs": round(self.peak_abs, 6),
            "passed": self.passed,
            "threshold_dbfs": self.threshold_dbfs,
        }


def rms_dbfs(signal: np.ndarray) -> float:
    """RMS in dBFS, treating 1.0 as full scale."""
    signal = np.asarray(signal, dtype=np.float64)
    if signal.size == 0:
        return -math.inf
    rms = float(np.sqrt(np.mean(signal ** 2)))
    if rms <= 0.0:
        return -math.inf
    return 20.0 * math.log10(rms)


def null_test(fp32_output: np.ndarray, fp16_output: np.ndarray,
              *, model_name: str, fixture: str,
              threshold_dbfs: float = NULL_TEST_FLOOR_DBFS) -> NullTestResult:
    """Compute residual and compare to threshold."""
    a = np.asarray(fp32_output, dtype=np.float64)
    b = np.asarray(fp16_output, dtype=np.float64)
    if a.shape != b.shape:
        raise ValueError(f"shape mismatch: {a.shape} vs {b.shape}")
    residual = a - b
    dbfs = rms_dbfs(residual)
    return NullTestResult(
        model_name=model_name,
        fixture=fixture,
        rms_dbfs=dbfs,
        peak_abs=float(np.max(np.abs(residual))) if residual.size else 0.0,
        passed=dbfs <= threshold_dbfs,
        threshold_dbfs=threshold_dbfs,
    )


def convert_to_fp16(src_onnx: Path, dst_onnx: Path, *,
                    keep_io_types: bool = True) -> None:
    """Wrap `onnxconverter_common.float16.convert_float_to_float16`."""
    import onnx
    from onnxconverter_common import float16

    model = onnx.load(str(src_onnx))
    model_fp16 = float16.convert_float_to_float16(
        model, keep_io_types=keep_io_types,
    )
    dst_onnx.parent.mkdir(parents=True, exist_ok=True)
    onnx.save(model_fp16, str(dst_onnx))


@dataclass
class Fp16Attempt:
    model_name: str
    fp32_path: str
    fp16_path: str | None
    residuals: list[NullTestResult] = field(default_factory=list)
    all_passed: bool = False
    notes: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "model_name": self.model_name,
            "fp32_path": self.fp32_path,
            "fp16_path": self.fp16_path,
            "residuals": [r.as_dict() for r in self.residuals],
            "all_passed": self.all_passed,
            "notes": self.notes,
        }


def attempt_fp16(fp32_path: Path, fp16_path: Path, model_name: str,
                 run_fn: Callable[[Path], dict[str, np.ndarray]],
                 fixture_names: Iterable[str],
                 threshold_dbfs: float = NULL_TEST_FLOOR_DBFS) -> Fp16Attempt:
    """
    High-level helper: convert fp32→fp16, run `run_fn` on both, null-test.

    `run_fn(path) -> {fixture_name: output_array}` is supplied by the caller
    (it knows how to feed Demucs vs CLAP vs AST). Outputs must be directly
    comparable (same dtype after cast, same shape).
    """
    try:
        convert_to_fp16(fp32_path, fp16_path)
    except Exception as e:
        return Fp16Attempt(model_name=model_name, fp32_path=str(fp32_path),
                           fp16_path=None, notes=f"conversion failed: {e!s}")

    try:
        fp32_out = run_fn(fp32_path)
        fp16_out = run_fn(fp16_path)
    except Exception as e:
        return Fp16Attempt(model_name=model_name, fp32_path=str(fp32_path),
                           fp16_path=str(fp16_path),
                           notes=f"inference failed: {e!s}")

    residuals = []
    all_ok = True
    for name in fixture_names:
        if name not in fp32_out or name not in fp16_out:
            continue
        r = null_test(fp32_out[name], fp16_out[name],
                      model_name=model_name, fixture=name,
                      threshold_dbfs=threshold_dbfs)
        residuals.append(r)
        all_ok &= r.passed

    return Fp16Attempt(
        model_name=model_name,
        fp32_path=str(fp32_path),
        fp16_path=str(fp16_path),
        residuals=residuals,
        all_passed=all_ok and bool(residuals),
    )


def write_fp16_report(path: Path, attempts: list[Fp16Attempt]) -> None:
    """Write `v0/state/A0/fp16_report.md` when any attempt fails."""
    lines = ["# fp16 Export Investigation — Track A0.7",
             "",
             "Null-test threshold: RMS residual of (fp32 − fp16) ≤ "
             f"{NULL_TEST_FLOOR_DBFS} dBFS.",
             "",
             "| Model | Fixture | Residual RMS (dBFS) | Peak |abs| | Pass |",
             "|---|---|---:|---:|:---:|"]
    for a in attempts:
        if not a.residuals:
            lines.append(f"| {a.model_name} | (no residuals) | — | — | "
                         f"{'skip' if 'skip' in a.notes else 'fail'} |")
            continue
        for r in a.residuals:
            lines.append(
                f"| {a.model_name} | {r.fixture} | {r.rms_dbfs:+.2f} | "
                f"{r.peak_abs:.3e} | {'PASS' if r.passed else 'FAIL'} |"
            )
    lines.append("")
    lines.append("## Notes")
    for a in attempts:
        status = "shipped fp16" if a.all_passed else "shipped fp32 fallback"
        lines.append(f"- **{a.model_name}** — {status}. {a.notes}")
    lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines))
