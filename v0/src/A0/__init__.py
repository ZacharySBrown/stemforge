"""
Track A0 — ONNX Conversion + Parity Validation.

Converts the three families of PyTorch / HuggingFace models that StemForge
uses at inference time into ONNX for the ONNX-first v0 device:

- Demucs hybrid (htdemucs, htdemucs_ft, htdemucs_6s)   — stem separation
- CLAP     (laion/clap-htsat-unfused)                  — genre classification
- AST      (MIT/ast-finetuned-audioset-10-10-0.4593)   — instrument detection

See `v0/tracks/A0-onnx-conversion.md` for the authoritative brief and
`v0/PIVOT.md` §E for the hard inference-optimization requirements this
module must satisfy.
"""

__all__: list[str] = []
