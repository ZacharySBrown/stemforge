"""
Guard-rails for the Track B package split.

These tests enforce the lazy-import contract so a future change can't
accidentally make `import stemforge.cli` pull in torch / transformers
and inflate the core install footprint.
"""

import subprocess
import sys
import textwrap


CHECK_SCRIPT = textwrap.dedent(
    """
    import sys
    import stemforge
    import stemforge.cli  # noqa: F401
    import stemforge.analyzer  # noqa: F401  (module defs only — no model load)

    heavy = {
        "torch":        [m for m in sys.modules if m == "torch" or m.startswith("torch.")],
        "transformers": [m for m in sys.modules if m == "transformers" or m.startswith("transformers.")],
        # "demucs" alone matches our own stemforge.backends.demucs, so check the lib ns
        "demucs":       [m for m in sys.modules if m == "demucs" or m.startswith("demucs.")],
        "laion_clap":   [m for m in sys.modules if m == "laion_clap" or m.startswith("laion_clap.")],
    }
    for name, mods in heavy.items():
        if mods:
            raise SystemExit(f"{name} leaked into eager import: {mods[:5]}")
    print("OK")
    """
)


def test_core_import_does_not_pull_torch_or_transformers():
    """
    `import stemforge.cli` and `import stemforge.analyzer` must not eagerly
    import torch, transformers, demucs (library), or laion_clap.

    Run in a subprocess so we get a clean sys.modules snapshot regardless of
    what the pytest process itself has already imported.
    """
    result = subprocess.run(
        [sys.executable, "-c", CHECK_SCRIPT],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        "Heavy deps leaked into stemforge eager imports.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert "OK" in result.stdout


def test_demucs_backend_friendly_error_when_torch_missing(monkeypatch):
    """
    When torch/demucs are not importable, DemucsBackend.separate() raises a
    RuntimeError that points users at `stemforge[native]`.
    """
    from pathlib import Path

    from stemforge.backends.demucs import DemucsBackend

    # Force ImportError for torch and demucs.* inside separate()'s try block.
    real_import = __builtins__["__import__"] if isinstance(__builtins__, dict) else __import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "torch" or name.startswith("torch.") or name.startswith("demucs"):
            raise ImportError(f"simulated missing {name}")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr("builtins.__import__", fake_import)

    be = DemucsBackend()
    try:
        be.separate(Path("/tmp/does_not_matter.wav"), Path("/tmp/out"))
    except RuntimeError as e:
        msg = str(e)
        assert "stemforge[native]" in msg, f"friendly hint missing in: {msg}"
        assert "native" in msg
    else:
        raise AssertionError("expected RuntimeError, got no exception")


def test_analyzer_friendly_error_when_transformers_missing(monkeypatch):
    """
    When transformers is not installable, the analyzer raises a RuntimeError
    pointing at `stemforge[analyzer]`.
    """
    # Reset the module-level cache so _get_clap actually tries to import.
    import stemforge.analyzer as analyzer_mod

    monkeypatch.setattr(analyzer_mod, "_clap_pipeline", None)
    monkeypatch.setattr(analyzer_mod, "_ast_pipeline", None)

    real_import = __builtins__["__import__"] if isinstance(__builtins__, dict) else __import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "transformers" or name.startswith("transformers."):
            raise ImportError(f"simulated missing {name}")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr("builtins.__import__", fake_import)

    for fn in (analyzer_mod._get_clap, analyzer_mod._get_ast):
        try:
            fn()
        except RuntimeError as e:
            assert "stemforge[analyzer]" in str(e), f"analyzer hint missing: {e}"
        else:
            raise AssertionError(f"{fn.__name__} should have raised RuntimeError")
