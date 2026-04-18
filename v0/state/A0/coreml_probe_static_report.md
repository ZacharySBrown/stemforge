# CoreML EP probe — static vs dynamic shapes

Sweep: each ONNX × CoreML option combination → ORT VERBOSE log
scraped for per-node EP assignment + 5 timed runs after 3 warmup.

| label | loaded | nodes(coreml/cpu/total) | part% | warmup_s | mean_s | p95_s | error |
|---|---:|---|---:|---:|---:|---:|---|
| htdemucs_dynamic::cpu_only | False | 0/0/4244 | 0.0 | 5.9506 | 2.0793 | 2.3772 |  |
| htdemucs_dynamic::coreml_mlprogram_all_dynamic | False | — | None | None | None | None | Fail: [ONNXRuntimeError] : 1 : FAIL : Failed to create MLModel, error: Failed to build the model execution plan using a  |
| htdemucs_dynamic::coreml_mlprogram_all_static | True | 0/0/4244 | 0.0 | 5.9387 | 1.9686 | 1.9937 |  |
| htdemucs_dynamic::coreml_mlprogram_ane_only | True | 0/0/4244 | 0.0 | 6.0204 | 1.9809 | 2.0135 |  |
| htdemucs_dynamic::coreml_neuralnetwork_all | True | 0/0/4244 | 0.0 | 5.794 | 1.8967 | 1.9548 |  |

Note: ORT VERBOSE per-node assignment lines vary by version;
`coreml_partition_pct` is a best-effort scrape of the load-time
log. Authoritative count requires reading the partition graph.