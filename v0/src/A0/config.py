"""
Static configuration for Track A0.

All path/name/threshold constants live here so `convert.py`, `validate.py`,
and the tests agree on the same values. Keep this module dependency-free
(no torch, no onnx imports) so it is cheap to load from the test suite.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


# ── Repo-relative paths ──────────────────────────────────────────────────────

# `v0/src/A0/config.py` → parents[3] is the repo root.
REPO_ROOT = Path(__file__).resolve().parents[3]

A0_SRC_DIR   = REPO_ROOT / "v0" / "src" / "A0"
A0_STATE_DIR = REPO_ROOT / "v0" / "state" / "A0"
BUILD_MODELS_DIR = REPO_ROOT / "v0" / "build" / "models"

# ORT optimized-graph cache (see PIVOT §E). Per-model subdirs written below it.
ORT_CACHE_DIR = BUILD_MODELS_DIR / "ort_cache"

# Files written to v0/state/A0/
STATE_PROGRESS_NDJSON      = A0_STATE_DIR / "progress.ndjson"
STATE_ARTIFACTS_JSON       = A0_STATE_DIR / "artifacts.json"
STATE_VALIDATION_REPORT    = A0_STATE_DIR / "validation_report.json"
STATE_FP16_REPORT_MD       = A0_STATE_DIR / "fp16_report.md"
STATE_PERF_JSON            = A0_STATE_DIR / "perf.json"
STATE_DONE_FLAG            = A0_STATE_DIR / "done.flag"
STATE_BLOCKER_MD           = A0_STATE_DIR / "blocker.md"

MANIFEST_PATH = BUILD_MODELS_DIR / "manifest.json"


# ── Model registry ───────────────────────────────────────────────────────────

DEMUCS_MODELS = {
    # key                # (torch_ref_checkpoint, onnx_filename, priority,     purpose)
    "htdemucs_ft":  ("htdemucs_ft",  "htdemucs_ft.onnx",  "primary",   "fine-tuned 4-stem"),
    "htdemucs_6s":  ("htdemucs_6s",  "htdemucs_6s.onnx",  "secondary", "6-stem (guitar+piano)"),
    "htdemucs":     ("htdemucs",     "htdemucs.onnx",     "fallback",  "base 4-stem"),
}

CLAP_CHECKPOINT = "laion/clap-htsat-unfused"
CLAP_ONNX_FILENAME = "clap_htsat_unfused.onnx"
CLAP_GENRE_EMBEDDINGS_FILENAME = "clap_genre_embeddings.json"

AST_CHECKPOINT = "MIT/ast-finetuned-audioset-10-10-0.4593"
AST_ONNX_FILENAME = "ast_audioset.onnx"


# ── Parity tolerances ────────────────────────────────────────────────────────
#
# Targets from `v0/tracks/A0-onnx-conversion.md`:
#
#   Demucs: max_abs_err < 1e-3, max_rel_err < 1e-2 on separated waveforms,
#           tested on both a 10s drum loop AND a 30s full mix.
#   CLAP:   cosine similarity ≥ 0.999 on audio-branch embeddings.
#   AST:    top-5 labels identical, max logit diff < 1e-3.
#
# Wider tolerances are acceptable with a listening test; any loosened value
# must be recorded explicitly in `validation_report.json`.

@dataclass(frozen=True)
class ParityTargets:
    demucs_max_abs_err: float = 1.0e-3
    demucs_max_rel_err: float = 1.0e-2
    clap_min_cosine:     float = 0.999
    ast_max_logit_diff:  float = 1.0e-3
    ast_topk_labels:     int   = 5
    fp16_null_rms_dbfs_max: float = -60.0   # stricter = more negative


PARITY = ParityTargets()


# ── Demucs export strategy ───────────────────────────────────────────────────
#
# `htdemucs_ft` is a bag-of-4 fine-tuned models averaged at inference.
# Strategies (in order of preference):
#
#   "fused":  export the whole bag as one graph (preferred by brief).
#   "per_head": export each of the 4 heads as a separate ONNX, average host-side
#               (mandatory fallback if fused graph > 500 MB).
#
# `htdemucs` / `htdemucs_6s` are single models — strategy is always "single".
#
# STFT strategies (Demucs uses STFT internally):
#
#   "native":   rely on `torch.onnx.export(..., opset_version>=17)`' STFT op
#               support. Cleanest graph.
#   "external": do STFT/iSTFT in a Python wrapper outside the ONNX graph;
#               only the learned network goes into ONNX. Ugly but reliable.

DEMUCS_FUSED_SIZE_LIMIT_MB = 500
OPSET_VERSION = 17  # ≥17 required for STFT support in torch.onnx
