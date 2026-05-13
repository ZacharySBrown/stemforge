"""Tests for ``~/stemforge/.stemforge_state.json`` reader/writer.

Exercises :func:`load_state`, :func:`save_state`,
:func:`get_active_curation`, :func:`set_active_curation`. The state file
is the only persistent runtime state the server owns (spec §2.4); these
tests pin its on-disk shape + the active-curation accessor contract.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from stemforge.configurator.schemas import StemforgeState
from stemforge.configurator.state import (
    get_active_curation,
    load_state,
    save_state,
    set_active_curation,
)


# ── load_state ──────────────────────────────────────────────────────────────


def test_load_state_returns_empty_when_file_missing(tmp_path: Path) -> None:
    state = load_state(tmp_path / "absent.json")
    assert isinstance(state, StemforgeState)
    assert state.active_curations == {}


def test_load_state_returns_empty_when_file_blank(tmp_path: Path) -> None:
    p = tmp_path / "blank.json"
    p.write_text("")
    state = load_state(p)
    assert state.active_curations == {}


def test_load_state_parses_valid_file(tmp_path: Path) -> None:
    p = tmp_path / "state.json"
    p.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "active_curations": {"/foo.als": "alpha", "/bar.als": "beta"},
            }
        )
    )
    state = load_state(p)
    assert state.active_curations == {"/foo.als": "alpha", "/bar.als": "beta"}


def test_load_state_rejects_malformed_json(tmp_path: Path) -> None:
    p = tmp_path / "bad.json"
    p.write_text("{not json}")
    with pytest.raises(json.JSONDecodeError):
        load_state(p)


# ── save_state ─────────────────────────────────────────────────────────────


def test_save_state_atomic_writes_canonical_json(tmp_path: Path) -> None:
    state_path = tmp_path / "saved.json"
    state = StemforgeState(active_curations={"/x.als": "verse1"})
    save_state(state, state_path)
    assert state_path.is_file()
    data = json.loads(state_path.read_text())
    assert data["active_curations"] == {"/x.als": "verse1"}
    assert data["schema_version"] == 1


def test_save_state_creates_parent_dir(tmp_path: Path) -> None:
    nested = tmp_path / "deep" / "state.json"
    save_state(StemforgeState(), nested)
    assert nested.is_file()


# ── set_active_curation / get_active_curation ──────────────────────────────


def test_set_and_get_active_curation(tmp_path: Path) -> None:
    p = tmp_path / "active.json"
    set_active_curation("/foo.als", "verse1", p)
    assert get_active_curation("/foo.als", p) == "verse1"
    assert get_active_curation("/missing.als", p) is None


def test_set_active_curation_with_none_clears(tmp_path: Path) -> None:
    p = tmp_path / "clear.json"
    set_active_curation("/foo.als", "v1", p)
    assert get_active_curation("/foo.als", p) == "v1"
    set_active_curation("/foo.als", None, p)
    assert get_active_curation("/foo.als", p) is None


def test_set_active_curation_updates_last_seen_at(tmp_path: Path) -> None:
    p = tmp_path / "ts.json"
    state = set_active_curation("/x.als", "n", p)
    assert state.last_seen_at is not None
