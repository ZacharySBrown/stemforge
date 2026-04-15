"""
fuse_ft.py — Phase 2 full 4-head htdemucs_ft fusion.

Takes the 4 static ONNX heads and produces a single fused graph sharing
inputs ``mix`` + ``z_cac`` and emitting a single combined ``stems_out``
tensor of shape (1, 4, 2, segment_samples). The per-stem bag weights
matrix I_4 (head i → source i only) is applied via Gather nodes so the
fused graph returns the final 4 stems directly.

Structure::

    graph inputs:  mix (1,2,343980)   z_cac (1,4,2048,336)
        │  (Identity fanout x4)
        ├───► head0 subgraph ──► h0__time_out (1,4,2,343980)
        │                    └─► h0__zout_cac (1,4,4,2048,336)
        ├───► head1 subgraph ──► h1__time_out
        │                    └─► h1__zout_cac
        ├───► head2 subgraph ──► h2__time_out
        │                    └─► h2__zout_cac
        └───► head3 subgraph ──► h3__time_out
                             └─► h3__zout_cac

        Per head i, the combined stem for source i is the sum of the time
        and frequency branches. The frequency-branch iSTFT runs in the host
        (not ONNX), so this graph exposes BOTH time_out and zout_cac per
        head. The host then picks head i's stem i (via the I_4 weights),
        runs iSTFT on zout_cac[i], and sums with time_out[i]. That matches
        the unfused bag's behaviour bit-for-bit.

        We emit two graph outputs:
          time_out_stacked : (1, 4, 2, 343980)
              concat of each head's own stem, in canonical source order
              {drums, bass, other, vocals}.
          zout_cac_stacked : (1, 4, 4, 2048, 336)
              same but for the frequency branch.

        The Gather/Slice wiring handles the I_4 permutation inline so
        time_out_stacked[:, i] == h<i>__time_out[:, i].

Usage::

    uv run --active python -m v0.src.A0.fuse_ft
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import traceback
from pathlib import Path
from typing import Any

import onnx
from onnx import helper, TensorProto

from . import config
from .fusion_smoke import _prefix_model

FT_MODELS_DIR = config.BUILD_MODELS_DIR / "htdemucs_ft"

# Specialist matrix per v0/src/A/src/sf_demucs.hpp: head i produces source i.
# (head 0 → drums, head 1 → bass, head 2 → other, head 3 → vocals)
SPECIALIST_SOURCES = ["drums", "bass", "other", "vocals"]


def _dims_of(vi: onnx.ValueInfoProto) -> list[int | str]:
    return [d.dim_value if d.HasField("dim_value") else d.dim_param
            for d in vi.type.tensor_type.shape.dim]


def _dedupe_opsets(model: onnx.ModelProto) -> None:
    seen: dict[str, int] = {}
    for oi in model.opset_import:
        if oi.version > seen.get(oi.domain, -1):
            seen[oi.domain] = oi.version
    del model.opset_import[:]
    for dom, ver in seen.items():
        oi = model.opset_import.add()
        oi.domain = dom
        oi.version = ver


def fuse_ft(head_paths: list[Path], dst_onnx: Path) -> onnx.ModelProto:
    if len(head_paths) != 4:
        raise ValueError("htdemucs_ft requires exactly 4 heads")

    # Prefix each head (inputs, outputs, everything).
    prefixed: list[onnx.ModelProto] = []
    for i, p in enumerate(head_paths):
        m = onnx.load(str(p))
        prefixed.append(_prefix_model(m, f"h{i}__", rename_io=True))

    fused = prefixed[0]
    for nxt in prefixed[1:]:
        fused = onnx.compose.merge_models(fused, nxt, io_map=[])

    # Shared inputs + Identity fanout per head.
    mix_vi = next(vi for vi in fused.graph.input if vi.name == "h0__mix")
    zcac_vi = next(vi for vi in fused.graph.input if vi.name == "h0__z_cac")

    shared_mix = helper.make_tensor_value_info(
        "mix", mix_vi.type.tensor_type.elem_type, _dims_of(mix_vi))
    shared_zcac = helper.make_tensor_value_info(
        "z_cac", zcac_vi.type.tensor_type.elem_type, _dims_of(zcac_vi))

    fanout = []
    for i in range(4):
        fanout.append(helper.make_node(
            "Identity", ["mix"], [f"h{i}__mix"], name=f"fanout_mix_{i}"))
        fanout.append(helper.make_node(
            "Identity", ["z_cac"], [f"h{i}__z_cac"], name=f"fanout_zcac_{i}"))

    g = fused.graph
    skip = {f"h{i}__mix" for i in range(4)} | {f"h{i}__z_cac" for i in range(4)}
    keep_inputs = [vi for vi in list(g.input) if vi.name not in skip]
    del g.input[:]
    g.input.extend([shared_mix, shared_zcac] + keep_inputs)

    existing = list(g.node)
    del g.node[:]
    g.node.extend(fanout + existing)

    # Per-head Gather: pick head i's own source i from its (1, 4, 2, N) /
    # (1, 4, 4, F, T) outputs. Then Concat along source dim to yield
    # (1, 4, 2, N) and (1, 4, 4, F, T).
    #
    # Gather axis=1 (the source dim), indices=[i], keepdims.
    idx_initializers = []
    for i in range(4):
        init = helper.make_tensor(f"src_idx_{i}", TensorProto.INT64, [1], [i])
        idx_initializers.append(init)
    g.initializer.extend(idx_initializers)

    picker_nodes = []
    picked_time = []
    picked_zcac = []
    for i in range(4):
        picker_nodes.append(helper.make_node(
            "Gather", [f"h{i}__time_out", f"src_idx_{i}"], [f"pick_time_{i}"],
            name=f"pick_time_{i}", axis=1))
        picker_nodes.append(helper.make_node(
            "Gather", [f"h{i}__zout_cac", f"src_idx_{i}"], [f"pick_zcac_{i}"],
            name=f"pick_zcac_{i}", axis=1))
        picked_time.append(f"pick_time_{i}")
        picked_zcac.append(f"pick_zcac_{i}")
    # Concat along axis=1 (source dim) to reconstruct a 4-stem tensor.
    picker_nodes.append(helper.make_node(
        "Concat", picked_time, ["time_out_stacked"],
        name="concat_time", axis=1))
    picker_nodes.append(helper.make_node(
        "Concat", picked_zcac, ["zout_cac_stacked"],
        name="concat_zcac", axis=1))

    g.node.extend(picker_nodes)

    # Replace graph outputs with two combined outputs.
    time_shape = _dims_of(next(vi for vi in g.output if vi.name == "h0__time_out"))
    zcac_shape = _dims_of(next(vi for vi in g.output if vi.name == "h0__zout_cac"))
    # shape is (1, 4, 2, N) / (1, 4, 4, F, T) — after per-head gather axis=1 keepdim
    # becomes (1, 1, 2, N) / (1, 1, 4, F, T), concat along axis=1 rebuilds (1, 4, …).
    new_time = helper.make_tensor_value_info(
        "time_out_stacked", TensorProto.FLOAT, time_shape)
    new_zcac = helper.make_tensor_value_info(
        "zout_cac_stacked", TensorProto.FLOAT, zcac_shape)
    del g.output[:]
    g.output.extend([new_time, new_zcac])

    _dedupe_opsets(fused)
    fused.producer_name = "stemforge.fuse_ft"
    fused.producer_version = "0.1"

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


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out-name", default="htdemucs_ft_fused.onnx")
    p.add_argument("--out-dir", default=str(FT_MODELS_DIR))
    args = p.parse_args(argv)

    out_dir = Path(args.out_dir)
    out_path = out_dir / args.out_name
    head_paths = [out_dir / f"htdemucs_ft.head{i}_static.onnx"
                  for i in range(4)]
    for p in head_paths:
        if not p.exists():
            print(f"MISSING: {p}", file=sys.stderr)
            return 2

    t0 = time.perf_counter()
    try:
        fuse_ft(head_paths, out_path)
    except Exception as e:
        print(f"fuse_ft failed: {type(e).__name__}: {e!s}", file=sys.stderr)
        traceback.print_exc()
        return 3
    dt = time.perf_counter() - t0

    data_path = out_path.with_name(out_path.name + ".data")
    onnx_size = out_path.stat().st_size
    data_size = data_path.stat().st_size if data_path.exists() else 0
    sha = _sha256(out_path)

    result = {
        "fused_path": str(out_path),
        "fused_data_path": str(data_path),
        "onnx_size_bytes": onnx_size,
        "data_size_bytes": data_size,
        "total_size_bytes": onnx_size + data_size,
        "sha256": sha,
        "elapsed_sec": round(dt, 3),
    }
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
