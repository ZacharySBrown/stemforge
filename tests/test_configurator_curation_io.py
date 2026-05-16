"""Unit tests for the :mod:`stemforge.configurator.curation_io` helpers.

Covers the atomic write/read path, file-lock behavior, name validation,
and discovery. These run independent of the FastAPI app — they're the
primitive contract every endpoint composes on top of.
"""

from __future__ import annotations

import threading
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

from stemforge.configurator.curation_io import (
    curation_path,
    is_valid_curation_name,
    list_curations,
    lock_curation,
    read_curation,
    write_curation_atomic,
)
from stemforge.configurator.schemas import Curation, Pad, Target


def _make_curation(name: str, pads_per_group: int = 4) -> Curation:
    now = datetime.now(UTC)
    target = Target(groups=2, pads_per_group=pads_per_group)
    from stemforge.configurator.schemas import Group

    groups = {
        letter: Group(
            label="",
            template=None,
            pads=[Pad(pad_id=f"{letter}{i + 1:02d}") for i in range(pads_per_group)],
        )
        for letter in ("A", "B")
    }
    return Curation(
        name=name,
        type="deck",
        created_at=now,
        modified_at=now,
        target=target,
        groups=groups,
    )


# ── is_valid_curation_name ─────────────────────────────────────────────────


@pytest.mark.parametrize(
    "name",
    [
        "verse_swap",
        "verse-swap-v1",
        "A",
        "a1.b2-c3",
        "x" * 64,
    ],
)
def test_valid_curation_names_accepted(name: str) -> None:
    assert is_valid_curation_name(name) is True


@pytest.mark.parametrize(
    "name",
    [
        "",
        "/escape",
        "foo/bar",
        "..",
        ".",
        ".stemforge_state",
        "stemforge_state",
        "_leading_underscore",  # must start alphanumeric
        ".leading_dot",
        "x" * 65,
        "spaces in name",
        "tab\there",
        None,  # not a str
        123,  # not a str
    ],
)
def test_invalid_curation_names_rejected(name) -> None:
    assert is_valid_curation_name(name) is False


# ── write_curation_atomic + read_curation ──────────────────────────────────


def test_atomic_write_then_read_round_trips(tmp_path: Path) -> None:
    curation = _make_curation("round_trip")
    path = curation_path(tmp_path, "round_trip")
    write_curation_atomic(path, curation)
    restored = read_curation(path)
    assert restored.name == "round_trip"
    assert restored == curation


def test_long_external_path_is_not_line_wrapped(tmp_path: Path) -> None:
    """A long external_path must stay on ONE line.

    PyYAML's default width (80) folds long plain scalars across indented
    continuation lines. That's valid YAML, but the M4L device's
    hand-rolled line-based parser can't follow a folded scalar and
    rejects the whole curation. Deep Ableton crop paths trip this.
    """
    from stemforge.configurator.schemas.curation import PadSource

    long_path = (
        "/Users/zak/Music/Ableton/Live Recordings/2026-05-15 065129 "
        "Temp Project/Samples/Processed/Crop/Soul Pride 162 [2026-05-15 223746].wav"
    )
    curation = _make_curation("wrappy")
    curation.groups["A"].pads[0] = Pad(
        pad_id="A01",
        source=PadSource.for_external(external_path=long_path),
    )
    path = curation_path(tmp_path, "wrappy")
    write_curation_atomic(path, curation)

    text = path.read_text()
    # The path appears verbatim on a single line — no folding.
    assert f"external_path: {long_path}" in text
    # And it still round-trips.
    assert read_curation(path).groups["A"].pads[0].source.external_path == long_path


def test_atomic_write_creates_parent_dir(tmp_path: Path) -> None:
    nested = tmp_path / "deeper" / "still" / "curations"
    curation = _make_curation("c")
    path = curation_path(nested, "c")
    write_curation_atomic(path, curation)
    assert path.is_file()


def test_atomic_write_leaves_no_tmp_files_on_success(tmp_path: Path) -> None:
    curation = _make_curation("clean")
    path = curation_path(tmp_path, "clean")
    write_curation_atomic(path, curation)
    leftovers = list(tmp_path.glob(".clean.yaml.*.tmp"))
    assert leftovers == []


def test_read_curation_rejects_malformed_yaml(tmp_path: Path) -> None:
    p = tmp_path / "broken.yaml"
    p.write_text("not: a: real: mapping: structure: [")  # invalid YAML
    with pytest.raises(Exception):
        read_curation(p)


def test_read_curation_rejects_non_mapping_root(tmp_path: Path) -> None:
    import yaml as _yaml

    p = tmp_path / "list_root.yaml"
    p.write_text("- one\n- two\n")
    with pytest.raises(_yaml.YAMLError):
        read_curation(p)


# ── list_curations ─────────────────────────────────────────────────────────


def test_list_curations_returns_stable_sorted_yaml_files(tmp_path: Path) -> None:
    for name in ["c", "a", "b"]:
        write_curation_atomic(curation_path(tmp_path, name), _make_curation(name))
    # Drop a non-yaml file; should be ignored.
    (tmp_path / "decoy.txt").write_text("nope")
    paths = list_curations(tmp_path)
    assert [p.stem for p in paths] == ["a", "b", "c"]


def test_list_curations_returns_empty_for_missing_dir(tmp_path: Path) -> None:
    assert list_curations(tmp_path / "does-not-exist") == []


# ── lock_curation ─────────────────────────────────────────────────────────


def test_lock_curation_serializes_two_threads(tmp_path: Path) -> None:
    """Two threads each acquire the lock; the second blocks on the first.

    We verify by recording acquire-times — the second thread must enter
    *after* the first releases. Granularity is ~100ms to dodge clock jitter.
    """
    path = curation_path(tmp_path, "guarded")
    write_curation_atomic(path, _make_curation("guarded"))
    enter_times: list[float] = []
    release_times: list[float] = []
    barrier = threading.Barrier(2)

    def _worker(hold_for: float) -> None:
        barrier.wait()
        with lock_curation(path):
            enter_times.append(time.monotonic())
            time.sleep(hold_for)
            release_times.append(time.monotonic())

    t1 = threading.Thread(target=_worker, args=(0.2,))
    t2 = threading.Thread(target=_worker, args=(0.05,))
    t1.start()
    t2.start()
    t1.join(timeout=5.0)
    t2.join(timeout=5.0)
    assert len(enter_times) == 2
    # Second enter must come after first release — that's the lock's contract.
    enter_times.sort()
    release_times.sort()
    assert enter_times[1] >= release_times[0] - 0.01  # allow tiny scheduling slop


def test_lock_curation_non_blocking_raises_when_held(tmp_path: Path) -> None:
    path = curation_path(tmp_path, "held")
    write_curation_atomic(path, _make_curation("held"))
    # First lock taken via a thread that sits on it for 0.5s.
    blocker_done = threading.Event()
    holding = threading.Event()

    def _hold() -> None:
        with lock_curation(path):
            holding.set()
            blocker_done.wait(timeout=1.0)

    t = threading.Thread(target=_hold)
    t.start()
    assert holding.wait(timeout=2.0)
    # Non-blocking lock must fail immediately.
    with pytest.raises(BlockingIOError):
        with lock_curation(path, blocking=False):
            pass
    blocker_done.set()
    t.join(timeout=2.0)
