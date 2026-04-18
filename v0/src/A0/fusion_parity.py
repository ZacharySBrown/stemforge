"""
fusion_parity.py — Parity + latency check for the htdemucs_ft fused graph.

Runs BOTH the fused graph and the 4 unfused heads on the same STFT/mix
inputs (shared Python-side pre-processing), then compares per-stem.

Specifically, for each source i:
    fused time_out_stacked[:, i]  should equal  head_i.time_out[:, i]
    fused zout_cac_stacked[:, i]  should equal  head_i.zout_cac[:, i]

This checks that our Gather-then-Concat combiner correctly implements the
I_4 specialist matrix without perturbing the learned weights.

Uses CPU EP on both sides. CoreML EP testing for the fused graph is
blocked by the MLProgram SystemError 20 compile failure
(see v0/state/A/fusion_aborted.md for details).
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

import numpy as np
import onnxruntime as ort

from . import config, demucs_export

FT_MODELS_DIR = config.BUILD_MODELS_DIR / "htdemucs_ft"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--fused", default=str(FT_MODELS_DIR / "htdemucs_ft_fused.onnx"))
    p.add_argument("--fixture", default=str(
        config.REPO_ROOT / "v0/tests/fixtures/short_loop.wav"))
    args = p.parse_args(argv)

    import soundfile as sf
    import torch

    fixture_audio, _sr = sf.read(args.fixture, dtype="float32", always_2d=True)
    fixture_audio = fixture_audio.T
    seg = 343980
    mix, _ = demucs_export._pad_fixture_to_segment(fixture_audio, seg)
    mix_t = torch.from_numpy(mix).to(torch.float32)[None, ...]
    z = demucs_export.apply_stft(mix_t)
    z_cac = demucs_export.pack_cac(z).numpy().astype(np.float32)
    mix_in = mix_t.numpy().astype(np.float32)

    # Fused
    sess_f = ort.InferenceSession(args.fused, providers=["CPUExecutionProvider"])
    t0 = time.perf_counter()
    fused_time, fused_zcac = sess_f.run(None, {"mix": mix_in, "z_cac": z_cac})
    t_fused = time.perf_counter() - t0
    print(f"fused  time_out shape={fused_time.shape} zout_cac shape={fused_zcac.shape}")
    print(f"fused  inference   = {t_fused:.3f} s (CPU)")

    # 4 unfused heads (sequential CPU — the status quo).
    unfused_sess = [
        ort.InferenceSession(
            str(FT_MODELS_DIR / f"htdemucs_ft.head{i}_static.onnx"),
            providers=["CPUExecutionProvider"]) for i in range(4)
    ]
    t0 = time.perf_counter()
    unfused_outs = [s.run(None, {"mix": mix_in, "z_cac": z_cac})
                    for s in unfused_sess]
    t_unfused = time.perf_counter() - t0
    print(f"unfused bag seq    = {t_unfused:.3f} s (CPU, 4 heads)")

    # Parity per source.
    per_source = []
    max_abs_t = 0.0
    max_abs_z = 0.0
    for i in range(4):
        # Each unfused head outputs (1, 4, 2, N); for head i, specialist source = i.
        ref_t = unfused_outs[i][0][:, i:i + 1]  # keepdims
        got_t = fused_time[:, i:i + 1]
        ref_z = unfused_outs[i][1][:, i:i + 1]
        got_z = fused_zcac[:, i:i + 1]
        d_t = float(np.max(np.abs(ref_t - got_t)))
        d_z = float(np.max(np.abs(ref_z - got_z)))
        rms_t_lin = float(np.sqrt(np.mean((ref_t - got_t) ** 2)))
        rms_t_db = -240.0 if rms_t_lin <= 0 else 20.0 * math.log10(rms_t_lin)
        per_source.append({"source_index": i, "max_abs_time": d_t,
                           "max_abs_zcac": d_z, "rms_time_dbfs": rms_t_db})
        max_abs_t = max(max_abs_t, d_t)
        max_abs_z = max(max_abs_z, d_z)

    # Combined time-branch residual RMS.
    combined_time_ref = np.concatenate(
        [unfused_outs[i][0][:, i:i + 1] for i in range(4)], axis=1)
    resid = combined_time_ref.astype(np.float64) - fused_time.astype(np.float64)
    rms = float(np.sqrt(np.mean(resid ** 2)))
    rms_db = -240.0 if rms <= 0 else 20.0 * math.log10(rms)

    summary = {
        "fused_inference_cpu_sec": t_fused,
        "unfused_bag_cpu_sec": t_unfused,
        "cpu_speedup_vs_unfused_bag": t_unfused / t_fused if t_fused > 0 else None,
        "max_abs_time": max_abs_t,
        "max_abs_zcac": max_abs_z,
        "residual_rms_dbfs_time": rms_db,
        "parity_pass_lt_60dbfs": rms_db <= -60.0,
        "per_source": per_source,
    }
    print(json.dumps(summary, indent=2))

    if summary["parity_pass_lt_60dbfs"]:
        print("\nPARITY PASS: time-branch RMS residual "
              f"{rms_db:+.1f} dBFS ≤ -60 dBFS threshold")
        return 0
    else:
        print(f"\nPARITY FAIL: time-branch RMS residual {rms_db:+.1f} dBFS "
              "> -60 dBFS threshold", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
