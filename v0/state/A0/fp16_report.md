# fp16 Export Investigation — Track A0.7

Null-test threshold: RMS residual of (fp32 − fp16) ≤ -60.0 dBFS.

| Model | Fixture | Residual RMS (dBFS) | Peak |abs| | Pass |
|---|---|---:|---:|:---:|
| htdemucs | (no residuals) | — | — | fail |
| htdemucs_6s | (no residuals) | — | — | fail |
| htdemucs_ft | (no residuals) | — | — | fail |

## Notes
- **htdemucs** — shipped fp32 fallback. inference failed: [ONNXRuntimeError] : 1 : FAIL : Load model from /Users/zak/zacharysbrown/stemforge/.claude/worktrees/agent-a74b3cc1/v0/build/models/htdemucs/htdemucs.fp16.onnx failed:Type Error: Type (tensor(float16)) of output arg (/Cast_output_0) of node (/Cast) does not match expected type (tensor(float)).
- **htdemucs_6s** — shipped fp32 fallback. inference failed: [ONNXRuntimeError] : 1 : FAIL : Load model from /Users/zak/zacharysbrown/stemforge/.claude/worktrees/agent-a74b3cc1/v0/build/models/htdemucs_6s/htdemucs_6s.fp16.onnx failed:Type Error: Type (tensor(float16)) of output arg (/Cast_output_0) of node (/Cast) does not match expected type (tensor(float)).
- **htdemucs_ft** — shipped fp32 fallback. inference failed: [ONNXRuntimeError] : 1 : FAIL : Load model from /Users/zak/zacharysbrown/stemforge/.claude/worktrees/agent-a74b3cc1/v0/build/models/htdemucs_ft/htdemucs_ft.head0.fp16.onnx failed:Type Error: Type (tensor(float16)) of output arg (/Cast_output_0) of node (/Cast) does not match expected type (tensor(float)).
