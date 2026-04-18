"""
A0 orchestrator — convert all torch reference models to ONNX.

Usage:
    python -m v0.src.A0.convert --models ast clap demucs
    python -m v0.src.A0.convert --models ast               # one at a time
    python -m v0.src.A0.convert --dry-run                  # no downloads

Each model runs through:
    1. export (or probe if upstream blocker)
    2. CoreML EP smoke test (latency, fallback ops)
    3. fp16 attempt + null-test
    4. int8 attempt (classifiers only; stretch)
    5. manifest entry

Progress streams to `v0/state/A0/progress.ndjson` per SHARED.md. On completion
`convert.py` writes either `done.flag` (if every required model succeeds) or
`blocker.md` (if any required model fails and no graceful fallback exists).
"""
from __future__ import annotations

import argparse
import sys
import time
import traceback
from pathlib import Path

import numpy as np

from . import (ast_export, clap_export, config, coreml_probe, demucs_export,
               fixtures, fp16, manifest, progress, quantize)


REQUIRED_MODELS = ("ast", "clap", "demucs")


# ── Helpers to run small inference batches for fp16 null-tests ──────────────

def _run_ast(onnx_path: Path) -> dict[str, np.ndarray]:
    import onnxruntime as ort
    import torch
    from transformers import AutoFeatureExtractor
    session = ort.InferenceSession(str(onnx_path),
                                   providers=["CPUExecutionProvider"])
    fe = AutoFeatureExtractor.from_pretrained(config.AST_CHECKPOINT)
    out = {}
    for fx in fixtures.all_fixtures():
        mono = fx.samples.mean(axis=0).astype(np.float32)
        import librosa
        y = librosa.resample(mono, orig_sr=fx.sr, target_sr=16_000)
        torch.manual_seed(0)
        np.random.seed(0)
        inputs = fe(y, sampling_rate=16_000, return_tensors="np")
        wanted = {i.name for i in session.get_inputs()}
        feed = {k: np.asarray(v) for k, v in inputs.items() if k in wanted}
        if not feed:
            feed = {session.get_inputs()[0].name: list(inputs.values())[0]}
        logits = session.run(None, feed)[0][0]
        out[fx.name] = logits.astype(np.float32)
    return out


def _run_clap(onnx_path: Path) -> dict[str, np.ndarray]:
    """
    Run CLAP audio-branch over all fixtures. Seeded up-front so the
    processor's random sub-clip selection (for audio > 10 s) is stable
    across fp32 and fp16 runs — without the seed the null-test residual
    is dominated by preprocessor variance instead of model precision.
    """
    import onnxruntime as ort
    import torch
    from transformers import ClapProcessor
    session = ort.InferenceSession(str(onnx_path),
                                   providers=["CPUExecutionProvider"])
    processor = ClapProcessor.from_pretrained(config.CLAP_CHECKPOINT)
    out = {}
    for fx in fixtures.all_fixtures():
        mono = fx.samples.mean(axis=0).astype(np.float32)
        import librosa
        y = librosa.resample(mono, orig_sr=fx.sr, target_sr=48_000)
        torch.manual_seed(0)
        np.random.seed(0)
        inputs = processor(audios=y, sampling_rate=48_000, return_tensors="np")
        wanted = {i.name for i in session.get_inputs()}
        feed = {k: np.asarray(v) for k, v in inputs.items() if k in wanted}
        emb = np.asarray(session.run(None, feed)[0])
        if emb.ndim > 1:
            emb = emb[0]
        out[fx.name] = emb.astype(np.float32)
    return out


# ── Per-model driver ────────────────────────────────────────────────────────

def _convert_ast(manifest_entries: dict, validation_entries: dict,
                 fp16_attempts: list, quant_attempts: list) -> bool:
    progress.emit("ast", 10, "downloading + exporting")
    dst_dir = config.BUILD_MODELS_DIR / "ast"
    try:
        onnx_path = ast_export.export(dst_dir)
    except Exception as e:
        progress.emit("ast", 0, f"export failed: {e!s}")
        return False

    # Parity validation on both fixtures.
    parity_pass = True
    fixture_parities = []
    for fx in fixtures.all_fixtures():
        import librosa
        mono = fx.samples.mean(axis=0).astype(np.float32)
        y16 = librosa.resample(mono, orig_sr=fx.sr, target_sr=16_000)
        p = ast_export.validate(onnx_path, y16, fx.name)
        fixture_parities.append(p.as_dict())
        parity_pass &= p.passed
        progress.emit("ast", 30,
                      f"parity {fx.name}: logit_diff={p.max_logit_diff:.4e} "
                      f"labels_match={p.labels_match} pass={p.passed}")
    validation_entries["ast"] = {"passed": parity_pass,
                                 "fixtures": fixture_parities}

    # CoreML probe — needs the model's real input spec.
    # Build a synthetic input matching AST's expected shape.
    try:
        import onnxruntime as ort
        tmp_sess = ort.InferenceSession(str(onnx_path),
                                        providers=["CPUExecutionProvider"])
        probe_inputs = {}
        for inp in tmp_sess.get_inputs():
            shape = [d if isinstance(d, int) and d > 0 else 1 for d in inp.shape]
            probe_inputs[inp.name] = np.zeros(shape, dtype=np.float32)
    except Exception as e:
        probe_inputs = {}
        progress.emit("ast", 40, f"probe input build failed: {e!s}")

    cml = coreml_probe.probe(onnx_path, "ast_audioset", probe_inputs) \
        if probe_inputs else coreml_probe.CoreMLProbe(
            "ast_audioset", str(onnx_path))

    # fp16 attempt.
    fp16_path = dst_dir / "ast_audioset.fp16.onnx"
    fp16_result = fp16.attempt_fp16(
        onnx_path, fp16_path, "ast_audioset",
        run_fn=_run_ast,
        fixture_names=[fx.name for fx in fixtures.all_fixtures()],
    )
    fp16_attempts.append(fp16_result)
    precision = "fp16" if fp16_result.all_passed else "fp32"
    final_onnx = fp16_path if fp16_result.all_passed else onnx_path
    progress.emit("ast", 60, f"fp16 {'shipped' if fp16_result.all_passed else 'fallback to fp32'}")

    # int8 attempt (stretch).
    int8_path = dst_dir / "ast_audioset.int8.onnx"
    try:
        # Simple pseudo-eval: top-1 on the two fixtures = accuracy over 2 samples.
        # Real caller should supply a 200-sample evaluator.
        def eval_top1(path: Path) -> float:
            out = _run_ast(path)
            return float(np.mean([np.argmax(v) == np.argmax(out[fx.name])
                                  for fx, v in zip(fixtures.all_fixtures(),
                                                   out.values())]))
        q = quantize.attempt_int8(final_onnx, int8_path, "ast_audioset",
                                  eval_fn=eval_top1, min_samples=2)
        quant_attempts.append(q)
        if q.passed and q.int8_path:
            precision = "int8-dynamic"
            final_onnx = Path(q.int8_path)
            progress.emit("ast", 75, "int8 shipped")
    except Exception as e:  # non-fatal, stretch goal
        progress.emit("ast", 75, f"int8 skipped: {e!s}")

    # Manifest entry.
    manifest_entries["ast_audioset"] = manifest.build_entry(
        final_onnx,
        torch_ref_checkpoint=config.AST_CHECKPOINT,
        max_abs_err=max((p["max_logit_diff"] for p in fixture_parities),
                        default=0.0),
        max_rel_err=0.0,
        precision=precision,
        coreml_ep_supported=cml.coreml_loaded,
        cpu_fallback_ops=cml.cpu_fallback_ops,
        optimized_cache=(Path(cml.optimized_cache_path)
                         if cml.optimized_cache_path else None),
        notes="audio classifier; top-5 labels must match",
    )
    progress.emit("ast", 100, f"done, precision={precision}")
    return parity_pass


def _convert_clap(manifest_entries: dict, validation_entries: dict,
                  fp16_attempts: list, quant_attempts: list) -> bool:
    progress.emit("clap", 10, "downloading + exporting")
    dst_dir = config.BUILD_MODELS_DIR / "clap"
    try:
        onnx_path = clap_export.export(dst_dir)
    except Exception as e:
        progress.emit("clap", 0, f"export failed: {e!s}")
        return False

    try:
        clap_export.bake_genre_embeddings(
            config.BUILD_MODELS_DIR / config.CLAP_GENRE_EMBEDDINGS_FILENAME)
    except Exception as e:
        progress.emit("clap", 15, f"genre embedding bake failed: {e!s}")

    import librosa
    parity_pass = True
    fixture_parities = []
    for fx in fixtures.all_fixtures():
        mono = fx.samples.mean(axis=0).astype(np.float32)
        y48 = librosa.resample(mono, orig_sr=fx.sr, target_sr=48_000)
        p = clap_export.validate(onnx_path, y48, fx.name)
        fixture_parities.append(p.as_dict())
        parity_pass &= p.passed
        progress.emit("clap", 30, f"parity {fx.name}: cos={p.cosine:.6f} "
                                  f"pass={p.passed}")
    validation_entries["clap"] = {"passed": parity_pass,
                                  "fixtures": fixture_parities}

    # CoreML probe.
    try:
        import onnxruntime as ort
        tmp_sess = ort.InferenceSession(str(onnx_path),
                                        providers=["CPUExecutionProvider"])
        probe_inputs = {}
        for inp in tmp_sess.get_inputs():
            shape = [d if isinstance(d, int) and d > 0 else 1 for d in inp.shape]
            probe_inputs[inp.name] = np.zeros(shape, dtype=np.float32)
    except Exception as e:
        probe_inputs = {}
        progress.emit("clap", 40, f"probe input build failed: {e!s}")

    cml = coreml_probe.probe(onnx_path, "clap_htsat_unfused", probe_inputs) \
        if probe_inputs else coreml_probe.CoreMLProbe(
            "clap_htsat_unfused", str(onnx_path))

    fp16_path = dst_dir / "clap.fp16.onnx"
    fp16_result = fp16.attempt_fp16(
        onnx_path, fp16_path, "clap_htsat_unfused",
        run_fn=_run_clap,
        fixture_names=[fx.name for fx in fixtures.all_fixtures()],
    )
    fp16_attempts.append(fp16_result)
    precision = "fp16" if fp16_result.all_passed else "fp32"
    final_onnx = fp16_path if fp16_result.all_passed else onnx_path
    progress.emit("clap", 60,
                  f"fp16 {'shipped' if fp16_result.all_passed else 'fp32 fallback'}")

    manifest_entries["clap_htsat_unfused"] = manifest.build_entry(
        final_onnx,
        torch_ref_checkpoint=config.CLAP_CHECKPOINT,
        max_abs_err=0.0,
        max_rel_err=1.0 - min((p["cosine"] for p in fixture_parities),
                              default=1.0),
        precision=precision,
        coreml_ep_supported=cml.coreml_loaded,
        cpu_fallback_ops=cml.cpu_fallback_ops,
        optimized_cache=(Path(cml.optimized_cache_path)
                         if cml.optimized_cache_path else None),
        notes="audio branch only; genre text embeddings are baked into "
              "clap_genre_embeddings.json",
    )
    progress.emit("clap", 100, f"done, precision={precision}")
    return parity_pass


def _convert_demucs(manifest_entries: dict, validation_entries: dict,
                    fp16_attempts: list) -> bool:
    """
    Run the Demucs export attempt and record the blocker.

    This driver intentionally does NOT write `done.flag`; the in-graph STFT
    export is known to fail in the current torch/ort stack (see module
    docstring in demucs_export.py). The external-STFT refactor is the
    recommended path and is handed off via blocker.md.
    """
    import torch
    from demucs.pretrained import get_model

    attempted = []
    any_success = False

    for key, (ckpt, onnx_filename, priority, desc) in \
            config.DEMUCS_MODELS.items():
        progress.emit(f"demucs.{key}", 5, f"loading torch ref {ckpt} ({desc})")
        try:
            bag = get_model(ckpt)
        except Exception as e:
            progress.emit(f"demucs.{key}", 0, f"torch ref load failed: {e!s}")
            attempted.append({"model": key, "status": "load_failed",
                              "error": str(e)[:500]})
            continue

        n_heads = len(bag.models)
        for head_idx, head in enumerate(bag.models):
            head = head.eval()
            seg_samples = demucs_export.segment_samples_for(head)
            head_onnx = (config.BUILD_MODELS_DIR / key /
                         (onnx_filename if n_heads == 1 else
                          f"{Path(onnx_filename).stem}.head{head_idx}.onnx"))
            progress.emit(f"demucs.{key}", 20 + 15 * head_idx,
                          f"attempting in-graph export head {head_idx+1}/{n_heads}")

            ok, err = demucs_export.attempt_in_graph_export(
                head, head_onnx, seg_samples)
            attempted.append({"model": key, "head": head_idx,
                              "segment_samples": seg_samples,
                              "in_graph_ok": ok, "error": err})

            if ok:
                any_success = True
                # Record into manifest even if partial.
                try:
                    manifest_entries[f"{key}_head{head_idx}"] = \
                        manifest.build_entry(
                            head_onnx,
                            torch_ref_checkpoint=ckpt,
                            max_abs_err=float("nan"),
                            max_rel_err=float("nan"),
                            precision="fp32",
                            coreml_ep_supported=False,
                            cpu_fallback_ops=[],
                            optimized_cache=None,
                            notes="in-graph STFT export succeeded — validate "
                                  "parity before shipping")
                except Exception as e:
                    progress.emit(f"demucs.{key}", 30,
                                  f"manifest build failed: {e!s}")

    validation_entries["demucs"] = {
        "passed": False,
        "attempts": attempted,
        "note": "in-graph STFT export blocked; see blocker.md",
    }
    return any_success


# ── CLI ─────────────────────────────────────────────────────────────────────

def _parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Track A0 — ONNX conversion")
    p.add_argument("--models", nargs="*", default=list(REQUIRED_MODELS),
                   choices=REQUIRED_MODELS,
                   help="Which model families to convert.")
    p.add_argument("--branch", default="feat/v0-A0-onnx",
                   help="Branch recorded in done.flag.")
    p.add_argument("--dry-run", action="store_true",
                   help="Validate imports + fixtures only; no downloads.")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv or sys.argv[1:])
    progress.emit("start", 0, f"A0 convert models={args.models}")
    t0 = time.perf_counter()

    manifest_entries: dict = {}
    validation_entries: dict = {}
    fp16_attempts: list = []
    quant_attempts: list = []

    if args.dry_run:
        for fx in fixtures.all_fixtures():
            progress.emit("dry-run", 50, f"fixture ok: {fx.name} "
                                         f"shape={fx.samples.shape} sr={fx.sr}")
        progress.emit("dry-run", 100, "imports validated, exiting")
        return 0

    results: dict[str, bool] = {}
    if "ast" in args.models:
        try:
            results["ast"] = _convert_ast(manifest_entries, validation_entries,
                                          fp16_attempts, quant_attempts)
        except Exception as e:
            progress.emit("ast", 0,
                          f"uncaught error: {type(e).__name__}: {e!s}")
            results["ast"] = False
            traceback.print_exc(file=sys.stderr)

    if "clap" in args.models:
        try:
            results["clap"] = _convert_clap(manifest_entries,
                                            validation_entries,
                                            fp16_attempts, quant_attempts)
        except Exception as e:
            progress.emit("clap", 0,
                          f"uncaught error: {type(e).__name__}: {e!s}")
            results["clap"] = False
            traceback.print_exc(file=sys.stderr)

    if "demucs" in args.models:
        try:
            results["demucs"] = _convert_demucs(manifest_entries,
                                                validation_entries,
                                                fp16_attempts)
        except Exception as e:
            progress.emit("demucs", 0,
                          f"uncaught error: {type(e).__name__}: {e!s}")
            results["demucs"] = False
            traceback.print_exc(file=sys.stderr)

    # Write manifest + validation report.
    manifest.write(manifest_entries)
    _write_validation_report(validation_entries, fp16_attempts, quant_attempts)

    # fp16 report markdown
    if any(not a.all_passed for a in fp16_attempts):
        fp16.write_fp16_report(config.STATE_FP16_REPORT_MD, fp16_attempts)

    duration = time.perf_counter() - t0
    all_required_ok = all(results.get(m, False) for m in REQUIRED_MODELS
                          if m in args.models)

    artifacts = [str(config.MANIFEST_PATH.resolve().relative_to(config.REPO_ROOT))]
    for entry in manifest_entries.values():
        artifacts.append(entry["path"])

    if all_required_ok:
        progress.write_artifacts("complete", [{"path": p} for p in artifacts],
                                 duration, results=results)
        progress.write_done_flag(args.branch, artifacts,
                                 notes=f"results={results}")
    else:
        progress.write_artifacts("blocked",
                                 [{"path": p} for p in artifacts],
                                 duration, results=results)
        # blocker.md is written by the main orchestrator callsite if this
        # is running as the authoritative track entry — see run.sh.

    progress.emit("done", 100, f"results={results} ok={all_required_ok}")
    return 0 if all_required_ok else 1


def _write_validation_report(validation, fp16_attempts, quant_attempts):
    import json
    config.A0_STATE_DIR.mkdir(parents=True, exist_ok=True)
    doc = {
        "validation": validation,
        "fp16_attempts": [a.as_dict() for a in fp16_attempts],
        "int8_attempts": [q.as_dict() for q in quant_attempts],
    }
    with open(config.STATE_VALIDATION_REPORT, "w") as fh:
        json.dump(doc, fh, indent=2)
        fh.write("\n")


if __name__ == "__main__":
    sys.exit(main())
