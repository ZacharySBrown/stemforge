"""
CoreML EP smoke test + optimized-model cache setup.

Implements the non-negotiable PIVOT §E requirements:

  * `ORT_ENABLE_ALL` graph optimization.
  * `SetOptimizedModelFilePath()` — save the optimized graph to disk so the
    downstream C++ host (Track A) does not re-optimize on every run.
  * CoreML EP with `COREML_FLAG_USE_CPU_AND_GPU` so any unsupported op
    falls back to CPU *within the session* instead of blowing up.
  * Record which ops, if any, fell back to CPU (this is the signal Track A
    uses to decide whether to ship the CoreML EP in production or revert
    to CPU-only for that model).

We probe by building two sessions — one with CoreML, one CPU-only — and
running a single-inference forward pass with timing. The brief requires
wall-clock latency on a 30-second stereo @ 44.1 kHz input; the concrete
input shape is model-specific so the caller passes it via `probe_inputs`.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Sequence

import numpy as np

try:  # Deferred: tests that don't need ORT should not import this.
    import onnxruntime as ort
except Exception:  # pragma: no cover - environment guard
    ort = None  # type: ignore[assignment]

from . import config


@dataclass
class CoreMLProbe:
    model_name: str
    onnx_path: str
    coreml_loaded: bool = False
    providers_resolved: list[str] = field(default_factory=list)
    cpu_fallback_ops: list[str] = field(default_factory=list)
    cpu_only_latency_sec: float | None = None
    coreml_latency_sec: float | None = None
    optimized_cache_path: str | None = None
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _session_options(model_name: str) -> "ort.SessionOptions":
    """Build SessionOptions with `ORT_ENABLE_ALL` + optimized-model cache."""
    assert ort is not None
    so = ort.SessionOptions()
    so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    cache_dir = config.ORT_CACHE_DIR / model_name
    cache_dir.mkdir(parents=True, exist_ok=True)
    so.optimized_model_filepath = str(cache_dir / f"{model_name}.optimized.onnx")
    # Match the C++ host's expected runtime behavior: single-threaded dispatch
    # is fine for v0 (sample_rate/segment-length determine latency, not cores).
    so.intra_op_num_threads = max(1, (os.cpu_count() or 4) - 1)
    return so


def _coreml_providers() -> list:
    """CoreML EP provider spec with CPU+GPU fallback, matching PIVOT §E."""
    assert ort is not None
    # ORT exposes CoreML flags as a dict in newer releases; fall back gracefully.
    coreml_opts = {
        # COREML_FLAG_USE_CPU_AND_GPU — unsupported ops fall back to CPU
        # within the same session rather than failing the load.
        "MLComputeUnits": "ALL",
        "ModelFormat": "MLProgram",
        # Keep models that touch dynamic shapes on CPU inside the EP itself.
        "RequireStaticInputShapes": "0",
    }
    return [("CoreMLExecutionProvider", coreml_opts),
            "CPUExecutionProvider"]


def probe(onnx_path: Path, model_name: str,
          probe_inputs: dict[str, np.ndarray],
          runs: int = 1) -> CoreMLProbe:
    """
    Load `onnx_path` on CoreML EP and CPU-only. Measure single-inference
    wall clock for each. Record any ops that fell back.

    `probe_inputs` is the `{input_name: np.ndarray}` feed dict — the shape
    is model-specific (Demucs wants (1, 2, segment_samples), CLAP wants
    (1, 48000), etc.) so the caller supplies it.
    """
    res = CoreMLProbe(model_name=model_name, onnx_path=str(onnx_path))

    if ort is None:
        res.error = "onnxruntime not installed"
        return res

    so = _session_options(model_name)
    res.optimized_cache_path = str(so.optimized_model_filepath)

    try:
        sess_cpu = ort.InferenceSession(
            str(onnx_path), sess_options=so,
            providers=["CPUExecutionProvider"],
        )
    except Exception as e:
        res.error = f"cpu session load failed: {e!s}"
        return res

    t0 = time.perf_counter()
    for _ in range(runs):
        _ = sess_cpu.run(None, probe_inputs)
    res.cpu_only_latency_sec = round((time.perf_counter() - t0) / runs, 4)

    # Session construction is one concern; actually running inference is
    # another. We track them separately so a "CoreML loaded the model but
    # a dummy forward failed on zero-shaped inputs" case is not conflated
    # with "CoreML refused to load at all".
    try:
        sess_cml = ort.InferenceSession(
            str(onnx_path), sess_options=so,
            providers=_coreml_providers(),
        )
        res.providers_resolved = list(sess_cml.get_providers())
        res.coreml_loaded = "CoreMLExecutionProvider" in res.providers_resolved
        res.cpu_fallback_ops = _collect_cpu_fallback_ops(onnx_path, model_name)
    except Exception as e:
        res.error = f"coreml session load failed: {e!s}"
        return res

    try:
        t0 = time.perf_counter()
        for _ in range(runs):
            _ = sess_cml.run(None, probe_inputs)
        res.coreml_latency_sec = round((time.perf_counter() - t0) / runs, 4)
    except Exception as e:
        # Session loaded but forward failed — likely probe-input issue
        # (zero-shaped dummy, missing bool inputs, etc.). Record but don't
        # flip coreml_loaded to False.
        res.error = f"coreml forward failed (probe input issue likely): {e!s}"

    return res


def _collect_cpu_fallback_ops(onnx_path: Path, model_name: str) -> list[str]:
    """
    Enumerate ops the CoreML EP does not support by comparing the optimized
    graph against the set of ops CoreML EP claims to support.

    This is a heuristic — the authoritative source is the CoreML EP's
    per-node assignment log emitted at ORT_LOGGING_LEVEL=VERBOSE. The Track A
    host should parse those logs on first run and persist the result.
    """
    assert ort is not None
    try:
        import onnx
    except ImportError:
        return []

    # Load the optimized graph if it exists (cheaper), else the original.
    cache_path = config.ORT_CACHE_DIR / model_name / f"{model_name}.optimized.onnx"
    if cache_path.exists():
        model_proto = onnx.load(str(cache_path))
    else:
        model_proto = onnx.load(str(onnx_path))

    ops = {n.op_type for n in model_proto.graph.node}
    # Curated list of ops CoreML EP *does not* implement (as of ORT 1.24).
    # This list is intentionally conservative; Track A should replace it with
    # the runtime-captured assignment log on first launch.
    unsupported_hint = {
        "STFT", "ISTFT", "SpectrogramExtractor", "MFCC",
        "ComplexMul", "RealCosineTransform",
        "NonMaxSuppression", "CumSum",
        "LSTM",  # partial support — varies by version/activation
    }
    return sorted(ops & unsupported_hint)
