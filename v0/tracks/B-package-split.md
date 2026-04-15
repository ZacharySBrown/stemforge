# Track B — Python Package Split

## Goal

Split `stemforge` into two dependency tiers so:
- `pip install stemforge` works without torch (for LALAL/MusicAI-only users, and for CI speed)
- `pip install stemforge[native]` brings in torch+demucs for local Demucs
- Track A's PyInstaller build only freezes what it actually needs

## Inputs

- Current `pyproject.toml`
- Current `stemforge/` module graph

## Outputs

- Updated `pyproject.toml` with `[project.optional-dependencies]`: `core` (default), `native`, `analyzer`, `dev`
- Lazy imports in:
  - `stemforge/backends/demucs.py` — torch/demucs inside `DemucsBackend.separate()`
  - `stemforge/analyzer.py` — transformers/clap/ast inside `analyze()`
- Friendly errors when a heavy backend is used without its extras installed
- `v0/state/B/done.flag`

## Subtasks

### B1 — pyproject.toml shape
```toml
[project]
dependencies = [
    # Lightweight only — no torch, no transformers
    "requests>=2.31", "librosa>=0.10.2", "soundfile>=0.12",
    "numpy>=1.26", "click>=8.1", "rich>=13.7",
    "pyyaml>=6", "musicai-sdk>=0.1",
]

[project.optional-dependencies]
native   = ["torch>=2.1", "torchaudio>=2.1", "demucs>=4.0.1"]
analyzer = ["transformers>=4.40", "laion-clap>=1.1"]
dev      = ["pytest>=8", "pyinstaller>=6.5", ...]
```

Note: `librosa` stays in core because beat tracking is shared between backends. It doesn't pull torch.

### B2 — Lazy imports in demucs backend
Move `import torch`, `from demucs.pretrained import get_model` from module top to inside `DemucsBackend.separate()`. Wrap with a try/except that raises a clear message:

```python
def separate(self, audio_path, out_dir, model="default"):
    try:
        import torch
        from demucs.pretrained import get_model
        from demucs.apply import apply_model
    except ImportError as e:
        raise RuntimeError(
            "Demucs backend requires the 'native' extras. Install with:\n"
            "  pip install 'stemforge[native]'"
        ) from e
    ...
```

### B3 — Lazy imports in analyzer
Same pattern in `stemforge/analyzer.py` for transformers/CLAP/AST imports. Error message points to `stemforge[analyzer]`.

### B4 — Import hygiene
Run `python -c "import stemforge; import stemforge.cli"` in a fresh venv with **only** core deps. Must succeed without importing torch.

Tool:
```bash
python -c "import sys; import stemforge.cli; print('torch' in sys.modules)"
# Expected: False
```

### B5 — README update
Add install variants table to README.md:
```
pip install stemforge              # LALAL/MusicAI only
pip install stemforge[native]      # + local Demucs
pip install stemforge[analyzer]    # + audio classification
pip install stemforge[native,analyzer,dev]   # everything
```

## Acceptance

- Fresh venv + `pip install .` succeeds in <30s (no torch download).
- `python -c "import stemforge.cli"` works; `torch` not in `sys.modules`.
- `stemforge balance` works (LALAL HTTP backend, no torch).
- `stemforge split track.wav --backend demucs` fails with the friendly error in the core-only venv.
- `pip install .[native]` + same command succeeds.

## Subagent Brief

You are implementing Track B of StemForge v0.

**Read:**
- `v0/PLAN.md`, `v0/SHARED.md`, `v0/tracks/B-package-split.md`
- `stemforge/__init__.py`, `stemforge/backends/demucs.py`, `stemforge/analyzer.py`, `stemforge/cli.py`, `pyproject.toml`

**Touch only:**
- `pyproject.toml`
- `stemforge/backends/demucs.py`
- `stemforge/analyzer.py`
- `stemforge/__init__.py` (only if it imports heavy modules transitively)
- `README.md` (install variants section)

**Do not:**
- Delete any existing functionality
- Change any function signatures
- Touch Track A's files

**Verify with two venvs** (use `uv venv` for speed):
1. Core venv: `pip install .` → assertions in B4
2. Native venv: `pip install .[native]` → `stemforge split` with demucs succeeds

Write `v0/state/B/done.flag` on success, `v0/state/B/blocker.md` if blocked.
