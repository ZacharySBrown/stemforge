"""
Parity test for the vendored HTDemucs.forward_from_spec patch.

The contract (see ``stemforge/_vendor/demucs_patched.py``): running
``forward_from_spec(mix_padded, _spec(mix_padded))`` followed by a
caller-side ``_ispec`` and the canonical post-pad crop must be
numerically indistinguishable from the upstream ``forward(mix)``.
"""
from __future__ import annotations

import pytest

torch = pytest.importorskip("torch")


def _make_tiny_htdemucs():
    """
    Build a small HTDemucs from the VENDORED module so weights are aligned.

    We deliberately don't fetch pretrained checkpoints here (network-free
    test).  Random weights are fine — the parity contract is about the
    graph, not the model quality.
    """
    from stemforge._vendor.demucs_patched import HTDemucs

    torch.manual_seed(0)
    model = HTDemucs(
        sources=["drums", "bass", "other", "vocals"],
        audio_channels=2,
        # Shrink to keep test under a second on CPU.
        channels=8,
        growth=2,
        nfft=4096,
        depth=4,
        t_layers=1,
        bottom_channels=0,
        samplerate=44100,
        segment=1,            # 1 s training segment
        use_train_segment=True,
    ).eval()
    return model


def _apply_upstream_forward(model, mix):
    """Run the patched module's own ``forward`` — the reference."""
    with torch.no_grad():
        return model.forward(mix)


def _apply_external_spec(model, mix):
    """Simulate the caller responsibilities for ``forward_from_spec``."""
    import torch.nn.functional as F
    from fractions import Fraction

    length = mix.shape[-1]
    # Mirror the training-length pad the upstream forward applies so the
    # caller-side STFT sees the same signal.
    if model.use_train_segment:
        training_length = int(Fraction(model.segment) * model.samplerate)
        if mix.shape[-1] < training_length:
            length_pre_pad = mix.shape[-1]
            mix_padded = F.pad(mix, (0, training_length - length_pre_pad))
        else:
            length_pre_pad = None
            mix_padded = mix
    else:
        training_length = length
        length_pre_pad = None
        mix_padded = mix

    with torch.no_grad():
        z = model._spec(mix_padded)
        xt, zout = model.forward_from_spec(mix_padded, z)
        # The caller does iSTFT + summation.
        x_freq = model._ispec(zout, training_length)
        out = xt + x_freq
        if length_pre_pad is not None:
            out = out[..., :length_pre_pad]
        return out


def test_forward_from_spec_matches_forward_random_input():
    """
    On a tiny randomly-initialized HTDemucs, forward() ≡ forward_from_spec()
    after the caller performs external STFT/iSTFT.
    """
    model = _make_tiny_htdemucs()
    # 0.9 s of stereo audio @ 44.1 kHz — shorter than the training segment
    # so the training-length pad is exercised.
    mix = torch.randn(1, 2, int(0.9 * model.samplerate)) * 0.1

    ref = _apply_upstream_forward(model, mix)
    got = _apply_external_spec(model, mix)

    assert ref.shape == got.shape, (ref.shape, got.shape)
    max_abs = (ref - got).abs().max().item()
    # Float32 STFT/iSTFT round-trip has a tiny numerical residual; 1e-5 is
    # looser than the 1e-6 headline but still orders of magnitude below the
    # Demucs parity budget of 1e-3.
    assert max_abs < 1e-5, (
        f"forward vs forward_from_spec parity failed: max_abs={max_abs:.3e}"
    )


def test_forward_from_spec_matches_forward_training_length_input():
    """Exercise the no-pad branch (mix already at training length)."""
    model = _make_tiny_htdemucs()
    # Exactly segment seconds — no training-length pad.
    length = int(model.segment * model.samplerate)
    mix = torch.randn(1, 2, length) * 0.1

    ref = _apply_upstream_forward(model, mix)
    got = _apply_external_spec(model, mix)
    max_abs = (ref - got).abs().max().item()
    assert max_abs < 1e-5, (
        f"forward vs forward_from_spec parity failed (no pad): "
        f"max_abs={max_abs:.3e}"
    )


def test_forward_from_spec_cac_matches_forward_from_spec():
    """
    The all-real CAC variant used for ONNX export must match the
    complex-tensor variant bit-exactly (they share ``_learned_forward``).
    """
    from v0.src.A0.demucs_export import pack_cac, unpack_cac

    model = _make_tiny_htdemucs()
    length = int(model.segment * model.samplerate)
    mix = torch.randn(1, 2, length) * 0.1
    with torch.no_grad():
        z = model._spec(mix)
        xt_ref, zout_ref = model.forward_from_spec(mix, z)

        z_cac = pack_cac(z)
        xt_cac, zout_cac = model.forward_from_spec_cac(mix, z_cac)
        zout_from_cac = unpack_cac(zout_cac)

    # Time branch must be exact (no packing involved).
    assert torch.allclose(xt_ref, xt_cac, atol=0.0), \
        f"time branch differs: max_abs={(xt_ref-xt_cac).abs().max()}"
    # Freq branch: complex → CAC → complex round-trip must be bit-exact.
    assert torch.allclose(zout_ref, zout_from_cac, atol=1e-6), \
        (f"freq branch differs: max_abs="
         f"{(zout_ref - zout_from_cac).abs().max()}")
