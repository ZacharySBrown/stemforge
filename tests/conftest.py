"""Top-level pytest fixtures for the stemforge test suite.

Hardening Stream B.1 introduces a session-scoped synthetic-song fixture
that any test wanting ground truth can request. The fixture is
deterministic per seed; a separate stability test guards against drift.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fixtures.synth_song import SynthSongFixture, make_synth_song


@pytest.fixture(scope="session")
def synth_song(tmp_path_factory: pytest.TempPathFactory) -> SynthSongFixture:
    """Session-scoped synthetic 8-bar 4/4 stereo loop @ 120 BPM.

    Rendered once per pytest run into a session tmpdir. Reuse across tests
    is safe because the file is read-only after construction.
    """
    out_dir: Path = tmp_path_factory.mktemp("synth_song")
    return make_synth_song(out_dir / "synth_song.wav")
