"""
CLAP → ONNX (laion/clap-htsat-unfused), audio branch only.

StemForge only needs the audio-encoder + projection for genre detection.
The text branch embeddings for the 13 genre prompts can be pre-baked into
a JSON sidecar (`clap_genre_embeddings.json`). At inference time the C++
host computes audio embedding → dot-product with the precomputed text
embeddings → softmax → top-1 genre.

Parity target: cosine similarity ≥ 0.999 between torch and ONNX audio
embeddings on the full GENRE_LABELS eval set.
"""
from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from . import config
from .progress import Timer, emit


# Keep this list in sync with `stemforge/analyzer.py:GENRE_LABELS`.
# Duplicated here so the A0 module is self-contained per SHARED.md
# (A0 must not import from stemforge/ since B is restructuring it).
GENRE_LABELS = [
    "electronic dance music",
    "hip hop",
    "rock",
    "jazz",
    "acoustic folk",
    "pop",
    "orchestral classical",
    "r&b soul",
    "metal",
    "ambient",
    "latin",
    "country",
    "reggae",
]


def export(dst_dir: Path, checkpoint: str = config.CLAP_CHECKPOINT,
           opset: int = config.OPSET_VERSION) -> Path:
    """
    Export CLAP audio-branch directly via `torch.onnx.export`.

    Optimum 0.1 does not yet include a CLAP ONNX config — attempting
    `main_export(task="feature-extraction")` raises
    `ValueError: Trying to export a clap model, that is a custom or
    unsupported architecture`. We side-step optimum and wrap the
    `get_audio_features` call in a tiny nn.Module. The text branch
    embeddings for the 13 genre prompts are baked separately via
    `bake_genre_embeddings()` so the exported graph stays audio-only.
    """
    import torch
    import torch.nn as nn
    from transformers import ClapModel, ClapProcessor

    class _ClapAudioBranch(nn.Module):
        def __init__(self, clap: ClapModel) -> None:
            super().__init__()
            self.clap = clap

        def forward(self, input_features, is_longer):   # type: ignore[no-untyped-def]
            return self.clap.get_audio_features(
                input_features=input_features,
                is_longer=is_longer,
            )

    dst_dir.mkdir(parents=True, exist_ok=True)
    emit("clap.export", 5, f"loading {checkpoint}")
    model = ClapModel.from_pretrained(checkpoint).eval()
    processor = ClapProcessor.from_pretrained(checkpoint)

    # Build a representative dummy input so torch.jit can trace shapes.
    rng = np.random.default_rng(0)
    dummy = rng.standard_normal(48_000 * 10).astype(np.float32) * 0.05
    pp = processor(audios=dummy, sampling_rate=48_000, return_tensors="pt")

    wrapper = _ClapAudioBranch(model).eval()
    canonical = dst_dir / config.CLAP_ONNX_FILENAME

    emit("clap.export", 40, "torch.onnx.export — audio branch only")
    with Timer("clap.export", model=checkpoint):
        torch.onnx.export(
            wrapper,
            (pp["input_features"], pp["is_longer"]),
            str(canonical),
            input_names=["input_features", "is_longer"],
            output_names=["audio_embed"],
            dynamic_axes={"input_features": {0: "batch"},
                          "is_longer":      {0: "batch"}},
            opset_version=opset,
            do_constant_folding=True,
            dynamo=False,
        )
    emit("clap.export", 100, f"wrote {canonical}")
    return canonical


def bake_genre_embeddings(dst_path: Path) -> Path:
    """
    Compute fp32 text embeddings for the genre prompts (torch reference)
    and persist to JSON so the C++ host can skip the text branch entirely.
    """
    from transformers import ClapModel, ClapProcessor
    import torch

    model = ClapModel.from_pretrained(config.CLAP_CHECKPOINT).eval()
    processor = ClapProcessor.from_pretrained(config.CLAP_CHECKPOINT)

    prompts = [f"This is {g} music." for g in GENRE_LABELS]
    emit("clap.bake", 0, f"computing text embeddings for {len(prompts)} prompts")
    inputs = processor(text=prompts, return_tensors="pt", padding=True)
    with torch.no_grad():
        feats = model.get_text_features(**inputs)
    # L2-normalize for cosine-similarity comparison downstream.
    feats = feats / feats.norm(dim=-1, keepdim=True).clamp_min(1e-12)
    arr = feats.cpu().numpy().astype(np.float32)

    doc = {
        "checkpoint": config.CLAP_CHECKPOINT,
        "labels": GENRE_LABELS,
        "prompts": prompts,
        "dim": int(arr.shape[1]),
        "embeddings": arr.tolist(),
        "normalized": True,
    }
    dst_path.parent.mkdir(parents=True, exist_ok=True)
    with open(dst_path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2)
    emit("clap.bake", 100, f"wrote {dst_path}")
    return dst_path


def _torch_audio_embedding(model, processor, audio_48k_mono: np.ndarray
                           ) -> np.ndarray:
    import torch
    inputs = processor(audios=audio_48k_mono, sampling_rate=48_000,
                       return_tensors="pt")
    with torch.no_grad():
        feat = model.get_audio_features(**inputs)
    feat = feat / feat.norm(dim=-1, keepdim=True).clamp_min(1e-12)
    return feat.numpy()[0]


def _ort_audio_embedding(session, processor, audio_48k_mono: np.ndarray
                         ) -> np.ndarray:
    # Processor in NumPy mode returns `input_features` as float32 and
    # `is_longer` as bool; ORT session wants them verbatim.
    inputs = processor(audios=audio_48k_mono, sampling_rate=48_000,
                       return_tensors="np")
    wanted = {i.name for i in session.get_inputs()}
    feed = {k: np.asarray(v) for k, v in inputs.items() if k in wanted}
    out = session.run(None, feed)
    emb = np.asarray(out[0])
    if emb.ndim > 1:
        emb = emb[0]
    norm = float(np.linalg.norm(emb))
    if norm > 0:
        emb = emb / norm
    return emb.astype(np.float32)


@dataclass
class ClapParity:
    fixture: str
    cosine: float
    passed: bool

    def as_dict(self) -> dict[str, Any]:
        return {"fixture": self.fixture,
                "cosine": round(self.cosine, 6),
                "passed": self.passed}


def validate(onnx_path: Path, audio_48k_mono: np.ndarray, fixture_name: str,
             min_cosine: float = config.PARITY.clap_min_cosine) -> ClapParity:
    """
    Compare torch vs ONNX audio embeddings on identical preprocessor output.

    The CLAP feature extractor does random sub-clip selection when the input
    is longer than 10 s (its `is_longer` path). To get deterministic parity
    we (1) seed torch's RNG before running the processor, and (2) share the
    exact `input_features` / `is_longer` tensors between the torch reference
    and the ONNX session. This isolates the ONNX graph's numerics from any
    processor-level stochasticity.
    """
    import torch
    import onnxruntime as ort
    from transformers import ClapModel, ClapProcessor

    model = ClapModel.from_pretrained(config.CLAP_CHECKPOINT).eval()
    processor = ClapProcessor.from_pretrained(config.CLAP_CHECKPOINT)
    session = ort.InferenceSession(str(onnx_path),
                                   providers=["CPUExecutionProvider"])

    # Seed before the processor runs so repeated validations are deterministic.
    torch.manual_seed(0)
    np.random.seed(0)
    pp = processor(audios=audio_48k_mono, sampling_rate=48_000,
                   return_tensors="pt")

    with Timer("clap.validate.torch"):
        with torch.no_grad():
            torch_emb = model.get_audio_features(
                input_features=pp["input_features"],
                is_longer=pp["is_longer"],
            ).numpy()[0]
    torch_emb = torch_emb / (np.linalg.norm(torch_emb) + 1e-12)

    with Timer("clap.validate.onnx"):
        feed = {i.name: np.asarray(pp[i.name].numpy()
                                   if hasattr(pp[i.name], "numpy")
                                   else pp[i.name])
                for i in session.get_inputs()}
        onnx_emb = np.asarray(session.run(None, feed)[0])
    if onnx_emb.ndim > 1:
        onnx_emb = onnx_emb[0]
    onnx_emb = onnx_emb / (np.linalg.norm(onnx_emb) + 1e-12)

    cos = float(np.dot(torch_emb, onnx_emb))
    return ClapParity(fixture=fixture_name, cosine=cos,
                      passed=cos >= min_cosine)
