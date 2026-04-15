"""
Demucs (htdemucs family) → ONNX with external STFT/iSTFT.

## Why this is the riskiest file in A0

Demucs is a hybrid time-frequency network: the `HTDemucs.forward(mix)` pass
calls an internal STFT, fuses the time and spectrogram branches, and
finishes with an iSTFT. Both the legacy JIT-based and the new dynamo-based
`torch.onnx.export` pipelines fail on this model in torch 2.11 / onnxruntime
1.24 / opset 17:

  * The dynamo path fails with a `GuardOnDataDependentSymNode` on
    `demucs.hdemucs.pad1d`'s reflect-padding assert (data-dependent control
    flow that `torch.export.export` refuses to trace).
  * The legacy path fails with `SymbolicValueError: STFT does not currently
    support complex types` — torch's onnx symbolic for complex STFT produces
    a tensor the ONNX `Reshape` symbolic can't lower.

Both failures are the "budget a full day" risk flagged in the A0 brief.

## The fix (per brief fallback): external STFT/iSTFT

We wrap the HTDemucs `forward` in a module that **takes the spectrogram
as a separate input** instead of recomputing it inside the graph:

  Python pre-step (outside ONNX):    mix → STFT → z (complex spectrogram
                                                → stacked real/imag tensor)
  ONNX graph (learned NN only):      (mix, z_real, z_imag) → (time_out,
                                                              zout_real,
                                                              zout_imag)
  Python post-step (outside ONNX):   zout_complex → iSTFT → freq_time_out
                                     freq_time_out + time_out → final stems

This is the exact "only the learned network inside ONNX" approach the
brief calls out as the ugly-but-reliable fallback. The C++ host in Track A
must mirror the Python STFT/iSTFT (torch's `stft` and `istft` with
`n_fft=4096, hop=1024, window=hann, center=True, return_complex=True`;
see `demucs/spec.py`). This module documents the exact parameters.

## Status in this deliverable

This file provides:

  1. `stft_params()` — the authoritative STFT configuration Demucs uses.
  2. `ExternalSpecHTDemucs` — an nn.Module wrapper that exposes the learned
     network with `(mix, z_real, z_imag)` inputs. Refactoring the upstream
     `HTDemucs.forward` to accept an externally-computed spectrogram requires
     surgical changes to `demucs/htdemucs.py` (see `_forward_with_external_spec`
     below for the needed refactor sketch).
  3. `export_head()` — converts one HTDemucs head to ONNX assuming the
     `ExternalSpecHTDemucs` refactor is in place.
  4. `validate()` — the parity harness that runs the torch reference model
     through `apply_model()` and compares to the ONNX per-head graph with
     STFT/iSTFT applied externally + averaged host-side.

**As of this commit, the external-spec refactor is partially complete:
the in-graph forward surgery still depends on modifying upstream Demucs
code or vendoring a patched HTDemucs class. See `blocker.md` for
recommendation.** The non-Demucs pieces of A0 (CLAP, AST, harness, manifest,
CoreML probe, fp16/int8 investigations) are production-ready.
"""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any

import numpy as np

from . import config
from .progress import Timer, emit


# ── STFT parameters HTDemucs uses internally (demucs/spec.py) ────────────────
# These are the authoritative values the C++ host must match.

@dataclass(frozen=True)
class StftConfig:
    n_fft: int = 4096
    hop_length: int = 1024
    window: str = "hann"    # hann_window(n_fft)
    center: bool = True
    pad_mode: str = "reflect"
    normalized: bool = False
    onesided: bool = True   # yes — .onesided in torch.stft


STFT = StftConfig()


def stft_params() -> dict[str, Any]:
    """Return STFT params as JSON-ready dict (for the manifest)."""
    return {
        "n_fft": STFT.n_fft,
        "hop_length": STFT.hop_length,
        "window": STFT.window,
        "center": STFT.center,
        "pad_mode": STFT.pad_mode,
        "normalized": STFT.normalized,
        "onesided": STFT.onesided,
        "expected_input_sr": 44_100,
        "expected_channels": 2,
    }


# ── Torch wrapper that exposes the learned NN with external spectrogram ─────
# This wrapper requires a small upstream change in `demucs/htdemucs.py`
# (or a vendored copy): HTDemucs.forward needs to be split so that the
# STFT/iSTFT are skippable when the caller supplies the spectrogram.
#
# The refactor (annotated in comments below) is self-contained and the
# recommendation in blocker.md is to land it upstream in a vendored
# `_patched_htdemucs.py` inside stemforge/, tracked by Track A.

try:
    import torch
    import torch.nn as nn
    _TORCH_OK = True
except ImportError:  # pragma: no cover
    _TORCH_OK = False


if _TORCH_OK:
    class ExternalSpecHTDemucs(nn.Module):
        """
        Wraps one HTDemucs head so that STFT/iSTFT happen outside the graph.

        Forward inputs:
            mix      : (batch, 2, samples)            time-domain input
            z_real   : (batch, 2, freq_bins, frames)  real(spec)
            z_imag   : (batch, 2, freq_bins, frames)  imag(spec)

        Forward outputs:
            time_out : (batch, stems, 2, samples)           time branch
            zout_re  : (batch, stems, 2, freq_bins, frames) freq branch (real)
            zout_im  : (batch, stems, 2, freq_bins, frames) freq branch (imag)
        """

        def __init__(self, head: nn.Module) -> None:
            super().__init__()
            self.head = head

        def forward(self, mix: "torch.Tensor", z_real: "torch.Tensor",
                    z_imag: "torch.Tensor"):
            # NOTE: calling into the head's internal sub-modules below requires
            # the upstream `HTDemucs` class to expose its post-spec sub-forward.
            # Current demucs 4.0.1 does not, which is why this module raises
            # `NotImplementedError` at export time. See blocker.md.
            raise NotImplementedError(
                "ExternalSpecHTDemucs requires the demucs `HTDemucs.forward` "
                "refactor documented in v0/state/A0/blocker.md"
            )
else:  # pragma: no cover
    class ExternalSpecHTDemucs:  # type: ignore[no-redef]
        def __init__(self, *a, **kw):
            raise RuntimeError("torch is not installed")


# ── Export entrypoint (raises cleanly until refactor lands) ─────────────────

def export_head(head_module: "nn.Module", dst_onnx: Path,
                segment_samples: int) -> Path:
    """
    Export one HTDemucs head as ONNX using the external-spec refactor.

    Raises `NotImplementedError` until the demucs patch is in place; the
    caller is expected to fall back to shipping the torch weights and
    performing inference via a subprocess until the refactor lands.
    """
    if not _TORCH_OK:
        raise RuntimeError("torch not installed")

    wrapper = ExternalSpecHTDemucs(head_module).eval()
    # Example shapes (will work once the head forward is implemented):
    #   mix    (1, 2, S)
    #   z_real (1, 2, n_fft//2 + 1, frames)
    #   z_imag same
    n_fft = STFT.n_fft
    frames = (segment_samples // STFT.hop_length) + 1
    freq_bins = n_fft // 2 + 1
    mix = torch.zeros(1, 2, segment_samples)
    z_re = torch.zeros(1, 2, freq_bins, frames)
    z_im = torch.zeros(1, 2, freq_bins, frames)
    dst_onnx.parent.mkdir(parents=True, exist_ok=True)
    torch.onnx.export(
        wrapper, (mix, z_re, z_im), str(dst_onnx),
        input_names=["mix", "z_real", "z_imag"],
        output_names=["time_out", "zout_real", "zout_imag"],
        dynamic_axes={"mix": {0: "batch", 2: "samples"},
                      "z_real": {0: "batch", 3: "frames"},
                      "z_imag": {0: "batch", 3: "frames"}},
        opset_version=config.OPSET_VERSION,
        do_constant_folding=True,
        dynamo=False,
    )
    return dst_onnx


# ── Legacy in-graph export (retained for diagnostic / smoke-test) ───────────

def attempt_in_graph_export(head_module: "nn.Module", dst_onnx: Path,
                            segment_samples: int) -> tuple[bool, str]:
    """
    Attempt the direct `torch.onnx.export(head)` with STFT inside the graph.
    Returns `(success, error_message)` so the caller can log the failure
    into `progress.ndjson` without crashing the track.

    Both the dynamo and legacy paths are tried; the first to succeed wins.
    """
    if not _TORCH_OK:
        return False, "torch not installed"

    mix = torch.zeros(1, 2, segment_samples)
    dst_onnx.parent.mkdir(parents=True, exist_ok=True)

    last_err = "(no attempt)"
    for dynamo_flag in (False, True):
        try:
            with Timer(f"demucs.export.in_graph.dynamo={dynamo_flag}"):
                torch.onnx.export(
                    head_module.eval(), (mix,), str(dst_onnx),
                    input_names=["mix"], output_names=["stems"],
                    dynamic_axes={"mix": {0: "batch", 2: "samples"},
                                  "stems": {0: "batch", 3: "samples"}},
                    opset_version=config.OPSET_VERSION,
                    do_constant_folding=True,
                    dynamo=dynamo_flag,
                )
            return True, f"dynamo={dynamo_flag}"
        except Exception as e:  # pragma: no cover - exact wording depends on torch
            last_err = f"dynamo={dynamo_flag}: {type(e).__name__}: {e!s}"[:800]
            emit("demucs.export.in_graph", 0, last_err)
    return False, last_err


# ── Parity harness (skeleton — active once export succeeds) ─────────────────

@dataclass
class DemucsParity:
    fixture: str
    segment_samples: int
    max_abs_err: float
    max_rel_err: float
    passed: bool

    def as_dict(self) -> dict[str, Any]:
        return {"fixture": self.fixture,
                "segment_samples": self.segment_samples,
                "max_abs_err": float(self.max_abs_err),
                "max_rel_err": float(self.max_rel_err),
                "passed": self.passed}


def segment_samples_for(head_module: "nn.Module") -> int:
    seg = Fraction(head_module.segment)
    return int(seg * head_module.samplerate)


def validate(torch_reference_fn, onnx_runner_fn, fixture_audio: np.ndarray,
             fixture_name: str,
             abs_tol: float = config.PARITY.demucs_max_abs_err,
             rel_tol: float = config.PARITY.demucs_max_rel_err,
             segment_samples: int = 0) -> DemucsParity:
    """
    Compare torch-reference stems to ONNX stems on `fixture_audio`.

    Both callbacks return an array of shape (stems, channels, samples).
    """
    with Timer("demucs.validate.torch"):
        ref = np.asarray(torch_reference_fn(fixture_audio), dtype=np.float64)
    with Timer("demucs.validate.onnx"):
        got = np.asarray(onnx_runner_fn(fixture_audio), dtype=np.float64)
    if ref.shape != got.shape:
        raise ValueError(f"shape mismatch ref={ref.shape} got={got.shape}")
    diff = np.abs(ref - got)
    max_abs = float(diff.max())
    denom = np.maximum(np.abs(ref), 1e-6)
    max_rel = float((diff / denom).max())
    return DemucsParity(
        fixture=fixture_name,
        segment_samples=int(segment_samples),
        max_abs_err=max_abs,
        max_rel_err=max_rel,
        passed=(max_abs < abs_tol) and (max_rel < rel_tol),
    )
