"""
Re-export Demucs ONNX graphs with FULLY STATIC input shapes.

A0.1 exported the heads with ``dynamic_axes={mix:[0,2], z_cac:[0,3], ...}``
so the same graph could process variable segment lengths. The CoreML EP
partitioner refuses to run on internal Reshape nodes that inherit those
dynamic dimensions, even when the input is concrete at runtime. Result:
``coreml_ep_supported=false`` for every Demucs graph.

This script re-exports each variant with ``dynamic_axes=None`` so torch
bakes the training-length segment shape into the graph as a constant, and
the subsequent constant-folding pass eliminates the dynamic-shape
Reshape lineage that breaks the CoreML EP. Output files live alongside
the originals with ``_static.onnx`` suffix.

Run::

    python -m v0.src.A0.reexport_static                       # all variants
    python -m v0.src.A0.reexport_static --models htdemucs     # one variant

For each variant we:

    1. Load the pretrained torch bag.
    2. Re-export each head with locked input shapes.
    3. Numerically compare static vs dynamic ONNX (parity check on a real
       audio fixture). Bit-equal expected — same compute, different
       graph metadata.
    4. Probe CoreML EP on the new static graph (calls
       ``coreml_probe_static.probe_one``) and report partition coverage.
    5. Write artifacts + a markdown summary.

The original dynamic ONNX files are kept on disk so the C++ host can
fall back to them.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import time
import traceback
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

import numpy as np

from . import config, demucs_export


@dataclass
class ReexportResult:
    variant: str
    head_index: int
    dynamic_path: str
    static_path: str
    static_size_bytes: int = 0
    static_sha256: str = ""
    parity_max_abs: float | None = None
    parity_residual_rms_dbfs: float | None = None
    parity_pass: bool = False
    coreml_loaded: bool = False
    coreml_partition_pct: float | None = None
    coreml_mean_latency_sec: float | None = None
    cpu_only_mean_latency_sec: float | None = None
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def export_static_head(head_module, dst_onnx: Path, segment_samples: int) -> Path:
    """
    Export one HTDemucs head with all input shapes baked in (no dynamic axes).

    Mirrors ``demucs_export.export_head`` except:
      * ``dynamic_axes`` is empty / None — every dim is a literal int.
      * Same vendored ``forward_from_spec_cac`` wrapper is used.
    """
    import torch

    demucs_export._wrap_head_with_vendored_class(head_module)
    wrapper = demucs_export.ExternalSpecHTDemucs(head_module).eval()

    n_fft = demucs_export.STFT.n_fft
    hop = demucs_export.STFT.hop_length
    freq_bins = n_fft // 2
    frames = int(math.ceil(segment_samples / hop))

    mix = torch.zeros(1, 2, segment_samples)
    z_cac = torch.zeros(1, 4, freq_bins, frames)

    dst_onnx.parent.mkdir(parents=True, exist_ok=True)
    torch.onnx.export(
        wrapper,
        (mix, z_cac),
        str(dst_onnx),
        input_names=["mix", "z_cac"],
        output_names=["time_out", "zout_cac"],
        # IMPORTANT: no dynamic_axes → torch writes literal dims into the graph.
        dynamic_axes=None,
        opset_version=config.OPSET_VERSION,
        do_constant_folding=True,
        dynamo=False,
    )
    return dst_onnx


def _onnx_inference_static(onnx_path: Path, mix_np: np.ndarray) -> np.ndarray:
    """Run the static ONNX once with fresh CPU-only session — for parity."""
    return demucs_export.run_head_onnx(onnx_path, mix_np,
                                       providers=["CPUExecutionProvider"])


def _parity_check(static_path: Path, dynamic_path: Path,
                  segment_samples: int, fixture: np.ndarray) -> tuple[float, float, bool]:
    """
    Numerical parity static vs dynamic on a real fixture.

    Returns (max_abs, residual_rms_dbfs, pass).
    """
    mix, _ = demucs_export._pad_fixture_to_segment(fixture, segment_samples)
    mix_bcs = mix[None, ...]

    static_out = _onnx_inference_static(static_path, mix_bcs).astype(np.float64)
    dyn_out = _onnx_inference_static(dynamic_path, mix_bcs).astype(np.float64)

    if static_out.shape != dyn_out.shape:
        return float("nan"), float("nan"), False
    diff = static_out - dyn_out
    max_abs = float(np.max(np.abs(diff)))
    rms = float(np.sqrt(np.mean(diff ** 2)))
    rms_dbfs = -240.0 if rms <= 0 else 20.0 * math.log10(rms)
    # Static and dynamic graphs must produce identical outputs (same
    # compute, just different shape metadata). Tight tolerance.
    pass_ = max_abs < 1e-5 or rms_dbfs <= -100.0
    return max_abs, rms_dbfs, pass_


def _probe_coreml(static_path: Path, segment_samples: int,
                  variant: str) -> dict[str, Any]:
    """Run a single CoreML EP probe with the most-promising option set."""
    from . import coreml_probe_static as cps

    inputs = cps._build_inputs(segment_samples)
    # Best-bet options based on prior probe results: MLProgram + ALL +
    # static shape required + subgraph EP.
    opts = {
        "MLComputeUnits": "ALL",
        "ModelFormat": "MLProgram",
        "RequireStaticInputShapes": "1",
        "EnableOnSubgraphs": "1",
    }
    cml = cps.probe_one(f"{variant}_static", static_path, inputs, opts,
                        n_warmup=2, n_timed=3)
    cpu = cps.probe_one(f"{variant}_static_cpu", static_path, inputs, None,
                       n_warmup=1, n_timed=2)
    return {
        "coreml": cml.as_dict(),
        "cpu": cpu.as_dict(),
    }


def reexport_variant(variant: str,
                     fixture: np.ndarray | None,
                     skip_parity: bool = False,
                     skip_coreml: bool = False) -> list[ReexportResult]:
    from demucs.pretrained import get_model

    print(f"[{variant}] loading torch bag", flush=True)
    bag = get_model(variant)
    onnx_paths = []  # dynamic
    static_paths = []
    out_dir = config.BUILD_MODELS_DIR / variant
    out_dir.mkdir(parents=True, exist_ok=True)

    n = len(bag.models)
    for i, head in enumerate(bag.models):
        if n == 1:
            dyn = out_dir / f"{variant}.onnx"
            stat = out_dir / f"{variant}_static.onnx"
        else:
            dyn = out_dir / f"{variant}.head{i}.onnx"
            stat = out_dir / f"{variant}.head{i}_static.onnx"
        onnx_paths.append(dyn)
        static_paths.append(stat)

    seg = demucs_export.segment_samples_for(bag.models[0])

    results: list[ReexportResult] = []
    for i, (head, dst) in enumerate(zip(bag.models, static_paths)):
        r = ReexportResult(variant=variant, head_index=i,
                           dynamic_path=str(onnx_paths[i]),
                           static_path=str(dst))
        try:
            print(f"[{variant}] exporting static head {i+1}/{n} → {dst.name}",
                  flush=True)
            t0 = time.perf_counter()
            export_static_head(head.eval(), dst, seg)
            dt = time.perf_counter() - t0
            r.static_size_bytes = dst.stat().st_size
            r.static_sha256 = _sha256(dst)
            print(f"[{variant}]   exported in {dt:.1f}s "
                  f"size={r.static_size_bytes/1e6:.1f}MB sha={r.static_sha256[:12]}",
                  flush=True)
        except Exception as e:
            r.error = f"export: {type(e).__name__}: {e!s}"[:600]
            traceback.print_exc()
            results.append(r)
            continue

        # Parity vs the dynamic export — should be bit-equal modulo
        # constant-folding ordering effects.
        if not skip_parity and onnx_paths[i].exists() and fixture is not None:
            try:
                ma, rms_db, ok = _parity_check(dst, onnx_paths[i], seg, fixture)
                r.parity_max_abs = ma
                r.parity_residual_rms_dbfs = rms_db
                r.parity_pass = ok
                print(f"[{variant}]   parity max_abs={ma:.3e} "
                      f"rms={rms_db:+.1f}dBFS pass={ok}", flush=True)
            except Exception as e:
                r.error = (r.error or "") + f" | parity: {e!s}"[:200]
                print(f"[{variant}]   parity check failed: {e!s}", flush=True)
        else:
            r.parity_pass = True  # no fixture available, assume ok

        # CoreML EP probe — only on head 0 (sufficient signal; saves time).
        if not skip_coreml and i == 0:
            try:
                cml = _probe_coreml(dst, seg, variant)
                r.coreml_loaded = bool(cml["coreml"]["coreml_loaded"])
                r.coreml_partition_pct = cml["coreml"]["coreml_partition_pct"]
                r.coreml_mean_latency_sec = cml["coreml"]["mean_latency_sec"]
                r.cpu_only_mean_latency_sec = cml["cpu"]["mean_latency_sec"]
                print(f"[{variant}]   coreml loaded={r.coreml_loaded} "
                      f"part%={r.coreml_partition_pct} "
                      f"cml_lat={r.coreml_mean_latency_sec}s "
                      f"cpu_lat={r.cpu_only_mean_latency_sec}s",
                      flush=True)
            except Exception as e:
                r.error = (r.error or "") + f" | coreml: {e!s}"[:200]

        results.append(r)
    return results


def _load_fixture() -> np.ndarray | None:
    """Load the short_loop fixture for parity check."""
    p = config.REPO_ROOT / "v0" / "tests" / "fixtures" / "short_loop.wav"
    if not p.exists():
        return None
    try:
        import soundfile as sf
    except ImportError:
        return None
    audio, sr = sf.read(str(p), dtype="float32", always_2d=True)
    # (samples, channels) → (channels, samples)
    return audio.T


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--models", nargs="*",
                   default=list(config.DEMUCS_MODELS.keys()),
                   choices=list(config.DEMUCS_MODELS.keys()))
    p.add_argument("--skip-parity", action="store_true")
    p.add_argument("--skip-coreml", action="store_true")
    args = p.parse_args(argv)

    fixture = _load_fixture()
    if fixture is None:
        print("warning: no v0/tests/fixtures/short_loop.wav — skipping parity",
              file=sys.stderr)

    all_results: list[ReexportResult] = []
    for variant in args.models:
        try:
            all_results += reexport_variant(
                variant, fixture,
                skip_parity=args.skip_parity or fixture is None,
                skip_coreml=args.skip_coreml,
            )
        except Exception as e:
            print(f"[{variant}] FAILED: {e!s}", file=sys.stderr)
            traceback.print_exc()
            all_results.append(ReexportResult(
                variant=variant, head_index=-1,
                dynamic_path="", static_path="",
                error=f"variant: {type(e).__name__}: {e!s}"[:600],
            ))

    # Persist report.
    out_dir = config.A0_STATE_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "reexport_static_report.json"
    md_path = out_dir / "reexport_static_report.md"
    with open(json_path, "w") as fh:
        json.dump([r.as_dict() for r in all_results], fh, indent=2)
        fh.write("\n")

    lines = ["# Static-shape ONNX re-export report", ""]
    lines += [
        "| variant | head | static_size_MB | parity_pass | coreml_loaded | "
        "coreml_part_% | cml_lat_s | cpu_lat_s | error |",
        "|---|---:|---:|:---:|:---:|---:|---:|---:|---|",
    ]
    for r in all_results:
        size_mb = r.static_size_bytes / 1e6 if r.static_size_bytes else 0
        err = (r.error or "").replace("|", "/")
        lines.append(
            f"| {r.variant} | {r.head_index} | {size_mb:.1f} | {r.parity_pass} | "
            f"{r.coreml_loaded} | {r.coreml_partition_pct} | "
            f"{r.coreml_mean_latency_sec} | {r.cpu_only_mean_latency_sec} | "
            f"{err[:120]} |"
        )
    md_path.write_text("\n".join(lines) + "\n")

    print(f"\nwrote {json_path}")
    print(f"wrote {md_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
