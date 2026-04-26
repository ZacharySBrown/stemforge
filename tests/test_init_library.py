"""Tests for tools/init_library.py — library subdivision bootstrap."""
from __future__ import annotations

import importlib.util
from pathlib import Path

_HELPER = Path(__file__).resolve().parents[1] / "tools" / "init_library.py"
_spec = importlib.util.spec_from_file_location("init_library", _HELPER)
init_library_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(init_library_mod)


def test_creates_all_subdirs_in_empty_root(tmp_path):
    created, existed = init_library_mod.init_library(tmp_path, dry_run=False)
    assert len(created) == len(init_library_mod.SUBDIRS)
    assert not existed
    for sub in init_library_mod.SUBDIRS:
        assert (tmp_path / sub).is_dir()


def test_idempotent_second_run(tmp_path):
    init_library_mod.init_library(tmp_path, dry_run=False)
    created, existed = init_library_mod.init_library(tmp_path, dry_run=False)
    assert not created
    assert len(existed) == len(init_library_mod.SUBDIRS)


def test_dry_run_creates_nothing(tmp_path):
    created, _ = init_library_mod.init_library(tmp_path, dry_run=True)
    assert created  # would have created
    for p in created:
        assert not p.exists()


def test_preserves_existing_user_dirs(tmp_path):
    # Simulate user already has some dirs from their reorg
    (tmp_path / "Samples" / "Breaks" / "Sliced").mkdir(parents=True)
    (tmp_path / "Samples" / "Loops" / "pauls_loops").mkdir(parents=True)
    (tmp_path / "Samples" / "Loops" / "pauls_loops" / "kick.wav").touch()

    init_library_mod.init_library(tmp_path, dry_run=False)

    # User's stuff still there
    assert (tmp_path / "Samples" / "Breaks" / "Sliced").is_dir()
    assert (tmp_path / "Samples" / "Loops" / "pauls_loops" / "kick.wav").exists()
    # New subdivisions added
    assert (tmp_path / "Samples" / "Loops" / "Drums").is_dir()
    assert (tmp_path / "Samples" / "Loops" / "Vocal").is_dir()
