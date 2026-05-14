"""Assertion helpers used by individual smoke tests.

Each helper raises ``AssertionError`` with a precise message on
mismatch and returns ``None`` on success. The smoke runner catches
AssertionError per-test, records the failure, and continues with the
remaining tests so one failure doesn't blow up the whole suite.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def assert_state(actual: dict | None, expected_subset: dict[str, Any]) -> None:
    """Assert every key/value in ``expected_subset`` matches in ``actual``.

    Recursive on dicts. Other values use ``==``. Missing keys in
    ``actual`` are an assertion failure. Extra keys in ``actual`` are
    fine — this is a partial match by design (server state grows new
    fields over time; smoke tests pin only what they care about).
    """
    if actual is None:
        raise AssertionError("expected state dict, got None (server unreachable?)")
    _assert_dict_subset(actual, expected_subset, path="$")


def _assert_dict_subset(actual: Any, expected: Any, *, path: str) -> None:
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            raise AssertionError(
                f"at {path}: expected dict, got {type(actual).__name__}: {actual!r}"
            )
        for k, v in expected.items():
            if k not in actual:
                raise AssertionError(
                    f"at {path}: key {k!r} missing from actual. keys={list(actual)!r}"
                )
            _assert_dict_subset(actual[k], v, path=f"{path}.{k}")
        return
    if actual != expected:
        raise AssertionError(f"at {path}: expected {expected!r}, got {actual!r}")


def assert_curation_file(curation_path: Path, expected_keys: list[str]) -> None:
    """Assert the curation YAML exists and contains the expected top-level keys."""
    if not curation_path.exists():
        raise AssertionError(f"curation file not written: {curation_path}")
    # Tolerate either YAML or JSON depending on writer version — both
    # have the same top-level key shape.
    text = curation_path.read_text()
    for key in expected_keys:
        # Crude but adequate for smoke: just look for "key:" or '"key":'
        if f"{key}:" not in text and f'"{key}"' not in text:
            raise AssertionError(
                f"curation file {curation_path.name} missing key {key!r}\n"
                f"--- file head ---\n{text[:400]}\n--- end ---"
            )


def assert_bounce_dir(bounce_dir: Path, expected_wav_count: int) -> None:
    """Assert ``bounce_dir`` exists with the expected number of WAV files."""
    if not bounce_dir.exists():
        raise AssertionError(f"bounce dir not created: {bounce_dir}")
    wavs = sorted(bounce_dir.glob("*.wav"))
    if len(wavs) != expected_wav_count:
        raise AssertionError(
            f"bounce dir {bounce_dir.name}: expected {expected_wav_count} wavs, "
            f"got {len(wavs)} ({[w.name for w in wavs[:6]]}...)"
        )


def assert_ppak_exists(export_path: Path, min_size: int = 1024) -> None:
    """Assert ``.ppak`` file exists and is at least ``min_size`` bytes."""
    if not export_path.exists():
        raise AssertionError(f"ppak not produced: {export_path}")
    size = export_path.stat().st_size
    if size < min_size:
        raise AssertionError(
            f"ppak {export_path.name} is suspiciously small: {size} bytes (expected ≥ {min_size})"
        )


def assert_track_count(state: dict | None, prefix: str, expected: int) -> None:
    """Assert the server-state's tracks list has ``expected`` entries with ``prefix``.

    The configurator server's /state response shape isn't pinned here;
    we look in several plausible locations so the assertion survives
    minor state-schema changes.
    """
    if state is None:
        raise AssertionError("expected /state dict, got None")
    tracks: list[Any] = []
    # Try a few shapes that the server has historically returned.
    for path in (("tracks",), ("live", "tracks"), ("session", "tracks")):
        node: Any = state
        for k in path:
            if isinstance(node, dict) and k in node:
                node = node[k]
            else:
                node = None
                break
        if isinstance(node, list):
            tracks = node
            break
    matching = [
        t for t in tracks if isinstance(t, dict) and str(t.get("name", "")).startswith(prefix)
    ]
    if len(matching) != expected:
        raise AssertionError(
            f"tracks with prefix {prefix!r}: expected {expected}, got {len(matching)}. "
            f"(state.tracks had {len(tracks)} entries)"
        )
