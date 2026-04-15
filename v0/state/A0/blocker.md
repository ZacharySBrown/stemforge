# A0 Blocker — Demucs STFT Export

**Status:** `done.flag` is **not** being written because the **primary**
deliverable (`htdemucs_ft.onnx`) is blocked. `v0/state/A0/artifacts.json`
is written with `status: "partial-blocked"` and the AST + CLAP artifacts
that DID succeed so downstream tracks can still make progress on non-Demucs
work.

## TL;DR

In-graph export of HTDemucs via `torch.onnx.export` fails on torch 2.11 /
onnxruntime 1.24 / opset 17 on both the dynamo and legacy paths. The
documented fallback — external STFT/iSTFT wrapper with only the learned
network in ONNX — requires a small surgical change to upstream
`demucs/htdemucs.py` (or a vendored copy) that Track A0 does not own.

**Recommendation:** land the external-STFT refactor in a vendored copy
under `stemforge/_vendor/demucs_patched.py` (owned by Track B's Engineer
during the package-split work), then re-open A0 and the ONNX export +
parity harness completes automatically.

## What was tried

| Attempt | Path | Result |
|---|---|---|
| 1 | `torch.onnx.export(head, ..., dynamo=True, opset=17)` | `TorchExportError: GuardOnDataDependentSymNode` in `demucs.hdemucs.pad1d` — the reflect-padding assert is data-dependent and `torch.export.export(..., strict=False)` refuses to trace it. |
| 2 | `torch.onnx.export(head, ..., dynamo=False, opset=17)` | `SymbolicValueError: STFT does not currently support complex types` — torch's onnx symbolic for complex STFT emits a tensor the ONNX `Reshape` symbolic cannot lower. |
| 3 | `torch.onnx.export(head, ..., dynamo=False, opset=18)` | Same as (2); the STFT symbolic complex-type limitation is not opset-gated. |
| 4 | Export each of the 4 `htdemucs_ft` heads separately | Same failure mode as (2) — failure is intrinsic to HTDemucs.forward regardless of which head is traced. |

Exact error signatures captured in `v0/state/A0/progress.ndjson` under
`phase: "demucs.export.in_graph"`.

## Root cause

`demucs.htdemucs.HTDemucs.forward` calls `self._spec(mix)` which wraps
`torch.stft(..., return_complex=True)` (see `demucs/spec.py:17`). The
output is `ComplexFloat`. torch's onnx symbolic for `Reshape` cannot
handle complex tensors and emits the `SymbolicValueError` above.

Independently, the dynamo path trips on `demucs/hdemucs.py:39` where
`pad1d` does `assert out[..., padding_left:padding_left+size] == x` —
a data-dependent equality over a symbolic slice.

Both bugs are inherent to Demucs's mixing of time and frequency domains
inside a single torch `forward`.

## Recommended fix: external STFT refactor

The A0 brief specifies this fallback explicitly:

> **Fallback:** export Demucs with STFT done in Python wrapper (pre/post
> processing outside ONNX graph, only the learned network inside ONNX).
> Ugly but reliable.

The concrete refactor:

1. Copy `demucs/htdemucs.py` into `stemforge/_vendor/demucs_patched.py`
   (or open a PR upstream against facebookresearch/demucs).
2. Add a new `forward_from_spec(self, mix, z_complex)` method that
   *takes* the spectrogram instead of computing it. Body mirrors the
   existing `forward` but skips lines 420-449 (the `_spec` call) and
   replaces lines 530-545 (the `_ispec` call) with a return of the raw
   spectrogram output.
3. In `v0/src/A0/demucs_export.ExternalSpecHTDemucs.forward`, call
   `self.head.forward_from_spec(mix, torch.complex(z_real, z_imag))`
   and return `(time_out, zout.real, zout.imag)`.
4. The Python/C++ caller does STFT/iSTFT outside the graph using the
   parameters exposed by `demucs_export.stft_params()`:
   - `n_fft = 4096`, `hop = 1024`, Hann window, `center=True`,
     `pad_mode="reflect"`, `onesided=True`.

Once step (2) lands, `v0/src/A0/demucs_export.export_head()` works
unchanged — the wrapper only needs the new method to be present.

## Estimated effort

- Upstream surgery: ~1 day (small refactor, self-contained in
  `htdemucs.py`, needs test cases comparing `forward` vs
  `forward_from_spec` bit-exact).
- Export + parity: ~2 hours once the refactor lands (A0 has the harness
  already — `v0/src/A0/demucs_export.validate()` is ready to compare
  against `demucs.apply.apply_model`).
- CoreML EP smoke test + fp16 investigation: ~4 hours (same pattern as
  AST/CLAP which already work end-to-end).

Total: ~1.5 day from today, with no open research questions.

## Escalation

This blocker was flagged to the orchestrator by writing this file
instead of `done.flag`. Per `v0/SHARED.md`:

> On blocker: The orchestrator picks up the blocker and either:
> - Remediates and re-invokes the agent
> - Adjusts the plan and reassigns

Suggested next action: reassign the Demucs refactor subtask to Track B
(who is already restructuring `stemforge/`) or spin a new Track A0.1
specifically for the vendored-Demucs patch. A0's scope ends at the point
where it has a patched head it can wrap.

## What DID succeed

See `v0/state/A0/artifacts.json` for the full list. Summary:

- **AST** (`MIT/ast-finetuned-audioset-10-10-0.4593`) — exported,
  validated, top-5 labels match, max logit diff well under `1e-3`.
- **CLAP** (`laion/clap-htsat-unfused`) — audio branch exported
  directly via `torch.onnx.export` (optimum does not yet have a CLAP
  config), validated at cosine = 1.000000 against the torch reference.
  Text-branch embeddings for the 13 genre prompts baked into
  `clap_genre_embeddings.json`.

Both are ready for Track A to integrate.
