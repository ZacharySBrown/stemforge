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

from stemforge.configurator.intents import POPUP_ALS_SENTINEL
from stemforge.configurator.schemas import StemforgeState
from stemforge.configurator.state import (
    AppState,
    clear_active_curation_for_host,
    get_active_curation,
    get_active_curation_for_host,
    load_state,
    save_state,
    set_active_curation,
    set_active_curation_for_host,
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


# ── Pre-UAT P1-3 helpers: sentinel-aware writers on AppState ────────────────
#
# Tests cover the four call patterns the design call (option (b) — encapsulate
# the sentinel handling) needs to handle: explicit path, sentinel path,
# None path, and missing-key reads.


def _make_app_state(tmp_path: Path) -> AppState:
    state = AppState()
    state.state_path = tmp_path / "host.json"
    return state


def test_set_active_curation_for_host_explicit_path(tmp_path: Path) -> None:
    """Explicit als_path lands in the dict under that key."""
    state = _make_app_state(tmp_path)
    sf_state = set_active_curation_for_host(state, "/abs/project.als", "verse1")
    assert sf_state.active_curations == {"/abs/project.als": "verse1"}
    # Cache mirrors disk.
    assert state.cached_stemforge_state.active_curations == {"/abs/project.als": "verse1"}


def test_set_active_curation_for_host_sentinel_path(tmp_path: Path) -> None:
    """Explicit sentinel als_path lands under the sentinel key."""
    state = _make_app_state(tmp_path)
    sf_state = set_active_curation_for_host(state, POPUP_ALS_SENTINEL, "verse2")
    assert sf_state.active_curations == {"__popup__": "verse2"}


def test_set_active_curation_for_host_none_normalizes_to_sentinel(
    tmp_path: Path,
) -> None:
    """None als_path normalizes to the popup sentinel."""
    state = _make_app_state(tmp_path)
    sf_state = set_active_curation_for_host(state, None, "verse3")
    assert sf_state.active_curations == {"__popup__": "verse3"}


def test_set_active_curation_for_host_empty_string_normalizes_to_sentinel(
    tmp_path: Path,
) -> None:
    """Empty-string als_path is treated as missing (defensive)."""
    state = _make_app_state(tmp_path)
    sf_state = set_active_curation_for_host(state, "", "verse4")
    assert sf_state.active_curations == {"__popup__": "verse4"}


def test_clear_active_curation_for_host_explicit_path(tmp_path: Path) -> None:
    state = _make_app_state(tmp_path)
    set_active_curation_for_host(state, "/abs/p.als", "v")
    sf_state = clear_active_curation_for_host(state, "/abs/p.als")
    assert sf_state.active_curations == {}


def test_clear_active_curation_for_host_sentinel_path(tmp_path: Path) -> None:
    state = _make_app_state(tmp_path)
    set_active_curation_for_host(state, POPUP_ALS_SENTINEL, "v")
    sf_state = clear_active_curation_for_host(state, None)  # None → sentinel
    assert sf_state.active_curations == {}


def test_clear_active_curation_for_host_idempotent_when_missing(
    tmp_path: Path,
) -> None:
    """Clearing an unset host is a no-op + returns empty state."""
    state = _make_app_state(tmp_path)
    sf_state = clear_active_curation_for_host(state, "/never-set.als")
    assert sf_state.active_curations == {}


def test_get_active_curation_for_host_returns_value(tmp_path: Path) -> None:
    state = _make_app_state(tmp_path)
    set_active_curation_for_host(state, "/abs/p.als", "verse")
    assert get_active_curation_for_host(state, "/abs/p.als") == "verse"


def test_get_active_curation_for_host_sentinel_lookup(tmp_path: Path) -> None:
    state = _make_app_state(tmp_path)
    set_active_curation_for_host(state, POPUP_ALS_SENTINEL, "verse")
    # All three lookups (sentinel, None, "") return the same value.
    assert get_active_curation_for_host(state, POPUP_ALS_SENTINEL) == "verse"
    assert get_active_curation_for_host(state, None) == "verse"
    assert get_active_curation_for_host(state, "") == "verse"


def test_get_active_curation_for_host_missing_key_returns_none(tmp_path: Path) -> None:
    state = _make_app_state(tmp_path)
    assert get_active_curation_for_host(state, "/nope.als") is None
    # Sentinel namespace also empty when nothing was ever written.
    assert get_active_curation_for_host(state, None) is None


def test_helpers_keep_in_memory_cache_in_sync(tmp_path: Path) -> None:
    """Writes through the helper refresh the cache without disk read.

    Belt-and-suspenders: the helpers don't just persist — they also
    mirror into ``cached_stemforge_state`` so the ``POST /als-opened``
    fast-path sees the latest map immediately.
    """
    state = _make_app_state(tmp_path)
    assert state.cached_stemforge_state.active_curations == {}
    set_active_curation_for_host(state, "/cache.als", "fresh")
    assert state.cached_stemforge_state.active_curations == {"/cache.als": "fresh"}
    clear_active_curation_for_host(state, "/cache.als")
    assert state.cached_stemforge_state.active_curations == {}
