"""
Manifest writer for `v0/build/models/manifest.json`.

Schema (frozen here, consumed by Track A, Track E, Track F):

    {
      "schema_version": 1,
      "generated_at": "<ISO8601>",
      "ort_version": "1.24.4",
      "opset_version": 17,
      "models": {
        "<model_name>": {
          "path": "v0/build/models/<file>.onnx",
          "sha256": "<hex>",
          "size": <bytes>,
          "input_shape":  {"name": [d0, d1, ...]},
          "output_shape": {"name": [d0, d1, ...]},
          "torch_ref_checkpoint": "<hf-or-hub-id>",
          "max_abs_err": <float>,
          "max_rel_err": <float>,
          "precision": "fp32" | "fp16" | "int8-dynamic",
          "coreml_ep_supported": <bool>,
          "cpu_fallback_ops": [...],
          "optimized_cache": "v0/build/models/ort_cache/<model>/...",
          "notes": "<optional>"
        }
      }
    }
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import config


SCHEMA_VERSION = 1


def sha256_of_file(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            buf = fh.read(chunk)
            if not buf:
                break
            h.update(buf)
    return h.hexdigest()


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _ort_version() -> str:
    try:
        import onnxruntime
        return onnxruntime.__version__
    except Exception:
        return "unknown"


def _model_io_shapes(onnx_path: Path) -> tuple[dict, dict]:
    import onnx
    m = onnx.load(str(onnx_path), load_external_data=False)
    def _shape(t):
        dims = []
        for d in t.type.tensor_type.shape.dim:
            if d.HasField("dim_value"):
                dims.append(int(d.dim_value))
            else:
                dims.append(d.dim_param or "dynamic")
        return dims
    inputs = {t.name: _shape(t) for t in m.graph.input}
    outputs = {t.name: _shape(t) for t in m.graph.output}
    return inputs, outputs


def build_entry(onnx_path: Path, *,
                torch_ref_checkpoint: str,
                max_abs_err: float,
                max_rel_err: float,
                precision: str,
                coreml_ep_supported: bool,
                cpu_fallback_ops: list[str],
                optimized_cache: Path | None,
                notes: str = "") -> dict[str, Any]:
    inputs, outputs = _model_io_shapes(onnx_path)
    # Path stored in manifest is relative to repo root for portability.
    rel_path = onnx_path.resolve().relative_to(config.REPO_ROOT)
    rel_cache = (optimized_cache.resolve().relative_to(config.REPO_ROOT)
                 if optimized_cache and optimized_cache.exists() else None)
    return {
        "path": str(rel_path),
        "sha256": sha256_of_file(onnx_path),
        "size": onnx_path.stat().st_size,
        "input_shape": inputs,
        "output_shape": outputs,
        "torch_ref_checkpoint": torch_ref_checkpoint,
        "max_abs_err": float(max_abs_err),
        "max_rel_err": float(max_rel_err),
        "precision": precision,
        "coreml_ep_supported": bool(coreml_ep_supported),
        "cpu_fallback_ops": list(cpu_fallback_ops),
        "optimized_cache": (str(rel_cache) if rel_cache else None),
        "notes": notes,
    }


def write(entries: dict[str, dict[str, Any]]) -> Path:
    config.BUILD_MODELS_DIR.mkdir(parents=True, exist_ok=True)
    doc = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _utcnow(),
        "ort_version": _ort_version(),
        "opset_version": config.OPSET_VERSION,
        "models": entries,
    }
    with open(config.MANIFEST_PATH, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    return config.MANIFEST_PATH


def load() -> dict[str, Any]:
    if not config.MANIFEST_PATH.exists():
        return {"schema_version": SCHEMA_VERSION, "models": {}}
    with open(config.MANIFEST_PATH, "r", encoding="utf-8") as fh:
        return json.load(fh)
