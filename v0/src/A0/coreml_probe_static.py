"""
Track A.coreml — exhaustive CoreML EP probe on Demucs ONNX graphs.

Compares the existing *dynamic-shape* ONNX models against a re-exported
*static-shape* ONNX (created by ``reexport_static.py``) under several
CoreML EP option combinations, with verbose ORT logging captured per run
so we can count CoreML vs CPU node assignments.

Why this exists
---------------
A0's original ``coreml_probe.py`` reported ``coreml_ep_supported=False``
for every Demucs graph because the dynamic-shape graphs trip the
"unbounded dimension not supported" check inside the CoreML EP partitioner.
~77 % of nodes are statically schedulable but the EP refused them all.

This script gathers the data needed to flip that decision: for each ONNX
file × each CoreML option combo, capture node assignments, latency, and
any ORT_LOGGING errors, then print a concise comparison table.

Run as::

    python -m v0.src.A0.coreml_probe_static --models htdemucs

Outputs a JSON report at ``v0/state/A0/coreml_probe_static_report.json``
and a human-readable Markdown summary at
``v0/state/A0/coreml_probe_static_report.md``.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import re
import sys
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

# Avoid hard dep on `v0.src.A0.config` for the path constants — fall
# back to repo-root-relative if running stand-alone.
REPO_ROOT = Path(__file__).resolve().parents[3]
STATE_DIR = REPO_ROOT / "v0" / "state" / "A0"
STATE_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class ProbeResult:
    label: str
    onnx_path: str
    options: dict[str, str]
    providers_resolved: list[str] = field(default_factory=list)
    coreml_loaded: bool = False
    load_error: str | None = None
    forward_error: str | None = None
    n_nodes_total: int | None = None
    n_nodes_coreml: int | None = None
    n_nodes_cpu: int | None = None
    coreml_partition_pct: float | None = None
    runs: int = 0
    warmup_sec: float | None = None
    mean_latency_sec: float | None = None
    p50_latency_sec: float | None = None
    p95_latency_sec: float | None = None
    notes: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _stft_shape(segment_samples: int) -> tuple[int, int]:
    import math
    n_fft = 4096
    hop = 1024
    return n_fft // 2, int(math.ceil(segment_samples / hop))


def _build_inputs(segment_samples: int) -> dict[str, np.ndarray]:
    fq, frames = _stft_shape(segment_samples)
    rng = np.random.default_rng(42)
    return {
        "mix": rng.standard_normal((1, 2, segment_samples)).astype(np.float32) * 0.1,
        "z_cac": rng.standard_normal((1, 4, fq, frames)).astype(np.float32) * 0.1,
    }


def _count_nodes(onnx_path: Path) -> int | None:
    try:
        import onnx
    except ImportError:
        return None
    try:
        m = onnx.load(str(onnx_path))
        return len(m.graph.node)
    except Exception:
        return None


# ── ORT VERBOSE log scraping ────────────────────────────────────────────────

# CoreML EP emits lines like:
#   [V:onnxruntime:, coreml_execution_provider.cc:GetCapability]
#   <op_name> assigned to CoreML.
# and CPU EP keeps the rest. We tap stderr by replacing fd 2 with a pipe
# during the session-load call. ORT writes its log to stderr by default
# when log_severity_level=0 (VERBOSE).
@contextlib.contextmanager
def _capture_stderr_to_file():
    """Redirect fd 2 (stderr) to a temp file, yield path, restore on exit."""
    saved_fd = os.dup(2)
    tmp = tempfile.NamedTemporaryFile(prefix="ort_stderr_", suffix=".log",
                                      delete=False)
    try:
        os.dup2(tmp.fileno(), 2)
        tmp.close()
        yield Path(tmp.name)
    finally:
        os.dup2(saved_fd, 2)
        os.close(saved_fd)


_RE_COREML_NODE = re.compile(r"node:\s*'([^']+)'.*?(?:CoreML|coreml)",
                             re.IGNORECASE)
_RE_ASSIGN_LINE = re.compile(
    r"\b(?P<provider>CoreMLExecutionProvider|CPUExecutionProvider)\b",
    re.IGNORECASE,
)


def _scrape_assignments(log_path: Path) -> tuple[int, int]:
    """
    Parse ORT VERBOSE log for per-node EP assignments.

    Returns (n_coreml, n_cpu).  Counts lines that mention an EP next to a
    node name. Best-effort heuristic — log format varies across ORT
    versions. The authoritative answer is the partition graph, but
    counting assigned-vs-fallback per node is the practical signal.
    """
    if not log_path.exists():
        return 0, 0
    n_coreml = 0
    n_cpu = 0
    try:
        text = log_path.read_text(errors="replace")
    except Exception:
        return 0, 0
    # ORT logs nodes assigned to a partition with format like:
    #   "[VERBOSE] ... GraphPartitioner ... Node placed on EP CoreMLExecutionProvider: <name>"
    for line in text.splitlines():
        if "Node placed on EP" not in line and "assigned to" not in line:
            continue
        m = _RE_ASSIGN_LINE.search(line)
        if not m:
            continue
        if m.group("provider").lower().startswith("coreml"):
            n_coreml += 1
        else:
            n_cpu += 1
    return n_coreml, n_cpu


# ── Probe a single (onnx, options) combination ──────────────────────────────

def probe_one(label: str, onnx_path: Path,
              probe_inputs: dict[str, np.ndarray],
              coreml_options: dict[str, str] | None,
              n_warmup: int = 3, n_timed: int = 5) -> ProbeResult:
    import onnxruntime as ort

    res = ProbeResult(label=label, onnx_path=str(onnx_path),
                      options=dict(coreml_options or {}))

    so = ort.SessionOptions()
    so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    # Enable VERBOSE so per-node assignment is in the captured log.
    so.log_severity_level = 0
    so.intra_op_num_threads = max(1, (os.cpu_count() or 4) - 1)

    providers = (
        [("CoreMLExecutionProvider", coreml_options or {}),
         "CPUExecutionProvider"]
        if coreml_options is not None
        else ["CPUExecutionProvider"]
    )

    # Capture stderr (ORT VERBOSE log) during session load + first inference.
    with _capture_stderr_to_file() as log_path:
        try:
            sess = ort.InferenceSession(
                str(onnx_path), sess_options=so, providers=providers,
            )
            res.providers_resolved = list(sess.get_providers())
            res.coreml_loaded = "CoreMLExecutionProvider" in res.providers_resolved
        except Exception as e:
            res.load_error = f"{type(e).__name__}: {e!s}"[:600]
            return res

        # Warmup (also captures the first-run JIT/compile cost in the log).
        try:
            t0 = time.perf_counter()
            for _ in range(n_warmup):
                sess.run(None, probe_inputs)
            res.warmup_sec = round(time.perf_counter() - t0, 4)
        except Exception as e:
            res.forward_error = f"warmup: {type(e).__name__}: {e!s}"[:600]
            return res

    # Now scrape the log (after the with-block restores stderr).
    n_coreml, n_cpu = _scrape_assignments(log_path)
    res.n_nodes_coreml = n_coreml
    res.n_nodes_cpu = n_cpu
    res.n_nodes_total = _count_nodes(onnx_path)
    if res.n_nodes_total:
        denom = max(1, n_coreml + n_cpu) if (n_coreml + n_cpu) else res.n_nodes_total
        res.coreml_partition_pct = round(100.0 * n_coreml / denom, 2)

    # Timed runs (no log capture — we want pure latency).
    try:
        latencies = []
        for _ in range(n_timed):
            t0 = time.perf_counter()
            sess.run(None, probe_inputs)
            latencies.append(time.perf_counter() - t0)
        latencies.sort()
        res.runs = n_timed
        res.mean_latency_sec = round(sum(latencies) / len(latencies), 4)
        res.p50_latency_sec = round(latencies[len(latencies) // 2], 4)
        res.p95_latency_sec = round(latencies[min(len(latencies) - 1,
                                                  int(0.95 * len(latencies)))],
                                    4)
    except Exception as e:
        res.forward_error = f"timed: {type(e).__name__}: {e!s}"[:600]

    # Cleanup log file.
    try:
        log_path.unlink()
    except Exception:
        pass

    return res


# ── Probe matrix per ONNX file ──────────────────────────────────────────────

OPTION_MATRIX: list[tuple[str, dict[str, str] | None]] = [
    ("cpu_only", None),
    ("coreml_mlprogram_all_dynamic", {
        "MLComputeUnits": "ALL",
        "ModelFormat": "MLProgram",
        "RequireStaticInputShapes": "0",
        "EnableOnSubgraphs": "1",
    }),
    ("coreml_mlprogram_all_static", {
        "MLComputeUnits": "ALL",
        "ModelFormat": "MLProgram",
        "RequireStaticInputShapes": "1",
        "EnableOnSubgraphs": "1",
    }),
    ("coreml_mlprogram_ane_only", {
        "MLComputeUnits": "CPUAndNeuralEngine",
        "ModelFormat": "MLProgram",
        "RequireStaticInputShapes": "1",
        "EnableOnSubgraphs": "1",
    }),
    ("coreml_neuralnetwork_all", {
        "MLComputeUnits": "ALL",
        "ModelFormat": "NeuralNetwork",
        "RequireStaticInputShapes": "1",
        "EnableOnSubgraphs": "1",
    }),
]


def probe_file(label_prefix: str, onnx_path: Path,
               segment_samples: int = 343980,
               option_matrix: list = OPTION_MATRIX,
               n_warmup: int = 3, n_timed: int = 5) -> list[ProbeResult]:
    inputs = _build_inputs(segment_samples)
    results: list[ProbeResult] = []
    for combo_label, opts in option_matrix:
        full_label = f"{label_prefix}::{combo_label}"
        print(f"[probe] {full_label}", flush=True)
        try:
            r = probe_one(full_label, onnx_path, inputs, opts,
                          n_warmup=n_warmup, n_timed=n_timed)
        except Exception as e:
            r = ProbeResult(label=full_label, onnx_path=str(onnx_path),
                            options=dict(opts or {}),
                            load_error=f"outer: {type(e).__name__}: {e!s}")
        results.append(r)
        if r.load_error:
            print(f"  LOAD FAIL: {r.load_error}", flush=True)
        elif r.forward_error:
            print(f"  FWD  FAIL: {r.forward_error}", flush=True)
        else:
            print(f"  load=ok coreml_loaded={r.coreml_loaded} "
                  f"part={r.coreml_partition_pct}% mean={r.mean_latency_sec}s",
                  flush=True)
    return results


# ── Reporting ───────────────────────────────────────────────────────────────

def write_markdown_report(results: list[ProbeResult], path: Path) -> None:
    lines = ["# CoreML EP probe — static vs dynamic shapes", ""]
    lines += [
        "Sweep: each ONNX × CoreML option combination → ORT VERBOSE log",
        "scraped for per-node EP assignment + 5 timed runs after 3 warmup.",
        "",
        "| label | loaded | nodes(coreml/cpu/total) | part% | warmup_s | mean_s | p95_s | error |",
        "|---|---:|---|---:|---:|---:|---:|---|",
    ]
    for r in results:
        nodes = (f"{r.n_nodes_coreml}/{r.n_nodes_cpu}/{r.n_nodes_total}"
                 if r.n_nodes_total else "—")
        err = (r.load_error or r.forward_error or "").replace("|", "/")
        lines.append(
            f"| {r.label} | {r.coreml_loaded} | {nodes} | "
            f"{r.coreml_partition_pct} | {r.warmup_sec} | "
            f"{r.mean_latency_sec} | {r.p95_latency_sec} | {err[:120]} |"
        )
    lines.append("")
    lines.append("Note: ORT VERBOSE per-node assignment lines vary by version;")
    lines.append("`coreml_partition_pct` is a best-effort scrape of the load-time")
    lines.append("log. Authoritative count requires reading the partition graph.")
    path.write_text("\n".join(lines))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--onnx", action="append", required=True,
                   help="(label, path) pair, e.g. htdemucs:/abs/path.onnx")
    p.add_argument("--segment-samples", type=int, default=343980)
    p.add_argument("--report-json", type=Path,
                   default=STATE_DIR / "coreml_probe_static_report.json")
    p.add_argument("--report-md", type=Path,
                   default=STATE_DIR / "coreml_probe_static_report.md")
    args = p.parse_args(argv)

    all_results: list[ProbeResult] = []
    for spec in args.onnx:
        if ":" not in spec:
            print(f"bad --onnx spec: {spec}", file=sys.stderr)
            return 2
        label, path_str = spec.split(":", 1)
        path = Path(path_str)
        if not path.exists():
            print(f"missing onnx: {path}", file=sys.stderr)
            return 2
        all_results += probe_file(label, path,
                                  segment_samples=args.segment_samples)

    args.report_json.parent.mkdir(parents=True, exist_ok=True)
    with open(args.report_json, "w") as fh:
        json.dump([r.as_dict() for r in all_results], fh, indent=2)
        fh.write("\n")
    write_markdown_report(all_results, args.report_md)
    print(f"\nwrote {args.report_json}")
    print(f"wrote {args.report_md}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
