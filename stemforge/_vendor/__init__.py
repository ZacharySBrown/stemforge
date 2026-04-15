"""
Vendored upstream modules patched for ONNX export.

Why this directory exists
-------------------------
Some upstream libraries embed operations that ``torch.onnx.export`` cannot
trace (data-dependent asserts, complex-typed STFT/iSTFT, etc.).  For the
StemForge v0 ONNX-first build (see ``v0/PIVOT.md``) we need bit-exact
vendored copies with small, surgical edits that let the learned network
export cleanly while keeping non-exportable DSP (STFT/iSTFT) outside the
graph.

Rules for this directory
------------------------
* Every file here MUST start with the upstream copyright header and a
  ``# vendored from <pkg> vX.Y.Z`` comment pointing to the exact revision.
* Edits must be minimal and documented in a ``# PATCH:`` comment above the
  change.  If a patch grows beyond a small refactor, reconsider and push
  upstream first.
* Vendored modules are not part of the public ``stemforge`` API — callers
  should import from ``stemforge._vendor.<module>`` only from inside the
  v0 track code or from tests.

Current contents
----------------
* ``demucs_patched`` — vendored from ``demucs`` v4.0.1.  Adds
  ``HTDemucs.forward_from_spec`` so Track A0 can export the learned network
  to ONNX with STFT/iSTFT performed by the Python (and eventually C++)
  caller.  See ``v0/state/A0/blocker.md`` and ``v0/src/A0/demucs_export.py``
  for context.
"""
