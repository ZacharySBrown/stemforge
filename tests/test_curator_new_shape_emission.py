"""Sentinel tests: every forge writer in stemforge/cli.py emits the new
two-file shape (auto_curation_manifest.json + arrangement_manifest.json)
alongside the legacy curated/manifest.json.

These are static / wiring tests because the heavy commands (forge,
re-anchor, reslice-curated) require Demucs + real audio and are marked
@pytest.mark.live for the integration suite. The sentinels lock the
call-site wiring in place so future refactors can't silently drop the
new-shape emission.
"""

from __future__ import annotations

import re
from pathlib import Path

CLI_PATH = Path(__file__).resolve().parent.parent / "stemforge" / "cli.py"


def test_forge_command_imports_new_writers():
    """The forge command imports both write_auto_curation and write_arrangement."""
    src = CLI_PATH.read_text()
    # Two import sites: inline path + --curation production path
    assert src.count("write_auto_curation") >= 2, (
        "forge must call write_auto_curation in both inline and --curation branches"
    )
    assert src.count("write_arrangement") >= 2, (
        "forge must call write_arrangement in both inline and --curation branches"
    )


def test_re_anchor_emits_new_shape_when_curated_exists():
    """re-anchor refreshes auto_curation_manifest.json + arrangement_manifest.json."""
    src = CLI_PATH.read_text()
    # Re-anchor body contains the new-shape writer calls.
    # Locate the re-anchor function and assert the writers appear within it.
    match = re.search(
        r"def re_anchor\(.*?\n(.+?)\n@cli\.command",
        src,
        re.DOTALL,
    )
    assert match, "re_anchor function body not found"
    body = match.group(1)
    assert "write_auto_curation" in body, (
        "re-anchor must call write_auto_curation when curated/ exists"
    )
    assert "write_arrangement" in body, "re-anchor must call write_arrangement when curated/ exists"


def test_reslice_curated_emits_new_shape():
    """reslice-curated refreshes the new-shape manifests after reslicing."""
    src = CLI_PATH.read_text()
    match = re.search(
        r"def reslice_curated\(.*?\n(.+?)\n@cli\.command",
        src,
        re.DOTALL,
    )
    assert match, "reslice_curated function body not found"
    body = match.group(1)
    assert "write_auto_curation" in body
    assert "write_arrangement" in body


def test_migrate_forge_subcommand_registered():
    """stemforge migrate-forge is a registered subcommand."""
    src = CLI_PATH.read_text()
    assert '@cli.command("migrate-forge")' in src


def test_re_curate_subcommand_registered():
    """stemforge re-curate is a registered subcommand."""
    src = CLI_PATH.read_text()
    assert '@cli.command("re-curate")' in src


def test_forge_emits_manifest_hash_in_complete_event():
    """The forge command's 'complete' event includes manifest_hash so M4L
    can store the reference for stale detection."""
    src = CLI_PATH.read_text()
    # The legacy inline path's complete event must carry the new fields.
    # Look for "complete" event emit with manifest_hash.
    assert "manifest_hash=_fm.manifest_hash" in src, (
        "forge's 'complete' event must publish manifest_hash for stale-detection wiring"
    )
