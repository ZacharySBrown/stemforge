"""
AST → ONNX (MIT/ast-finetuned-audioset-10-10-0.4593).

This is a standard HuggingFace `AutoModelForAudioClassification`. Optimum
ships a first-class ONNX config for it, so `optimum-cli export onnx` works
off the shelf. We call `main_export` directly to keep everything in-process.

AST input: log-Mel spectrogram at 16 kHz, 1024 frames × 128 mels. The HF
feature extractor produces this from raw audio; at inference time the
C++ host will replicate the feature extraction (Track A concern). For
A0 parity, we compare the *model* end-to-end given an identical feature
tensor.
"""
from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from . import config
from .progress import Timer, emit


AST_LOGIT_DIFF_TOL = config.PARITY.ast_max_logit_diff
AST_TOPK = config.PARITY.ast_topk_labels


def export(dst_dir: Path, checkpoint: str = config.AST_CHECKPOINT,
           opset: int = config.OPSET_VERSION) -> Path:
    """
    Export AST via optimum. Returns the path to the produced .onnx file.

    optimum writes an entire folder (model.onnx + config.json + preprocessor
    files). We extract the .onnx and leave the sidecars alongside it so
    Track A can use the preprocessor_config.json to replicate feature
    extraction.
    """
    from optimum.exporters.onnx import main_export

    dst_dir.mkdir(parents=True, exist_ok=True)
    emit("ast.export", 0, f"exporting {checkpoint} via optimum")
    with Timer("ast.export", model=checkpoint):
        main_export(
            model_name_or_path=checkpoint,
            output=str(dst_dir),
            task="audio-classification",
            opset=opset,
            framework="pt",
            do_validation=False,  # we run our own parity validation.
            do_constant_folding=True,
        )

    onnx_path = dst_dir / "model.onnx"
    if not onnx_path.exists():
        # Some optimum versions write a task-specific filename.
        candidates = list(dst_dir.glob("*.onnx"))
        if not candidates:
            raise FileNotFoundError(f"optimum produced no .onnx in {dst_dir}")
        onnx_path = candidates[0]

    canonical = dst_dir / config.AST_ONNX_FILENAME
    if onnx_path.resolve() != canonical.resolve():
        shutil.copy(onnx_path, canonical)
    emit("ast.export", 100, f"wrote {canonical}")
    return canonical


def _load_torch():
    """Return `(model, feature_extractor)` loaded from HF hub."""
    from transformers import (AutoFeatureExtractor,
                              AutoModelForAudioClassification)
    model = AutoModelForAudioClassification.from_pretrained(
        config.AST_CHECKPOINT).eval()
    fe = AutoFeatureExtractor.from_pretrained(config.AST_CHECKPOINT)
    return model, fe


def _torch_logits(model, fe, audio_16k_mono: np.ndarray) -> np.ndarray:
    """Run AST forward in torch; return logits over all 527 AudioSet classes."""
    import torch
    inputs = fe(audio_16k_mono, sampling_rate=16_000, return_tensors="pt")
    with torch.no_grad():
        out = model(**inputs)
    return out.logits.numpy()[0]


def _ort_logits(session, fe, audio_16k_mono: np.ndarray) -> np.ndarray:
    inputs = fe(audio_16k_mono, sampling_rate=16_000, return_tensors="np")
    feed = {k: v for k, v in inputs.items()
            if k in {i.name for i in session.get_inputs()}}
    if not feed:  # model input name is usually "input_values"
        feed = {session.get_inputs()[0].name: list(inputs.values())[0]}
    out = session.run(None, feed)
    return np.asarray(out[0][0])


@dataclass
class AstParity:
    torch_top5: list[int]
    onnx_top5: list[int]
    labels_match: bool
    max_logit_diff: float
    passed: bool
    fixture: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "torch_top5": self.torch_top5,
            "onnx_top5": self.onnx_top5,
            "labels_match": self.labels_match,
            "max_logit_diff": round(float(self.max_logit_diff), 6),
            "passed": self.passed,
            "fixture": self.fixture,
        }


def validate(onnx_path: Path, audio_16k_mono: np.ndarray, fixture_name: str,
             tolerance: float = AST_LOGIT_DIFF_TOL,
             topk: int = AST_TOPK) -> AstParity:
    """Run torch + onnx forward, compare top-k and logit residual."""
    import onnxruntime as ort
    model, fe = _load_torch()
    session = ort.InferenceSession(str(onnx_path),
                                   providers=["CPUExecutionProvider"])
    with Timer("ast.validate.torch"):
        torch_logits = _torch_logits(model, fe, audio_16k_mono)
    with Timer("ast.validate.onnx"):
        onnx_logits = _ort_logits(session, fe, audio_16k_mono)

    torch_top = list(map(int, np.argsort(-torch_logits)[:topk]))
    onnx_top = list(map(int, np.argsort(-onnx_logits)[:topk]))
    max_diff = float(np.max(np.abs(torch_logits - onnx_logits)))
    return AstParity(
        torch_top5=torch_top,
        onnx_top5=onnx_top,
        labels_match=(torch_top == onnx_top),
        max_logit_diff=max_diff,
        passed=(torch_top == onnx_top) and (max_diff <= tolerance),
        fixture=fixture_name,
    )
