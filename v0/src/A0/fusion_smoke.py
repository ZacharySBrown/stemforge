"""
fusion_smoke.py — Phase 1 gate for htdemucs_ft ONNX fusion.

BACKGROUND
----------
htdemucs_ft ships as a bag of 4 specialist HTDemucs heads. Each head is a
separate static ONNX file. Our C++ runtime currently creates 4 Ort::Sessions
— CoreML's per-session MLProgram compile costs ~10 s each, yielding a 40 s
session-setup penalty that turns the 4x inference speedup into a wall-clock
regression on one-shot CLI runs (v0/state/A/coreml_report.md §Key finding).

The fix is to fuse the 4 heads into a single ONNX graph sharing the input
tensors. One graph → one ORT session → one MLProgram compile.

This script is the cheapest possible predictive check: glue just 2 of the
4 heads with ``onnx.compose.merge_models`` and measure CoreML EP partition
coverage. If coverage on the 2-head prototype drops below 90%, the full
4-head fusion is unlikely to help and we abort early.

ABORT CRITERIA
--------------
  coverage_pct < 90  →  write v0/state/A/fusion_aborted.md, stop.

Invocation::

    uv run --active python -m v0.src.A0.fusion_smoke
    # or (explicit ORT verbose logging):
    ORT_LOG_LEVEL=VERBOSE uv run --active python -m v0.src.A0.fusion_smoke
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import onnx
import onnxruntime as ort

from . import config

FT_MODELS_DIR = config.BUILD_MODELS_DIR / "htdemucs_ft"


@dataclass
class SmokeResult:
    fused_path: str
    total_nodes: int = 0
    coreml_nodes_supported: int | None = None
    coreml_partitions: int | None = None
    coverage_pct: float | None = None
    coreml_loaded: bool = False
    error: str | None = None
    verbose_log_snippets: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _prefix_model(model: onnx.ModelProto, prefix: str,
                  rename_io: bool = True) -> onnx.ModelProto:
    """Add a prefix to every name in the model (optionally including I/O)."""
    return onnx.compose.add_prefix(
        model,
        prefix=prefix,
        rename_nodes=True,
        rename_edges=True,
        rename_initializers=True,
        rename_value_infos=True,
        rename_functions=True,
        rename_inputs=rename_io,
        rename_outputs=rename_io,
    )


def fuse_heads(head_paths: list[Path], dst_onnx: Path) -> onnx.ModelProto:
    """
    Merge N heads into one graph with shared inputs `mix` + `z_cac`.

    Strategy
    --------
    1. Load each head.
    2. Prefix all names INCLUDING inputs/outputs with ``h<i>__``. Each head
       ends up with distinct inputs (``h0__mix``, ``h0__z_cac``, …) and
       outputs (``h0__time_out``, ``h0__zout_cac``, …).
    3. Chain-merge with ``onnx.compose.merge_models`` using an empty
       ``io_map`` — no tensor is shared yet.
    4. Prepend a tiny wrapper: declare shared graph-level inputs
       ``mix`` / ``z_cac`` and emit one Identity per head feeding
       ``h<i>__mix`` / ``h<i>__z_cac``. CoreML EP absorbs Identity for free.
    5. Keep each head's outputs exposed as graph outputs so the smoke test
       can simply inspect partition coverage. (The Phase-2 full fusion
       collapses these to a single ``stems_out`` tensor via Gather+Concat.)
    """
    prefixed: list[onnx.ModelProto] = []
    for i, p in enumerate(head_paths):
        m = onnx.load(str(p))
        prefixed.append(_prefix_model(m, f"h{i}__", rename_io=True))

    # Chain merge (no io linkage, fully parallel after we wire inputs).
    fused = prefixed[0]
    for nxt in prefixed[1:]:
        fused = onnx.compose.merge_models(fused, nxt, io_map=[])

    # --- prepend shared-input wrapper -----------------------------------
    # Build a new graph whose inputs are ``mix`` + ``z_cac`` and whose first
    # nodes are Identity ops that feed the (renamed) per-head inputs.
    from onnx import helper

    head_inputs = []  # list of (mix_name, zcac_name) per head
    for i in range(len(head_paths)):
        head_inputs.append((f"h{i}__mix", f"h{i}__z_cac"))

    # Take shape/type from head 0's renamed inputs.
    mix_vi = None
    zcac_vi = None
    for vi in fused.graph.input:
        if vi.name == head_inputs[0][0]:
            mix_vi = vi
        elif vi.name == head_inputs[0][1]:
            zcac_vi = vi
    if mix_vi is None or zcac_vi is None:
        raise RuntimeError("cannot find head 0 inputs in fused graph")

    shared_mix = helper.make_tensor_value_info(
        "mix", mix_vi.type.tensor_type.elem_type,
        [d.dim_value if d.HasField("dim_value") else d.dim_param
         for d in mix_vi.type.tensor_type.shape.dim],
    )
    shared_zcac = helper.make_tensor_value_info(
        "z_cac", zcac_vi.type.tensor_type.elem_type,
        [d.dim_value if d.HasField("dim_value") else d.dim_param
         for d in zcac_vi.type.tensor_type.shape.dim],
    )

    # Identity nodes copying shared inputs → per-head renamed inputs.
    fanout_nodes = []
    for i, (m_in, z_in) in enumerate(head_inputs):
        fanout_nodes.append(helper.make_node(
            "Identity", ["mix"], [m_in], name=f"fanout_mix_{i}"))
        fanout_nodes.append(helper.make_node(
            "Identity", ["z_cac"], [z_in], name=f"fanout_zcac_{i}"))

    # Mutate fused.graph: replace inputs with just (mix, z_cac), and prepend
    # fanout nodes. The per-head names become internal edges.
    g = fused.graph
    new_inputs = [shared_mix, shared_zcac]
    # Keep any other inputs that were NOT per-head mix/zcac (shouldn't be any).
    skip = set()
    for m_in, z_in in head_inputs:
        skip.add(m_in); skip.add(z_in)
    for vi in list(g.input):
        if vi.name not in skip and vi.name not in {"mix", "z_cac"}:
            new_inputs.append(vi)
    del g.input[:]
    g.input.extend(new_inputs)

    # Prepend fanout nodes in stable order.
    existing_nodes = list(g.node)
    del g.node[:]
    g.node.extend(fanout_nodes + existing_nodes)

    # Dedupe opset_import — onnx.compose.merge_models leaves one entry per
    # input model, producing duplicates that CoreML EP rejects when
    # compiling the MLProgram (SystemError 20).
    seen: dict[str, int] = {}
    for oi in fused.opset_import:
        prev = seen.get(oi.domain, -1)
        if oi.version > prev:
            seen[oi.domain] = oi.version
    del fused.opset_import[:]
    for dom, ver in seen.items():
        oi = fused.opset_import.add()
        oi.domain = dom
        oi.version = ver

    # Single-producer tag for cleanliness.
    fused.producer_name = "stemforge.fusion"
    fused.producer_version = "0.1"

    # Validate the graph structurally. External tensors aren't loaded here
    # since these were loaded without external-data materialised, so skip
    # full_check.
    try:
        onnx.checker.check_model(fused, full_check=False)
    except Exception as e:
        print(f"warning: onnx.checker.check_model: {e!s}", file=sys.stderr)

    dst_onnx.parent.mkdir(parents=True, exist_ok=True)
    onnx.save(
        fused,
        str(dst_onnx),
        save_as_external_data=True,
        all_tensors_to_one_file=True,
        location=dst_onnx.name + ".data",
        size_threshold=1024,
    )
    return fused


def fuse_two_heads(head_paths: list[Path], dst_onnx: Path) -> onnx.ModelProto:
    return fuse_heads(head_paths[:2], dst_onnx)


def _capture_coreml_coverage(onnx_path: Path, verbose_log: Path) -> SmokeResult:
    """Instantiate a CoreML-EP session, capture partition stats from ORT verbose log."""
    result = SmokeResult(fused_path=str(onnx_path))

    # Force verbose logging — CoreML EP prints its GetCapability line at VERBOSE.
    # We redirect stderr to a file to capture it.
    import contextlib

    sess_opts = ort.SessionOptions()
    sess_opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    sess_opts.log_severity_level = 0  # VERBOSE
    sess_opts.log_verbosity_level = 1

    coreml_opts = {
        "ModelFormat": "MLProgram",
        "MLComputeUnits": "ALL",
        "RequireStaticInputShapes": "1",
        "EnableOnSubgraphs": "1",
    }

    verbose_log.parent.mkdir(parents=True, exist_ok=True)
    log_fd = os.open(str(verbose_log), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
    saved_stderr = os.dup(2)
    try:
        os.dup2(log_fd, 2)
        try:
            sess = ort.InferenceSession(
                str(onnx_path), sess_opts,
                providers=[("CoreMLExecutionProvider", coreml_opts),
                           "CPUExecutionProvider"],
            )
            result.coreml_loaded = True
            # Optional: actually run once with zero inputs so CoreML compile happens.
            # Skipped here — we only care about static partition coverage.
            del sess
        except Exception as e:
            result.error = f"{type(e).__name__}: {e!s}"[:400]
    finally:
        os.dup2(saved_stderr, 2)
        os.close(saved_stderr)
        os.close(log_fd)

    # Parse the partition line out of the verbose log.
    try:
        text = verbose_log.read_text(errors="ignore")
    except FileNotFoundError:
        text = ""

    # Grab the line "number of partitions supported by CoreML: N ..." style.
    for line in text.splitlines():
        low = line.lower()
        if "coreml" in low and ("partition" in low or "number of nodes" in low):
            result.verbose_log_snippets.append(line.strip())
    # Best-effort parse of N / total.
    import re
    m_supported = re.search(r"number of nodes supported by CoreML:\s*(\d+)", text)
    m_total = re.search(r"number of nodes in the graph:\s*(\d+)", text)
    m_parts = re.search(r"number of partitions supported by CoreML:\s*(\d+)", text)
    if m_supported and m_total:
        result.coreml_nodes_supported = int(m_supported.group(1))
        result.total_nodes = int(m_total.group(1))
        if result.total_nodes > 0:
            result.coverage_pct = 100.0 * result.coreml_nodes_supported / result.total_nodes
    if m_parts:
        result.coreml_partitions = int(m_parts.group(1))
    return result


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--head0", default=str(FT_MODELS_DIR / "htdemucs_ft.head0_static.onnx"))
    p.add_argument("--head1", default=str(FT_MODELS_DIR / "htdemucs_ft.head1_static.onnx"))
    p.add_argument("--out", default="/tmp/sf_fusion_smoke.onnx")
    p.add_argument("--log", default="/tmp/sf_fusion_smoke.verbose.log")
    p.add_argument("--threshold", type=float, default=90.0,
                   help="coverage %% below which Phase 2 must abort")
    args = p.parse_args(argv)

    h0 = Path(args.head0)
    h1 = Path(args.head1)
    if not h0.exists() or not h1.exists():
        print(f"MISSING head files: {h0=} exists={h0.exists()} "
              f"{h1=} exists={h1.exists()}", file=sys.stderr)
        return 2

    out = Path(args.out)
    t0 = time.perf_counter()
    try:
        fuse_two_heads([h0, h1], out)
    except Exception as e:
        print(f"merge failed: {type(e).__name__}: {e!s}", file=sys.stderr)
        traceback.print_exc()
        return 3
    fuse_dt = time.perf_counter() - t0

    result = _capture_coreml_coverage(out, Path(args.log))
    print(json.dumps({
        "fused_path": result.fused_path,
        "fuse_sec": round(fuse_dt, 3),
        "coreml_loaded": result.coreml_loaded,
        "coverage_pct": result.coverage_pct,
        "coreml_partitions": result.coreml_partitions,
        "coreml_nodes_supported": result.coreml_nodes_supported,
        "total_nodes": result.total_nodes,
        "verbose_log": args.log,
        "error": result.error,
    }, indent=2))

    if result.coverage_pct is None:
        print(f"\nABORT: could not parse CoreML coverage from {args.log}",
              file=sys.stderr)
        return 4
    if result.coverage_pct < args.threshold:
        print(f"\nABORT: 2-head fusion coverage {result.coverage_pct:.1f}% "
              f"< threshold {args.threshold}%", file=sys.stderr)
        return 5

    print(f"\nPHASE 1 PASS: 2-head fusion CoreML coverage "
          f"{result.coverage_pct:.1f}% ≥ {args.threshold}% — proceed to Phase 2")
    return 0


if __name__ == "__main__":
    sys.exit(main())
