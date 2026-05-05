"""Top-level pytest fixtures for the stemforge test suite.

Hardening Stream B.1 introduces a session-scoped synthetic-song fixture
that any test wanting ground truth can request. The fixture is
deterministic per seed; a separate stability test guards against drift.

Hardening Stream B.4 adds the ``@pytest.mark.live`` marker. Tests
marked ``live`` require a running Ableton (or any dev-Mac integration
out of CI's reach) and are skipped by default. Opt in by setting
``STEMFORGE_LIVE=1``.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from fixtures.synth_song import SynthSongFixture, make_synth_song


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Default-skip ``@pytest.mark.live`` tests unless ``STEMFORGE_LIVE=1``."""
    if os.environ.get("STEMFORGE_LIVE") == "1":
        return
    skip_live = pytest.mark.skip(reason="live tests require STEMFORGE_LIVE=1")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip_live)


@pytest.fixture(scope="session")
def synth_song(tmp_path_factory: pytest.TempPathFactory) -> SynthSongFixture:
    """Session-scoped synthetic 8-bar 4/4 stereo loop @ 120 BPM.

    Rendered once per pytest run into a session tmpdir. Reuse across tests
    is safe because the file is read-only after construction.
    """
    out_dir: Path = tmp_path_factory.mktemp("synth_song")
    return make_synth_song(out_dir / "synth_song.wav")
