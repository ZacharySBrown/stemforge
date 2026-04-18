"""
03_subgraphs_off_retry.py — try four CoreML EP option combos on the fused
graph to see whether any avoids the SystemError: 20 compile failure.

Rationale
---------
The 4-head fusion has a parallel-subgraph topology (4 heads chained via
onnx.compose.merge_models). CoreML EP's per-subgraph compile path may be
what's producing invalid bundle metadata. Disabling subgraph partitioning
and/or forcing NeuralNetwork format may route around the bug.

Matrix
------
  A: EnableOnSubgraphs=0, ModelFormat=MLProgram     — primary hypothesis
  B: EnableOnSubgraphs=0, ModelFormat=NeuralNetwork — legacy format, subgraphs off
  C: EnableOnSubgraphs=1, ModelFormat=NeuralNetwork — legacy format, subgraphs on
  D: MLComputeUnits=CPUOnly                         — sanity; should always load

For each combo:
  - Build the session (triggers CoreML compile).
  - Run one dummy inference (zeros). Confirms compile actually finished.
  - Record providers_resolved, timings, and any exception.

Outputs
-------
  /tmp/sf_fusion_debug/03_subgraphs_off.log         — combined verbose log
  /tmp/sf_fusion_debug/03_subgraphs_off.json        — {combo: result}
"""
from __future__ import annotations

import json
import os
import sys
import time
import traceback
import uuid
from pathlib import Path

import numpy as np
import onnxruntime as ort

REPO_ROOT = Path(__file__).resolve().parents[4]
FUSED = REPO_ROOT / "v0" / "build" / "models" / "htdemucs_ft" / "htdemucs_ft_fused.onnx"
OUT_DIR = Path("/tmp/sf_fusion_debug")
OUT_DIR.mkdir(parents=True, exist_ok=True)
LOG = OUT_DIR / "03_subgraphs_off.log"
REPORT = OUT_DIR / "03_subgraphs_off.json"

MIX_SHAPE = (1, 2, 343980)
ZCAC_SHAPE = (1, 4, 2048, 336)

COMBOS = {
    "A_mlprogram_subgraphs_off": {
        "ModelFormat": "MLProgram",
        "MLComputeUnits": "ALL",
        "RequireStaticInputShapes": "1",
        "EnableOnSubgraphs": "0",
    },
    "B_neuralnet_subgraphs_off": {
        "ModelFormat": "NeuralNetwork",
        "MLComputeUnits": "ALL",
        "RequireStaticInputShapes": "1",
        "EnableOnSubgraphs": "0",
    },
    "C_neuralnet_subgraphs_on": {
        "ModelFormat": "NeuralNetwork",
        "MLComputeUnits": "ALL",
        "RequireStaticInputShapes": "1",
        "EnableOnSubgraphs": "1",
    },
    "D_cpuonly_sanity": {
        "ModelFormat": "MLProgram",
        "MLComputeUnits": "CPUOnly",
        "RequireStaticInputShapes": "1",
        "EnableOnSubgraphs": "1",
    },
}


def run_one(name: str, opts: dict[str, str]) -> dict:
    result = {
        "name": name,
        "options": opts,
        "cache_dir": None,
        "coreml_loaded": False,
        "providers_resolved": [],
        "load_sec": None,
        "inference_ok": False,
        "inference_sec": None,
        "error": None,
    }
    cache_dir = Path(f"/tmp/sf_coreml_cache_{name}_{uuid.uuid4().hex}")
    cache_dir.mkdir(parents=True, exist_ok=False)
    result["cache_dir"] = str(cache_dir)
    opts_with_cache = dict(opts)
    opts_with_cache["ModelCacheDirectory"] = str(cache_dir)

    sess_opts = ort.SessionOptions()
    sess_opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    sess_opts.log_severity_level = 0
    sess_opts.log_verbosity_level = 1
    try:
        sess_opts.add_session_config_entry(
            "session.coreml.model_cache_dir", str(cache_dir)
        )
    except Exception:  # noqa: BLE001
        pass

    print(f"\n[03] ===== combo {name} =====", flush=True)
    print(f"[03] options: {opts_with_cache}", flush=True)

    try:
        t0 = time.perf_counter()
        sess = ort.InferenceSession(
            str(FUSED),
            sess_opts,
            providers=[
                ("CoreMLExecutionProvider", opts_with_cache),
                "CPUExecutionProvider",
            ],
        )
        result["load_sec"] = round(time.perf_counter() - t0, 3)
        result["coreml_loaded"] = True
        result["providers_resolved"] = list(sess.get_providers())

        mix = np.zeros(MIX_SHAPE, dtype=np.float32)
        zcac = np.zeros(ZCAC_SHAPE, dtype=np.float32)
        t1 = time.perf_counter()
        sess.run(None, {"mix": mix, "z_cac": zcac})
        result["inference_sec"] = round(time.perf_counter() - t1, 3)
        result["inference_ok"] = True
    except Exception as e:  # noqa: BLE001
        result["error"] = f"{type(e).__name__}: {e}"[:800]
        traceback.print_exc()

    result["coreml_compiled"] = (
        result["coreml_loaded"]
        and "CoreMLExecutionProvider" in result["providers_resolved"]
        and result["error"] is None
    )
    print(f"[03] result {name}: compiled={result['coreml_compiled']} "
          f"loaded={result['coreml_loaded']} "
          f"infer={result['inference_sec']}s err={result['error']}", flush=True)
    return result


def main() -> int:
    if not FUSED.exists():
        print(f"ERROR: missing fused artifact: {FUSED}", file=sys.stderr)
        print("Run `uv run --active python -m v0.src.A0.fuse_ft` first.",
              file=sys.stderr)
        return 2

    results: dict[str, dict] = {}
    log_fd = os.open(str(LOG), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
    saved_stderr = os.dup(2)
    try:
        os.dup2(log_fd, 2)
        for name, opts in COMBOS.items():
            results[name] = run_one(name, opts)
    finally:
        os.dup2(saved_stderr, 2)
        os.close(saved_stderr)
        os.close(log_fd)

    REPORT.write_text(json.dumps(results, indent=2))
    print(json.dumps(results, indent=2))

    # Exit 0 if at least one combo (other than D CPUOnly) compiled on CoreML.
    success = any(
        r["coreml_compiled"]
        for name, r in results.items()
        if name != "D_cpuonly_sanity"
    )
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
