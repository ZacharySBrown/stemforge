"""
int8 dynamic quantization for classifier models (AST, CLAP).

PIVOT §E A0.8 — stretch goal. Only ship if top-1 accuracy on the eval set is
within 1% of fp32 reference. Skip (not fail) if non-trivial; flag as
`stretch deferral`.

Demucs is explicitly **out of scope** — the brief states int8 quant is
almost certainly too lossy for a waveform regression model.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Sequence


@dataclass
class QuantAttempt:
    model_name: str
    src_path: str
    int8_path: str | None
    fp32_top1: float | None = None
    int8_top1: float | None = None
    accuracy_delta: float | None = None
    passed: bool = False
    reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "model_name": self.model_name,
            "src_path": self.src_path,
            "int8_path": self.int8_path,
            "fp32_top1": self.fp32_top1,
            "int8_top1": self.int8_top1,
            "accuracy_delta": self.accuracy_delta,
            "passed": self.passed,
            "reason": self.reason,
        }


def quantize_dynamic(src: Path, dst: Path) -> None:
    """Wrap `onnxruntime.quantization.quantize_dynamic` with int8 weights."""
    # Deferred import so the test suite can import this module without ORT.
    from onnxruntime.quantization import quantize_dynamic as _qd
    from onnxruntime.quantization.quant_utils import QuantType

    dst.parent.mkdir(parents=True, exist_ok=True)
    _qd(
        model_input=str(src),
        model_output=str(dst),
        weight_type=QuantType.QInt8,
        reduce_range=False,
        per_channel=False,
    )


def attempt_int8(src: Path, dst: Path, model_name: str,
                 eval_fn: Callable[[Path], float],
                 min_samples: int = 200,
                 max_accuracy_drop: float = 0.01) -> QuantAttempt:
    """
    Attempt int8 dynamic quantization + eval.

    `eval_fn(path) -> top1_accuracy_in_[0,1]` is provided by the caller; it
    must internally run ≥`min_samples` eval samples. If the fp32 accuracy is
    already unknown the caller passes a wrapped function that computes both.
    """
    try:
        quantize_dynamic(src, dst)
    except Exception as e:
        return QuantAttempt(model_name=model_name, src_path=str(src),
                            int8_path=None,
                            reason=f"quantize_dynamic failed: {e!s}")

    try:
        fp32_top1 = eval_fn(src)
        int8_top1 = eval_fn(dst)
    except Exception as e:
        return QuantAttempt(model_name=model_name, src_path=str(src),
                            int8_path=str(dst),
                            reason=f"eval failed: {e!s}")

    delta = float(fp32_top1 - int8_top1)
    passed = delta <= max_accuracy_drop
    return QuantAttempt(
        model_name=model_name,
        src_path=str(src),
        int8_path=str(dst),
        fp32_top1=round(float(fp32_top1), 4),
        int8_top1=round(float(int8_top1), 4),
        accuracy_delta=round(delta, 4),
        passed=passed,
        reason=("within 1% of fp32" if passed
                else f"top-1 dropped {delta*100:.2f}% > 1% threshold; "
                     "not shipping int8"),
    )
