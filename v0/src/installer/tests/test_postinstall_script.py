"""Static + dry-run checks for the postinstall / uninstall shell scripts."""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[4]
POSTINSTALL = REPO_ROOT / "v0" / "src" / "installer" / "scripts" / "postinstall"
UNINSTALL = REPO_ROOT / "v0" / "build" / "uninstall.sh"
INSTALL_SH = REPO_ROOT / "v0" / "build" / "install.sh"
BUILD_SH = REPO_ROOT / "v0" / "build" / "build-pkg.sh"
SIGN_SH = REPO_ROOT / "v0" / "build" / "sign-notarize-pkg.sh"


@pytest.mark.parametrize(
    "script",
    [POSTINSTALL, UNINSTALL, INSTALL_SH, BUILD_SH, SIGN_SH],
    ids=lambda p: p.name,
)
def test_shell_syntax(script: Path) -> None:
    """`bash -n` parses without error."""
    assert script.exists(), f"missing script: {script}"
    result = subprocess.run(
        ["bash", "-n", str(script)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"{script.name} syntax error:\n{result.stderr}"


@pytest.mark.parametrize(
    "script",
    [POSTINSTALL, UNINSTALL, INSTALL_SH, BUILD_SH, SIGN_SH],
    ids=lambda p: p.name,
)
def test_shebang(script: Path) -> None:
    with script.open("rb") as f:
        first = f.readline()
    assert first.startswith(b"#!/bin/bash") or first.startswith(b"#!/usr/bin/env bash"), (
        f"{script.name} missing bash shebang"
    )


def test_postinstall_has_safe_mode() -> None:
    content = POSTINSTALL.read_text()
    assert "set -e" in content, "postinstall should 'set -e'"
    assert "detect_ableton_lib" in content, "postinstall must detect Ableton lib"
    # Guard against regressions: both destinations must be created.
    assert "Presets/Audio Effects/Max Audio Effect" in content
    assert "/Templates" in content


def test_postinstall_als_is_conditional() -> None:
    """D's artifact is optional until skeleton.als lands."""
    content = POSTINSTALL.read_text()
    # Must check for file existence before copying the .als.
    assert '[ -f "$STAGING/StemForge.als" ]' in content


def test_uninstall_preserves_user_data() -> None:
    """Uninstall must not *execute* rm -rf against user data dirs.

    The script is allowed to print those commands as advisory hints (inside
    an echo or heredoc), so we check each non-comment, non-echo line.
    """
    forbidden_targets = [
        "~/stemforge",
        '"$HOME/stemforge"',
        "~/Library/Application Support/StemForge",
    ]
    for lineno, raw in enumerate(UNINSTALL.read_text().splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        # Hints are always inside echo/printf — skip those.
        if line.startswith(("echo ", "printf ")):
            continue
        if "rm -rf" in line:
            for target in forbidden_targets:
                assert target not in line, (
                    f"uninstall.sh line {lineno} executes destructive rm -rf against "
                    f"user data: {line!r}"
                )


@pytest.mark.skipif(sys.platform != "darwin", reason="dry-run uses macOS paths")
def test_postinstall_dryrun(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Execute postinstall with $HOME pointed at a temp dir + mock staging.

    Validates directory creation + conditional .als skip when the .als isn't
    staged. We do NOT validate Ableton detection here — that requires a real
    Preferences.cfg and is exercised by integration tests.
    """
    if not shutil.which("bash"):
        pytest.skip("bash not available")

    staging = Path("/tmp") / "stemforge-staging"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    # Stage a fake .amxd (any bytes — postinstall just cp's it).
    (staging / "StemForge.amxd").write_bytes(b"dummy amxd")
    # Deliberately DO NOT stage StemForge.als — validates conditional path.

    fake_home = tmp_path / "home"
    fake_home.mkdir()

    env = os.environ.copy()
    env["HOME"] = str(fake_home)
    env["USER"] = os.environ.get("USER", "testuser")

    # Ensure postinstall is executable.
    POSTINSTALL.chmod(POSTINSTALL.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

    result = subprocess.run(
        ["bash", str(POSTINSTALL)],
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"postinstall failed (rc={result.returncode})\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )

    # Default Ableton lib path (no Preferences.cfg -> fallback).
    lib = fake_home / "Music" / "Ableton" / "User Library"
    assert (lib / "Presets" / "Audio Effects" / "Max Audio Effect" / "StemForge.amxd").exists(), (
        "postinstall did not place .amxd in Ableton User Library"
    )
    assert (lib / "Templates").is_dir(), "Templates dir not created"
    assert not (lib / "Templates" / "StemForge.als").exists(), (
        "no .als was staged, so none should be installed"
    )

    support = fake_home / "Library" / "Application Support" / "StemForge"
    assert (support / "models").is_dir()
    assert (support / "bin").is_dir()

    for sub in ("inbox", "processed", "logs"):
        assert (fake_home / "stemforge" / sub).is_dir(), f"missing ~/stemforge/{sub}"

    # Staging must be wiped.
    assert not staging.exists(), "postinstall must clean up /tmp/stemforge-staging"
