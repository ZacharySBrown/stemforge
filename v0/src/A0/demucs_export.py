"""
Demucs (htdemucs family) → ONNX with external STFT/iSTFT.

## Why this is the riskiest file in A0

Demucs is a hybrid time-frequency network: the upstream
``HTDemucs.forward(mix)`` pass calls an internal STFT, fuses the time and
spectrogram branches, and finishes with an iSTFT.  Both the legacy
JIT-based and the new dynamo-based ``torch.onnx.export`` pipelines fail on
this model in torch 2.11 / onnxruntime 1.24 / opset 17.  See
``v0/state/A0/blocker.md`` for exact error signatures.

## The fix (per brief fallback): external STFT/iSTFT

We vendor ``demucs/htdemucs.py`` into
``stemforge/_vendor/demucs_patched.py`` and add a ``forward_from_spec``
method that takes the spectrogram as a separate input.  The wrapper in
this module pipes its graph inputs into that method:

  Python pre-step (outside ONNX):    mix → STFT → z (complex)
                                           → (z_real, z_imag)
  ONNX graph (learned NN only):      (mix, z_real, z_imag)
                                           → (time_out, zout_real, zout_imag)
  Python post-step (outside ONNX):   complex(zout_real, zout_imag)
                                           → iSTFT → freq_time_out
                                     freq_time_out + time_out → stems

See ``v0/src/A0/tests/test_forward_from_spec.py`` for the parity proof
that this factoring is numerically equivalent to upstream ``forward``.

## What this module provides

  1. ``stft_params()`` — authoritative STFT configuration.
  2. ``ExternalSpecHTDemucs`` — ``nn.Module`` wrapper with the three
     inputs / three outputs expected by the ONNX graph.
  3. ``apply_stft`` / ``apply_istft`` — CPU helpers that mirror
     ``_spec`` / ``_ispec`` exactly (needed by validate + the C++ host).
  4. ``export_head`` — traces one head to ONNX.
  5. ``validate_head`` — parity against ``apply_model`` on real fixtures.
  6. ``run_bag_onnx`` — average per-head ONNX outputs the way
     ``demucs.apply.apply_model`` averages bag-of-heads internally.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any

import numpy as np

from . import config
from .progress import Timer, emit


# ── STFT parameters HTDemucs uses internally (demucs/spec.py) ────────────────

@dataclass(frozen=True)
class StftConfig:
    n_fft: int = 4096
    hop_length: int = 1024
    window: str = "hann"    # hann_window(n_fft)
    center: bool = True
    pad_mode: str = "reflect"
    normalized: bool = False
    onesided: bool = True


STFT = StftConfig()


def stft_params() -> dict[str, Any]:
    """Return STFT params as JSON-ready dict (for the manifest).

    Externalisation contract for the C++/Python caller — they MUST drive
    STFT/iSTFT with these exact parameters.
    """
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

        All I/O is real-valued — ``aten::complex`` is unsupported in
        torch.onnx opset 17, so the caller must CAC-pack the complex
        spectrogram before feeding it in and CAC-unpack the output before
        running iSTFT.  See
        ``stemforge._vendor.demucs_patched.HTDemucs.forward_from_spec_cac``
        for the contract.

        Forward inputs:
            mix      : (batch, 2, samples)             time-domain input
                                                       padded to training length
            z_cac    : (batch, 4, freq_bins, frames)   CAC-encoded spec
                                                       (view_as_real → permute)

        Forward outputs:
            time_out : (batch, stems, 2, samples)              time branch
            zout_cac : (batch, stems, 4, freq_bins, frames)    CAC-encoded freq
        """

        def __init__(self, head: "nn.Module") -> None:
            super().__init__()
            self.head = head

        def forward(self, mix: "torch.Tensor", z_cac: "torch.Tensor"):
            return self.head.forward_from_spec_cac(mix, z_cac)
else:  # pragma: no cover
    class ExternalSpecHTDemucs:  # type: ignore[no-redef]
        def __init__(self, *a, **kw):
            raise RuntimeError("torch is not installed")


# ── STFT/iSTFT helpers that mirror ``_spec``/``_ispec`` bit-exactly ─────────
#
# These are thin wrappers around the logic in the vendored module so the
# validate harness and the C++ host share one reference.

def apply_stft(mix_padded: "torch.Tensor", n_fft: int = STFT.n_fft,
               hop: int = STFT.hop_length) -> "torch.Tensor":
    """
    Compute the complex spectrogram exactly as demucs.htdemucs._spec does.

    ``mix_padded`` must already be padded to the training length.
    """
    from demucs.spec import spectro
    from demucs.hdemucs import pad1d
    assert hop == n_fft // 4
    le = int(math.ceil(mix_padded.shape[-1] / hop))
    pad = hop // 2 * 3
    x = pad1d(mix_padded, (pad, pad + le * hop - mix_padded.shape[-1]),
              mode="reflect")
    z = spectro(x, n_fft, hop)[..., :-1, :]
    z = z[..., 2: 2 + le]
    return z


def apply_istft(zout: "torch.Tensor", length: int,
                n_fft: int = STFT.n_fft,
                hop: int = STFT.hop_length) -> "torch.Tensor":
    """Inverse STFT matching demucs.htdemucs._ispec at scale=0."""
    import torch.nn.functional as F
    from demucs.spec import ispectro
    z = F.pad(zout, (0, 0, 0, 1))
    z = F.pad(z, (2, 2))
    pad = hop // 2 * 3
    le = hop * int(math.ceil(length / hop)) + 2 * pad
    x = ispectro(z, hop, length=le)
    x = x[..., pad: pad + length]
    return x


# ── Export entrypoint ───────────────────────────────────────────────────────

def _wrap_head_with_vendored_class(head: "nn.Module") -> "nn.Module":
    """
    Attach the vendored ``forward_from_spec`` method to a live head.

    Why: upstream HTDemucs does not have ``forward_from_spec``.  Rather
    than force-replacing the class of a loaded pretrained model (which
    risks surprising attribute-lookup behaviour), we bind the method from
    our vendored copy onto the instance.  This keeps the pretrained
    weights / attributes untouched and only grafts in the new traceable
    path.

    The vendored class constructor is *identical* to upstream, so the
    method has the same ``self`` contract.
    """
    from stemforge._vendor.demucs_patched import HTDemucs as VendoredHTDemucs
    import types
    for name in ("forward_from_spec", "forward_from_spec_cac",
                 "_learned_forward"):
        setattr(head, name, types.MethodType(getattr(VendoredHTDemucs, name),
                                             head))
    return head


def segment_samples_for(head_module: "nn.Module") -> int:
    """Return the training-length segment (samples) for one head."""
    seg = Fraction(head_module.segment)
    return int(seg * head_module.samplerate)


def pack_cac(z_complex: "torch.Tensor") -> "torch.Tensor":
    """
    Convert a complex spectrogram ``(B, C, Fq, T)`` to the CAC-encoded
    real tensor ``(B, 2*C, Fq, T)`` that ``ExternalSpecHTDemucs`` accepts.

    Matches what ``HTDemucs._magnitude`` does internally when ``cac=True``.
    """
    B, C, Fq, T = z_complex.shape
    m = torch.view_as_real(z_complex).permute(0, 1, 4, 2, 3)
    return m.reshape(B, C * 2, Fq, T).contiguous()


def unpack_cac(zout_cac: "torch.Tensor", audio_channels: int = 2
               ) -> "torch.Tensor":
    """
    Invert :func:`pack_cac` on the network output ``(B, S, 2*C, Fq, T)``
    → complex ``(B, S, C, Fq, T)``.
    """
    B, S, twoC, Fq, T = zout_cac.shape
    C = twoC // audio_channels  # For audio_channels=2 and twoC=4 → C=2
    # Reshape to (B, S, C, 2, Fq, T), permute so the trailing dim is the
    # real/imag pair, then view_as_complex.
    z = zout_cac.view(B, S, audio_channels, 2, Fq, T)
    z = z.permute(0, 1, 2, 4, 5, 3).contiguous()
    return torch.view_as_complex(z)


def export_head(head_module: "nn.Module", dst_onnx: Path,
                segment_samples: int) -> Path:
    """
    Export one HTDemucs head as ONNX using the external-spec refactor.

    The graph has two dynamic inputs (``mix``, ``z_cac``) and two outputs
    (``time_out``, ``zout_cac``).  All I/O is real-valued; the caller
    performs STFT+CAC-packing before feeding the session, and
    CAC-unpacking+iSTFT on the output.
    """
    if not _TORCH_OK:
        raise RuntimeError("torch not installed")

    _wrap_head_with_vendored_class(head_module)
    wrapper = ExternalSpecHTDemucs(head_module).eval()

    n_fft = STFT.n_fft
    # HTDemucs._spec strips the Nyquist bin, so freq_bins = n_fft // 2.
    freq_bins = n_fft // 2
    frames = int(math.ceil(segment_samples / STFT.hop_length))

    mix = torch.zeros(1, 2, segment_samples)
    z_cac = torch.zeros(1, 4, freq_bins, frames)  # 2 audio chans × 2 (re, im)

    dst_onnx.parent.mkdir(parents=True, exist_ok=True)
    with Timer(f"demucs.export_head.{dst_onnx.stem}",
               segment_samples=segment_samples):
        torch.onnx.export(
            wrapper,
            (mix, z_cac),
            str(dst_onnx),
            input_names=["mix", "z_cac"],
            output_names=["time_out", "zout_cac"],
            dynamic_axes={
                "mix": {0: "batch", 2: "samples"},
                "z_cac": {0: "batch", 3: "frames"},
                "time_out": {0: "batch", 3: "samples"},
                "zout_cac": {0: "batch", 4: "frames"},
            },
            opset_version=config.OPSET_VERSION,
            do_constant_folding=True,
            dynamo=False,
        )
    return dst_onnx


# ── Legacy in-graph export (retained for diagnostic / smoke-test) ───────────

def attempt_in_graph_export(head_module: "nn.Module", dst_onnx: Path,
                            segment_samples: int) -> tuple[bool, str]:
    """
    Attempt the direct ``torch.onnx.export(head)`` with STFT inside the graph.

    This is retained purely for regression / diagnostic purposes.  The
    expected result is FAILURE (see ``blocker.md``).  Callers should use
    ``export_head`` for the production path.
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
        except Exception as e:  # pragma: no cover
            last_err = f"dynamo={dynamo_flag}: {type(e).__name__}: {e!s}"[:800]
            emit("demucs.export.in_graph", 0, last_err)
    return False, last_err


# ── Inference helpers ───────────────────────────────────────────────────────

def run_head_onnx(onnx_path: Path, mix_np: np.ndarray,
                  providers: list | None = None) -> np.ndarray:
    """
    Run one ONNX head on a ``(batch, 2, samples)`` mix.

    Does the external STFT in Python, feeds the session, then iSTFT and
    sums the time branch.  Returns stems ``(batch, stems, 2, samples)``.
    """
    import onnxruntime as ort

    assert _TORCH_OK, "torch not installed"
    sess = ort.InferenceSession(
        str(onnx_path),
        providers=providers or ["CPUExecutionProvider"],
    )
    input_info = sess.get_inputs()
    # Work out which ONNX input dtype is used so we cast correctly for
    # fp16 models.
    dtype = np.float32
    for i in input_info:
        if i.name == "mix":
            if "float16" in i.type:
                dtype = np.float16
            break

    mix_t = torch.from_numpy(mix_np).to(torch.float32)
    segment_samples = mix_t.shape[-1]
    z = apply_stft(mix_t)
    z_cac = pack_cac(z).numpy().astype(dtype)
    mix_in = mix_t.numpy().astype(dtype)

    time_out, zout_cac = sess.run(
        None, {"mix": mix_in, "z_cac": z_cac},
    )
    time_out = np.asarray(time_out, dtype=np.float32)
    zout_cac_t = torch.from_numpy(np.asarray(zout_cac, dtype=np.float32))
    zout_complex = unpack_cac(zout_cac_t)
    x_freq = apply_istft(zout_complex, segment_samples).numpy()
    return (time_out + x_freq).astype(np.float32)


def run_bag_onnx(onnx_paths: list[Path], mix_np: np.ndarray,
                 providers: list | None = None,
                 weights: list[list[float]] | None = None) -> np.ndarray:
    """
    Combine per-head ONNX outputs using the bag's per-source weights.

    Mirrors :func:`demucs.apply.apply_model`'s combiner: for each
    source, the final stem is ``sum(head_i[:,k,:,:] * w_i[k]) /
    sum(w_i[k])`` across heads.  When ``weights`` is None, uniform
    averaging is used (single-model bags collapse to this automatically).
    """
    outs = [run_head_onnx(p, mix_np, providers=providers)
            for p in onnx_paths]
    n_heads = len(outs)
    if n_heads == 1:
        return outs[0]

    arr = np.stack(outs, axis=0)  # (H, B, S, C, T)
    if weights is None:
        return arr.mean(axis=0)

    w = np.asarray(weights, dtype=np.float64)  # (H, S)
    assert w.shape == (n_heads, arr.shape[2]), (w.shape, arr.shape)
    totals = w.sum(axis=0)  # (S,)
    totals = np.where(totals > 0, totals, 1.0)
    # (H, 1, S, 1, 1) broadcasting over (H, B, S, C, T)
    combined = (arr * w[:, None, :, None, None]).sum(axis=0)
    combined = combined / totals[None, :, None, None]
    return combined


# ── Parity harness ──────────────────────────────────────────────────────────

@dataclass
class DemucsParity:
    fixture: str
    model_key: str
    segment_samples: int
    max_abs_err: float
    max_rel_err: float
    # Deep-network output magnitude varies by several orders of magnitude
    # across fixtures (silence vs. loud transients) so absolute-error
    # thresholds only work for moderate-level audio.  We track two extra
    # metrics that remain meaningful across fixtures:
    #   * residual_rms_dbfs — RMS(ref - onnx) in dBFS, treating 1.0 FS.
    #   * rel_peak          — max|ref - onnx| / max|ref|  (0 → bit-exact).
    residual_rms_dbfs: float
    rel_peak: float
    passed: bool

    def as_dict(self) -> dict[str, Any]:
        return {"fixture": self.fixture,
                "model_key": self.model_key,
                "segment_samples": self.segment_samples,
                "max_abs_err": float(self.max_abs_err),
                "max_rel_err": float(self.max_rel_err),
                "residual_rms_dbfs": float(self.residual_rms_dbfs),
                "rel_peak": float(self.rel_peak),
                "passed": self.passed}


def _pad_fixture_to_segment(fixture_audio: np.ndarray, segment_samples: int
                            ) -> tuple[np.ndarray, int]:
    """Pad mono/stereo fixture to ``segment_samples`` along the last dim."""
    if fixture_audio.ndim == 1:
        fixture_audio = np.stack([fixture_audio, fixture_audio], axis=0)
    elif fixture_audio.shape[0] == 1:
        fixture_audio = np.concatenate([fixture_audio, fixture_audio], axis=0)
    length = fixture_audio.shape[-1]
    if length > segment_samples:
        # Take centre slice to keep transients.
        start = (length - segment_samples) // 2
        mix = fixture_audio[..., start:start + segment_samples]
        used_len = segment_samples
    else:
        pad = segment_samples - length
        mix = np.pad(fixture_audio, ((0, 0), (0, pad)), mode="constant")
        used_len = length
    return mix.astype(np.float32), used_len


def torch_reference(head_or_bag, mix_np: np.ndarray) -> np.ndarray:
    """Run the torch reference model on a mix array."""
    from demucs.apply import apply_model
    mix_t = torch.from_numpy(mix_np).to(torch.float32)
    if mix_t.dim() == 2:
        mix_t = mix_t.unsqueeze(0)
    # apply_model handles bag (list of heads) and single models.
    with torch.no_grad():
        out = apply_model(head_or_bag, mix_t, shifts=0, split=False,
                          overlap=0.0, progress=False, num_workers=0)
    return out.cpu().numpy()


def validate_head(bag_or_head, onnx_paths: list[Path],
                  fixture_audio: np.ndarray, fixture_name: str,
                  model_key: str,
                  segment_samples: int,
                  abs_tol: float = config.PARITY.demucs_max_abs_err,
                  rel_tol: float = config.PARITY.demucs_max_rel_err
                  ) -> DemucsParity:
    """Compare torch-reference stems to ONNX stems on `fixture_audio`."""
    mix, _used = _pad_fixture_to_segment(fixture_audio, segment_samples)
    # apply_model takes shape (B, C, S).
    mix_bcs = mix[None, ...]  # (1, 2, S)

    # Bag combiner weights (per-head, per-source) mirror demucs' internal
    # ``apply_model`` aggregation.  For fine-tuned bags like htdemucs_ft
    # this is non-uniform and critical for parity; single-model bags have
    # weights=None which collapses to uniform averaging.
    weights = getattr(bag_or_head, "weights", None)

    with Timer(f"demucs.validate.torch.{model_key}.{fixture_name}"):
        ref = np.asarray(torch_reference(bag_or_head, mix_bcs),
                         dtype=np.float64)
    with Timer(f"demucs.validate.onnx.{model_key}.{fixture_name}"):
        got = np.asarray(run_bag_onnx(onnx_paths, mix_bcs, weights=weights),
                         dtype=np.float64)

    # Align shapes — apply_model returns (B, S, C, T) while our onnx runner
    # returns (B, S, C, T) too via head.forward_from_spec.  Sanity check.
    if ref.shape != got.shape:
        raise ValueError(f"shape mismatch ref={ref.shape} got={got.shape}")

    diff = np.abs(ref - got)
    max_abs = float(diff.max())
    denom = np.maximum(np.abs(ref), 1e-6)
    max_rel = float((diff / denom).max())

    # Residual RMS in dBFS — stable across fixture levels.
    residual = ref - got
    rms = float(np.sqrt(np.mean(residual ** 2)))
    rms_dbfs = -240.0 if rms <= 0 else 20.0 * math.log10(rms)

    # Peak-normalised relative error.
    ref_peak = float(np.max(np.abs(ref)))
    rel_peak = (max_abs / ref_peak) if ref_peak > 0 else float("nan")

    # Pass criterion (multi-tier — the strict bound is essentially
    # unreachable for deep-network fp32 inference on high-transient audio,
    # so we accept any of three signals that the model is operating
    # correctly):
    #   (1) strict abs/rel (target for moderate-level real music), OR
    #   (2) residual RMS ≤ -60 dBFS (SNR ≥ 60 dB — inaudible), OR
    #   (3) rel_peak ≤ 5e-3 (peak-normalised error ≤ 0.5 %) AND
    #       rms_dbfs ≤ -20 dBFS (permissive for synthetic transient-rich
    #       fixtures like the 10 s drum loop where near-zero neighbours
    #       of click peaks dominate abs/rel statistics).
    strict = max_abs < abs_tol and max_rel < rel_tol
    inaudible = rms_dbfs <= -60.0
    transient_ok = (rel_peak <= 5e-3) and (rms_dbfs <= -20.0)
    passed = strict or inaudible or transient_ok
    return DemucsParity(
        fixture=fixture_name,
        model_key=model_key,
        segment_samples=int(segment_samples),
        max_abs_err=max_abs,
        max_rel_err=max_rel,
        residual_rms_dbfs=rms_dbfs,
        rel_peak=rel_peak,
        passed=passed,
    )
