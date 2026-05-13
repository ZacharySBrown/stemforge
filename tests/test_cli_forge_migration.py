"""CliRunner tests for Phase 1A configurator CLI commands.

- `stemforge migrate-forge <slug>` round-trip + error handling.
- `stemforge re-curate <slug>` produces fresh manifest_hash when params
  change (stems unchanged).
- `stemforge forge --help` advertises the new flags / behavior.
- `stemforge migrate-forge --help` smoke.

`re-curate` shells out to `v0/src/stemforge_curate_bars.py` (which depends
on librosa + the full split output) — for the CLI-level fast test we
patch the subprocess call and pre-stage a synthetic legacy manifest.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from stemforge.cli import cli
from stemforge.configurator.schemas import ForgeManifest, compute_manifest_hash
from stemforge.forge.manifest_io import (
    ARRANGEMENT_FILENAME,
    AUTO_CURATION_FILENAME,
)


FIXTURES = Path(__file__).resolve().parent / "fixtures" / "forges"


def _seed_legacy_forge(forge_root: Path, *, source_fixture: str = "sample-forge") -> Path:
    """Stage a legacy forge dir under ``forge_root/<slug>/`` derived from a
    Phase 0 new-shape fixture. Returns the forge dir (containing
    ``curated/manifest.json``).
    """
    fixture_new = json.loads(
        (FIXTURES / source_fixture / "auto_curation_manifest.json").read_text()
    )
    forge_dir = forge_root / source_fixture
    (forge_dir / "curated").mkdir(parents=True)
    # Build legacy manifest mirror of the new shape's clips.
    LABEL_TO_LEGACY = {"drum": "drums", "bass": "bass", "vocal": "vocals", "other": "other"}
    stems: dict[str, list] = {}
    for clip in fixture_new["clips"]:
        legacy_stem = LABEL_TO_LEGACY[clip["stem"]]
        stems.setdefault(legacy_stem, []).append(
            {
                "position": len(stems.get(legacy_stem, [])) + 1,
                "clip_id": clip["clip_id"],
                "file": clip["audio_path"],
                "duration_bars": clip["duration_bars"],
            }
        )
    legacy = {
        "track": fixture_new["forge_slug"],
        "source_audio": fixture_new["source_audio"],
        "strategy": "max-diversity",
        "n_bars": fixture_new["clips"][0]["duration_bars"],
        "bpm": fixture_new["bpm"],
        "first_downbeat_sec": fixture_new["first_downbeat_sec"],
        "time_signature_numerator": 4,
        "stems": stems,
    }
    (forge_dir / "curated" / "manifest.json").write_text(json.dumps(legacy))
    # Also drop a minimal stems.json so re-curate can find it.
    (forge_dir / "stems.json").write_text(
        json.dumps(
            {
                "track_name": fixture_new["forge_slug"],
                "source_file": fixture_new["source_audio"],
                "backend": "demucs",
                "bpm": fixture_new["bpm"],
                "beat_count": 0,
                "stems": [],
                "pipeline": "default",
                "processed_at": "2026-05-13T00:00:00",
            }
        )
    )
    return forge_dir


# ── migrate-forge ────────────────────────────────────────────────────────────


def test_migrate_forge_help_loads():
    runner = CliRunner()
    result = runner.invoke(cli, ["migrate-forge", "--help"])
    assert result.exit_code == 0
    assert "auto_curation_manifest" in result.output
    assert "arrangement_manifest" in result.output


def test_migrate_forge_round_trip_against_breaks_n_beats_fixture(tmp_path: Path):
    """End-to-end: stage a legacy curated/manifest.json built from the
    breaks-n-beats-deck fixture, run `stemforge migrate-forge <path>`,
    assert both new-shape files exist with valid content and matching
    manifest_hash. The legacy file is preserved (compat window).
    """
    forge_dir = _seed_legacy_forge(tmp_path, source_fixture="breaks-n-beats-deck")
    runner = CliRunner()
    result = runner.invoke(cli, ["migrate-forge", str(forge_dir)])
    assert result.exit_code == 0, result.output

    fm_path = forge_dir / AUTO_CURATION_FILENAME
    am_path = forge_dir / ARRANGEMENT_FILENAME
    assert fm_path.exists()
    assert am_path.exists()
    # Legacy left in place for one-release compat
    assert (forge_dir / "curated" / "manifest.json").exists()

    new_fm = json.loads(fm_path.read_text())
    fixture_fm = json.loads(
        (FIXTURES / "breaks-n-beats-deck" / "auto_curation_manifest.json").read_text()
    )
    assert new_fm["forge_slug"] == "breaks-n-beats-deck"
    assert new_fm["bpm"] == fixture_fm["bpm"]
    assert new_fm["first_downbeat_sec"] == fixture_fm["first_downbeat_sec"]
    assert new_fm["schema_version"] == 1
    assert len(new_fm["clips"]) == len(fixture_fm["clips"])
    # manifest_hash is canonical hash of clips
    assert new_fm["manifest_hash"] == compute_manifest_hash(new_fm["clips"])
    # Round-trip through Pydantic
    ForgeManifest(**new_fm)


def test_migrate_forge_idempotent_already_migrated(tmp_path: Path):
    """Running migrate-forge twice is a no-op the second time."""
    forge_dir = _seed_legacy_forge(tmp_path)
    runner = CliRunner()
    r1 = runner.invoke(cli, ["migrate-forge", str(forge_dir)])
    assert r1.exit_code == 0, r1.output
    # Drop the legacy file to simulate post-cleanup state
    (forge_dir / "curated" / "manifest.json").unlink()
    r2 = runner.invoke(cli, ["migrate-forge", str(forge_dir)])
    assert r2.exit_code == 0, r2.output
    assert "already on new shape" in r2.output


def test_migrate_forge_missing_legacy_clean_error(tmp_path: Path):
    """No legacy manifest → ClickException with a clean message, not stacktrace."""
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    runner = CliRunner()
    result = runner.invoke(cli, ["migrate-forge", str(empty_dir)])
    assert result.exit_code != 0
    assert (
        "no curated/manifest.json" in result.output.lower() or "no curated" in result.output.lower()
    )


def test_migrate_forge_corrupt_legacy_clean_error(tmp_path: Path):
    forge_dir = tmp_path / "broken"
    (forge_dir / "curated").mkdir(parents=True)
    (forge_dir / "curated" / "manifest.json").write_text("{ not json")
    runner = CliRunner()
    result = runner.invoke(cli, ["migrate-forge", str(forge_dir)])
    assert result.exit_code != 0
    assert "malformed" in result.output.lower() or "invalid" in result.output.lower()


# ── re-curate ────────────────────────────────────────────────────────────────


def test_re_curate_help_loads():
    runner = CliRunner()
    result = runner.invoke(cli, ["re-curate", "--help"])
    assert result.exit_code == 0
    assert "Re-run auto-curation" in result.output
    assert "stale" in result.output.lower()


def test_re_curate_missing_stems_clean_error(tmp_path: Path):
    forge_dir = tmp_path / "noforge"
    forge_dir.mkdir()
    runner = CliRunner()
    result = runner.invoke(cli, ["re-curate", str(forge_dir)])
    assert result.exit_code != 0
    assert "stems.json" in result.output


def test_re_curate_produces_fresh_manifest_hash_when_params_change(tmp_path: Path, monkeypatch):
    """Stems are unchanged but the curator's strategy changes → new
    auto_curation_manifest.json must have a different manifest_hash.

    We stub out the subprocess call to the v0 curate script (which would
    otherwise require librosa + real audio) and instead emit a synthetic
    legacy manifest whose contents differ when the strategy differs. The
    point of the test is: re-curate REWRITES the new-shape file and
    refreshes the hash from the (potentially new) clips.
    """
    forge_dir = _seed_legacy_forge(tmp_path, source_fixture="sample-forge")

    # Initial state: write the new shape directly so we have a baseline hash.
    runner = CliRunner()
    initial = runner.invoke(cli, ["migrate-forge", str(forge_dir)])
    assert initial.exit_code == 0, initial.output
    baseline_fm = json.loads((forge_dir / AUTO_CURATION_FILENAME).read_text())

    # Patch subprocess.run inside the cli module to simulate the curate
    # script overwriting the legacy file with a different clip set.
    import stemforge.cli as cli_mod

    fake_legacy = json.loads((forge_dir / "curated" / "manifest.json").read_text())
    # Mutate: change a clip's file path so the resulting hash is different.
    first_stem = next(iter(fake_legacy["stems"].keys()))
    fake_legacy["stems"][first_stem][0]["file"] = "curated_audio/MUTATED.wav"
    fake_legacy["strategy"] = "rhythm-taxonomy"
    fake_legacy["bpm"] = baseline_fm["bpm"]  # keep bpm stable

    class _FakeResult:
        returncode = 0

    def _fake_run(*args, **kwargs):
        (forge_dir / "curated" / "manifest.json").write_text(json.dumps(fake_legacy))
        return _FakeResult()

    monkeypatch.setattr(cli_mod.subprocess, "run", _fake_run)

    result = runner.invoke(cli, ["re-curate", str(forge_dir), "--strategy", "rhythm-taxonomy"])
    assert result.exit_code == 0, result.output

    refreshed_fm = json.loads((forge_dir / AUTO_CURATION_FILENAME).read_text())
    assert refreshed_fm["manifest_hash"] != baseline_fm["manifest_hash"], (
        "re-curate must produce a new manifest_hash when clips change"
    )
    # Schema invariants preserved
    assert refreshed_fm["schema_version"] == 1
    assert refreshed_fm["forge_slug"] == baseline_fm["forge_slug"]


# ── Sentinel: forge --help still loads + lists new subcommands in group help


def test_cli_group_help_lists_migrate_forge_and_re_curate():
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "migrate-forge" in result.output
    assert "re-curate" in result.output
