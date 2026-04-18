# v0/build — Build Artifacts

This tree is generated, not authored. Track A0 writes ONNX model weights
and the accompanying manifest here; other tracks consume them.

## Why most files are gitignored

The `.onnx` weights are hundreds of megabytes each. They are hosted out-of-band
(GitHub release asset / R2 / S3) and fetched by `tools/fetch-models.sh` on
clean checkouts. The only files tracked in git are:

- `v0/build/README.md` (this file)
- `v0/build/models/manifest.json` (see schema in `v0/src/A0/manifest.py`)
- `v0/build/models/clap_genre_embeddings.json` (small sidecar, ~100 KB)

Everything else in `v0/build/` — the `.onnx` files, the `ort_cache/` tree,
optimum's scratch artifacts — is produced locally by running
`python -m v0.src.A0.convert`.

## Reproducing

```bash
# Fast iteration, one model at a time:
python -m v0.src.A0.convert --models ast
python -m v0.src.A0.convert --models clap
python -m v0.src.A0.convert --models demucs

# Everything in one pass:
python -m v0.src.A0.convert
```

See `v0/src/A0/README.md` for the downstream consumer guide (Track A native
host).
