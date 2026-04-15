"""
02_uuid_cache_retry.py — retry the fused-graph CoreML compile with a UUID'd
cache directory to rule out stale partial writes / deterministic path
collisions as the root cause of SystemError: 20.

Strategy
--------
CoreML EP derives its MLPackage cache path from a hash of the model. If a
prior failed compile left a half-written directory at that path, subsequent
runs hit ENOTDIR when the EP tries to descend into a file-as-directory.

We force a fresh, unique directory per run via the ORT session config
``session.coreml.model_cache_dir``. If the compile succeeds under this
configuration, the C++ runtime needs to set a per-session cache dir too.

Outputs
-------
  /tmp/sf_fusion_debug/02_uuid_cache.log   — full verbose ORT log
  /tmp/sf_fusion_debug/02_uuid_cache.json  — structured summary
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
LOG = OUT_DIR / "02_uuid_cache.log"
REPORT = OUT_DIR / "02_uuid_cache.json"

# Shapes from fuse_ft.py (1, 2, 343980) mix and (1, 4, 2048, 336) z_cac.
MIX_SHAPE = (1, 2, 343980)
ZCAC_SHAPE = (1, 4, 2048, 336)


def main() -> int:
    summary: dict = {
        "fused_path": str(FUSED),
        "fused_exists": FUSED.exists(),
        "cache_dir": None,
        "coreml_loaded": False,
        "providers_resolved": [],
        "compile_error": None,
        "inference_ok": False,
        "inference_sec": None,
    }

    if not FUSED.exists():
        summary["error"] = (
            f"missing fused artifact: {FUSED}. Run "
            "`uv run --active python -m v0.src.A0.fuse_ft` first."
        )
        REPORT.write_text(json.dumps(summary, indent=2))
        print(json.dumps(summary, indent=2))
        return 2

    cache_dir = Path(f"/tmp/sf_coreml_cache_{uuid.uuid4().hex}")
    cache_dir.mkdir(parents=True, exist_ok=False)
    summary["cache_dir"] = str(cache_dir)
    print(f"[02] unique cache dir: {cache_dir}", flush=True)

    sess_opts = ort.SessionOptions()
    sess_opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    sess_opts.log_severity_level = 0
    sess_opts.log_verbosity_level = 1
    # Both known session-config keys for CoreML cache dir — ORT versions differ.
    for key in (
        "session.coreml.model_cache_dir",
        "ep.coreml.model_cache_dir",
    ):
        try:
            sess_opts.add_session_config_entry(key, str(cache_dir))
        except Exception as e:  # noqa: BLE001
            print(f"[02] session config {key}: {e}", flush=True)

    coreml_opts = {
        "ModelFormat": "MLProgram",
        "MLComputeUnits": "ALL",
        "RequireStaticInputShapes": "1",
        "EnableOnSubgraphs": "1",
        # Older CoreML EP variants accept ModelCacheDirectory as a provider option.
        "ModelCacheDirectory": str(cache_dir),
    }

    log_fd = os.open(str(LOG), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
    saved_stderr = os.dup(2)
    try:
        os.dup2(log_fd, 2)
        try:
            t0 = time.perf_counter()
            sess = ort.InferenceSession(
                str(FUSED),
                sess_opts,
                providers=[
                    ("CoreMLExecutionProvider", coreml_opts),
                    "CPUExecutionProvider",
                ],
            )
            t_load = time.perf_counter() - t0
            summary["coreml_loaded"] = True
            summary["providers_resolved"] = list(sess.get_providers())
            summary["load_sec"] = round(t_load, 3)

            mix = np.zeros(MIX_SHAPE, dtype=np.float32)
            zcac = np.zeros(ZCAC_SHAPE, dtype=np.float32)
            t1 = time.perf_counter()
            sess.run(None, {"mix": mix, "z_cac": zcac})
            summary["inference_ok"] = True
            summary["inference_sec"] = round(time.perf_counter() - t1, 3)
        except Exception as e:  # noqa: BLE001
            summary["compile_error"] = f"{type(e).__name__}: {e}"[:800]
            traceback.print_exc()
    finally:
        os.dup2(saved_stderr, 2)
        os.close(saved_stderr)
        os.close(log_fd)

    # Heuristic: if providers_resolved contains CoreML, compile succeeded.
    summary["coreml_compiled"] = (
        summary["coreml_loaded"]
        and "CoreMLExecutionProvider" in summary["providers_resolved"]
        and summary["compile_error"] is None
    )

    REPORT.write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))

    # Extra: dump cache-dir contents so we can see what CoreML wrote.
    listing = OUT_DIR / "02_cache_dir_listing.txt"
    with listing.open("w") as fh:
        for root, dirs, files in os.walk(cache_dir):
            for name in sorted(dirs + files):
                p = Path(root) / name
                try:
                    sz = p.stat().st_size
                except OSError:
                    sz = -1
                fh.write(f"{sz:>12}  {p}\n")
    print(f"[02] cache-dir listing: {listing}")
    return 0 if summary["coreml_compiled"] else 1


if __name__ == "__main__":
    sys.exit(main())
