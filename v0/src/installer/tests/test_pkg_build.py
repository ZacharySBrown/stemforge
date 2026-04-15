"""Track E — .pkg build smoke tests.

Invokes ``v0/build/build-pkg.sh`` and verifies the resulting .pkg is a valid
xar archive whose expanded contents contain the expected payload files.

These tests are macOS-only (they need ``pkgbuild`` + ``productbuild``).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[4]
BUILD_SCRIPT = REPO_ROOT / "v0" / "build" / "build-pkg.sh"
PKG_OUT = REPO_ROOT / "v0" / "build" / "StemForge-0.0.0.pkg"


def _have(tool: str) -> bool:
    return shutil.which(tool) is not None


pytestmark = [
    pytest.mark.skipif(sys.platform != "darwin", reason="macOS-only packaging"),
    pytest.mark.skipif(
        not (_have("pkgbuild") and _have("productbuild") and _have("pkgutil")),
        reason="Apple packaging tools not available",
    ),
]


@pytest.fixture(scope="module")
def built_pkg(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Invoke build-pkg.sh once, return the produced .pkg path."""
    # Pre-flight: the build script resolves upstream artifacts from this
    # worktree or sibling worktrees. If none of them carry the real binaries
    # we can't meaningfully build, so we skip rather than fail.
    required_names = ["stemforge-native", "StemForge.amxd"]
    for name in required_names:
        if not _find_artifact(name):
            pytest.skip(f"upstream artifact {name!r} not found in any worktree")

    env = os.environ.copy()
    env.setdefault("STEMFORGE_VERSION", "0.0.0")
    result = subprocess.run(
        ["bash", str(BUILD_SCRIPT)],
        env=env,
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"build-pkg.sh failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )
    assert PKG_OUT.exists(), "expected .pkg was not produced"
    return PKG_OUT


def _find_artifact(name: str) -> Path | None:
    local = REPO_ROOT / "v0" / "build" / name
    if local.exists():
        return local
    # Glob local.
    hits = list((REPO_ROOT / "v0" / "build").glob(name))
    if hits:
        return hits[0]
    # Search sibling worktrees.
    for parent in [REPO_ROOT.parent, REPO_ROOT.parent.parent, REPO_ROOT.parent.parent.parent]:
        if not parent.exists():
            continue
        for candidate in parent.glob(f"*/v0/build/{name}"):
            return candidate
    return None


def test_pkg_is_xar_archive(built_pkg: Path) -> None:
    result = subprocess.run(
        ["file", "--brief", str(built_pkg)],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "xar archive" in result.stdout, f"expected xar archive, got: {result.stdout!r}"


def test_pkg_expands_cleanly(built_pkg: Path, tmp_path: Path) -> None:
    expand_dir = tmp_path / "expanded"
    subprocess.run(
        ["pkgutil", "--expand", str(built_pkg), str(expand_dir)],
        check=True,
        capture_output=True,
    )
    assert (expand_dir / "Distribution").exists(), "productbuild distribution file missing"
    assert (expand_dir / "system.pkg").exists(), "system component missing"
    assert (expand_dir / "user.pkg").exists(), "user component missing"


def test_pkg_payload_contains_binary(built_pkg: Path, tmp_path: Path) -> None:
    expand_dir = tmp_path / "expanded"
    subprocess.run(
        ["pkgutil", "--expand-full", str(built_pkg), str(expand_dir)],
        check=True,
        capture_output=True,
    )
    # Payload layout: <expand>/system.pkg/Payload/usr/local/bin/stemforge-native
    sys_payload_bin = expand_dir / "system.pkg" / "Payload" / "usr" / "local" / "bin"
    assert (sys_payload_bin / "stemforge-native").exists(), (
        f"stemforge-native not in system payload; got: {list(sys_payload_bin.iterdir()) if sys_payload_bin.exists() else 'missing dir'}"
    )
    assert (sys_payload_bin / "stemforge-uninstall").exists(), "uninstall helper missing"

    sys_payload_lib = expand_dir / "system.pkg" / "Payload" / "usr" / "local" / "lib"
    ort_dylibs = list(sys_payload_lib.glob("libonnxruntime*.dylib"))
    assert ort_dylibs, "libonnxruntime dylib missing from system payload"


def test_pkg_payload_contains_amxd(built_pkg: Path, tmp_path: Path) -> None:
    expand_dir = tmp_path / "expanded"
    subprocess.run(
        ["pkgutil", "--expand-full", str(built_pkg), str(expand_dir)],
        check=True,
        capture_output=True,
    )
    staging = expand_dir / "user.pkg" / "Payload" / "tmp" / "stemforge-staging"
    assert (staging / "StemForge.amxd").exists(), "StemForge.amxd missing from user payload"


def test_pkg_postinstall_script_present(built_pkg: Path, tmp_path: Path) -> None:
    expand_dir = tmp_path / "expanded"
    subprocess.run(
        ["pkgutil", "--expand-full", str(built_pkg), str(expand_dir)],
        check=True,
        capture_output=True,
    )
    postinstall = expand_dir / "user.pkg" / "Scripts" / "postinstall"
    assert postinstall.exists(), "postinstall script missing from user pkg"
    assert os.access(postinstall, os.X_OK), "postinstall is not executable"
