# fp16 Export Investigation — Track A0.7

Null-test threshold: RMS residual of (fp32 − fp16) ≤ -60.0 dBFS.

| Model | Fixture | Residual RMS (dBFS) | Peak |abs| | Pass |
|---|---|---:|---:|:---:|
| ast_audioset | drum_loop_10s | -51.24 | 1.018e-02 | FAIL |
| ast_audioset | full_mix_30s | -53.81 | 7.251e-03 | FAIL |
| clap_htsat_unfused | drum_loop_10s | -82.45 | 2.548e-04 | PASS |
| clap_htsat_unfused | full_mix_30s | -38.68 | 3.898e-02 | FAIL |

## Notes
- **ast_audioset** — shipped fp32 fallback. 
- **clap_htsat_unfused** — shipped fp32 fallback. 
