"""Fresh-install validation harness (Track H / Workstream W4).

Validates that the W2-built ``v0/build/StemForge-0.0.0.pkg`` contains
everything a fresh Mac needs to run StemForge end-to-end.

Two tiers:

* **Tier 1 (default):** ``pkgutil --expand-full`` into a session-scoped
  temp dir and assert on layout. Fast (~1 s per run after first extract),
  no sudo, no real install side-effects. This is what CI + local
  ``pytest`` runs see.
* **Tier 2 (opt-in):** ``sudo installer -pkg ... -target $TMPROOT`` against
  a throwaway root, then runs the installed binary's ``--version``. Gated
  on ``STEMFORGE_INSTALL_E2E=1`` because it needs sudo and is slow.

The critical assertion is ``test_user_staging_has_fused_onnx`` — a sha256
mismatch on ``htdemucs_ft_fused.onnx`` means the fusion contract (no
external .data sidecar, single inline file — CoreML EP requirement, see
``v0/state/A/fusion_succeeded.md``) was broken during packaging.

Run:

.. code-block:: bash

   uv run pytest v0/tests/test_pkg_install.py -v
   STEMFORGE_INSTALL_E2E=1 uv run pytest v0/tests/test_pkg_install.py -v
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

# v0/tests/test_pkg_install.py → parents[2] is the worktree root.
REPO = Path(__file__).resolve().parents[2]
V0 = REPO / "v0"
PKG_PATH = V0 / "build" / "StemForge-0.0.0.pkg"
PKG_MIN_BYTES = 100 * 1024 * 1024  # 100 MB floor; real pkg is ~409 MB.
FUSED_ONNX_SHA256 = (
    "71828190efe191a622f9c9273471de1458fe0e108f277872d43c5c81cbe29ce9"
)
PKGUTIL = "/usr/sbin/pkgutil"


# ---------------------------------------------------------------------------
# Fixtures (module-local; do NOT extend the shared v0/tests/conftest.py)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def pkg_path() -> Path:
    """Resolve the built pkg or skip with a clear remediation message."""
    if not PKG_PATH.exists():
        pytest.skip(
            f"{PKG_PATH} not found — run "
            "`bash v0/build/build-pkg.sh` first (W2 artifact is gitignored "
            "and must be built locally before W4 tests can run)."
        )
    return PKG_PATH


@pytest.fixture(scope="session")
def expanded_pkg(pkg_path: Path, tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Session-scoped `pkgutil --expand-full` of the pkg.

    Returns the expand dir. Shared across all tier-1 tests so a 409 MB pkg
    is only extracted once per pytest session.
    """
    expand_root = tmp_path_factory.mktemp("stemforge_pkg_expand")
    expand_dir = expand_root / "pkg"
    # pkgutil insists the output dir does NOT already exist.
    if expand_dir.exists():
        shutil.rmtree(expand_dir)
    result = subprocess.run(
        [PKGUTIL, "--expand-full", str(pkg_path), str(expand_dir)],
        capture_output=True,
        text=True,
        timeout=600,
    )
    if result.returncode != 0:
        pytest.fail(
            f"pkgutil --expand-full failed (rc={result.returncode})\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
    return expand_dir


@pytest.fixture(scope="session")
def system_payload(expanded_pkg: Path) -> Path:
    return expanded_pkg / "system.pkg" / "Payload"


@pytest.fixture(scope="session")
def user_payload(expanded_pkg: Path) -> Path:
    return expanded_pkg / "user.pkg" / "Payload"


@pytest.fixture(scope="session")
def user_staging(user_payload: Path) -> Path:
    return user_payload / "tmp" / "stemforge-staging"


@pytest.fixture(scope="session")
def user_scripts(expanded_pkg: Path) -> Path:
    return expanded_pkg / "user.pkg" / "Scripts"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _is_executable(path: Path) -> bool:
    mode = path.stat().st_mode
    return bool(mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH))


def _sha256_of(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Tier 1: expand-based assertions (default, fast, no sudo)
# ---------------------------------------------------------------------------


def test_pkg_exists(pkg_path: Path) -> None:
    """W4.1 — pkg artifact is present and non-trivially sized."""
    assert pkg_path.is_file(), f"{pkg_path} is not a regular file"
    size = pkg_path.stat().st_size
    assert size >= PKG_MIN_BYTES, (
        f"{pkg_path.name} is {size} bytes — expected at least "
        f"{PKG_MIN_BYTES} bytes. A pkg this small almost certainly "
        "means the 697 MB fused ONNX didn't make it into the payload."
    )


def test_pkg_expands_cleanly(expanded_pkg: Path) -> None:
    """W4.2 — pkgutil --expand-full succeeds and yields both sub-pkgs."""
    assert expanded_pkg.is_dir(), f"{expanded_pkg} is not a dir"
    # productbuild always produces this pair plus a Distribution file.
    assert (expanded_pkg / "Distribution").is_file(), "Distribution missing"
    assert (expanded_pkg / "system.pkg").is_dir(), "system.pkg missing"
    assert (expanded_pkg / "user.pkg").is_dir(), "user.pkg missing"


def test_system_payload_has_binary(system_payload: Path) -> None:
    """W4.3 — /usr/local/bin/stemforge-native is staged and executable."""
    binary = system_payload / "usr" / "local" / "bin" / "stemforge-native"
    assert binary.is_file(), f"{binary} missing or not a regular file"
    assert _is_executable(binary), f"{binary} is not executable"


def test_system_payload_has_dylib(system_payload: Path) -> None:
    """W4.4 — /usr/local/lib/libonnxruntime.*.dylib is staged."""
    lib_dir = system_payload / "usr" / "local" / "lib"
    assert lib_dir.is_dir(), f"{lib_dir} missing"
    matches = list(lib_dir.glob("libonnxruntime.*.dylib"))
    assert matches, (
        f"No libonnxruntime.*.dylib found under {lib_dir}. "
        f"Contents: {sorted(p.name for p in lib_dir.iterdir())}"
    )


def test_system_payload_has_uninstaller(system_payload: Path) -> None:
    """W4.5 — stemforge-uninstall is staged and executable."""
    uninstall = system_payload / "usr" / "local" / "bin" / "stemforge-uninstall"
    assert uninstall.is_file(), f"{uninstall} missing"
    assert _is_executable(uninstall), f"{uninstall} is not executable"


def test_user_staging_has_amxd(user_staging: Path) -> None:
    """W4.6 — StemForge.amxd is staged with valid Max 'ampf' magic."""
    amxd = user_staging / "StemForge.amxd"
    assert amxd.is_file(), f"{amxd} missing"
    size = amxd.stat().st_size
    assert size >= 1024, f"{amxd} is only {size} bytes — looks empty"
    with amxd.open("rb") as f:
        head = f.read(4)
    assert head == b"ampf", (
        f"{amxd} does not start with Max amxd magic bytes 'ampf' "
        f"(got {head!r}). The file is probably corrupt or swapped."
    )


def test_user_staging_has_bridge_js(user_staging: Path) -> None:
    """W4.7 — stemforge_bridge.v0.js is staged and is the real bridge."""
    bridge = user_staging / "stemforge_bridge.v0.js"
    assert bridge.is_file(), f"{bridge} missing"
    text = bridge.read_text(encoding="utf-8")
    assert "spawn" in text, (
        f"{bridge.name} does not reference `spawn` — looks like a shim or "
        "placeholder. The bridge must drive a child process via "
        "child_process.spawn."
    )


def test_user_staging_has_loader_js(user_staging: Path) -> None:
    """W4.8 — stemforge_loader.v0.js is staged."""
    loader = user_staging / "stemforge_loader.v0.js"
    assert loader.is_file(), f"{loader} missing"
    assert loader.stat().st_size > 0, f"{loader} is empty"


def test_user_staging_has_manifest(user_staging: Path) -> None:
    """W4.9 — models/manifest.json parses and has a `models` key."""
    manifest_path = user_staging / "models" / "manifest.json"
    assert manifest_path.is_file(), f"{manifest_path} missing"
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert "models" in data, (
        f"manifest.json is missing top-level 'models' key. "
        f"Keys present: {sorted(data.keys())}"
    )


def test_user_staging_has_fused_onnx(user_staging: Path) -> None:
    """W4.10 — htdemucs_ft_fused.onnx is staged AND sha256 matches.

    This is the critical fusion-contract check: if the sha drifts, the
    packaging step either corrupted the file or grabbed a non-fused
    variant. CoreML EP relies on this exact bytestream (no external
    weights, single inline file). See v0/state/A/fusion_succeeded.md.
    """
    fused = user_staging / "models" / "htdemucs_ft" / "htdemucs_ft_fused.onnx"
    assert fused.is_file(), f"{fused} missing"
    actual = _sha256_of(fused)
    assert actual == FUSED_ONNX_SHA256, (
        "Fused ONNX sha256 drifted!\n"
        f"  expected: {FUSED_ONNX_SHA256}\n"
        f"  actual:   {actual}\n"
        "Packaging either corrupted the file or substituted a different "
        "fused variant. Do NOT patch this sha — fix the source artifact "
        "and rebuild via v0/build/build-pkg.sh."
    )


def test_user_staging_has_no_data_sidecar(user_staging: Path) -> None:
    """W4.11 — no external-weight .data sidecars anywhere under models/.

    CoreML EP MLProgram compile silently falls back to CPU (SystemError 20)
    when it encounters ONNX models with external-weight sidecars. v0 ships
    only inline models. A .data file here would negate the whole point of
    the fusion pipeline. See v0/state/A/fusion_succeeded.md.
    """
    models_root = user_staging / "models"
    assert models_root.is_dir(), f"{models_root} missing"
    sidecars = [p for p in models_root.rglob("*.data") if p.is_file()]
    assert not sidecars, (
        "Found external-weight .data sidecar(s) in user staging payload:\n"
        + "\n".join(f"  - {p.relative_to(models_root)}" for p in sidecars)
        + "\nCoreML EP will silently fall back to CPU with these present. "
        "Re-fuse with onnx.save(..., save_as_external_data=False)."
    )


def test_user_staging_has_als(user_staging: Path) -> None:
    """W6 — StemForge.als is present in staging and is a valid gzipped Ableton set."""
    als = user_staging / "StemForge.als"
    assert als.exists(), "StemForge.als missing from staging"
    assert als.stat().st_size > 512, f"implausibly small: {als.stat().st_size}"
    import gzip
    import xml.etree.ElementTree as ET
    with gzip.open(als, "rb") as f:
        tree = ET.parse(f)
    root_tag = tree.getroot().tag.rsplit("}", 1)[-1]
    assert root_tag == "Ableton", f"unexpected root: {root_tag}"


def test_postinstall_present_and_executable(user_scripts: Path) -> None:
    """W4.12 — postinstall script exists, is +x, and has expected logic."""
    postinstall = user_scripts / "postinstall"
    assert postinstall.is_file(), f"{postinstall} missing"
    assert _is_executable(postinstall), f"{postinstall} is not executable"

    text = postinstall.read_text(encoding="utf-8")
    # Must reference the JS bridge it's relocating.
    assert "stemforge_bridge.v0.js" in text, (
        "postinstall does not mention stemforge_bridge.v0.js — it would "
        "fail to relocate the bridge next to StemForge.amxd."
    )
    # Must reference the Application Support models destination var.
    assert "MODELS_DEST" in text, (
        "postinstall does not set up $MODELS_DEST — models relocation "
        "into ~/Library/Application Support/StemForge/models would be "
        "skipped."
    )
    # Must drop privileges for the warmup so the CoreML cache lands in
    # the target user's Library and not /var/root.
    assert "sudo -u" in text, (
        "postinstall does not `sudo -u` the warmup step. Running warmup "
        "as root places the CoreML cache in /var/root/Library/Caches, "
        "which means the first user split still pays the cold-compile "
        "cost."
    )


# ---------------------------------------------------------------------------
# Tier 2: real installer run (opt-in, gated, slow)
# ---------------------------------------------------------------------------


E2E_ENV_VAR = "STEMFORGE_INSTALL_E2E"


@pytest.mark.skipif(
    os.environ.get(E2E_ENV_VAR) != "1",
    reason=(
        f"tier-2 e2e install test is gated on {E2E_ENV_VAR}=1 "
        "(requires sudo + takes ~1 min)"
    ),
)
def test_pkg_installs_end_to_end(pkg_path: Path, tmp_path: Path) -> None:
    """W4 tier-2 — `sudo installer` into a throwaway root + run the binary.

    This is NOT part of the default suite. It requires sudo (which may
    prompt for a password depending on local sudoers config) and a full
    pkg install, which takes ~30-60 s on modern hardware.
    """
    tmproot = tmp_path / "install-root"
    tmproot.mkdir()

    install = subprocess.run(
        [
            "sudo", "installer",
            "-pkg", str(pkg_path),
            "-target", str(tmproot),
        ],
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert install.returncode == 0, (
        f"`sudo installer` failed (rc={install.returncode})\n"
        f"stdout: {install.stdout}\nstderr: {install.stderr}"
    )

    installed_bin = tmproot / "usr" / "local" / "bin" / "stemforge-native"
    assert installed_bin.is_file(), (
        f"{installed_bin} not installed under {tmproot}. "
        f"Tree: {sorted(str(p) for p in tmproot.rglob('stemforge*'))}"
    )

    version = subprocess.run(
        [str(installed_bin), "--version"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    # Don't require rc==0 strictly (some CLIs print version with rc!=0),
    # but the binary must produce output mentioning the version string.
    combined = (version.stdout or "") + (version.stderr or "")
    assert "0.0.0" in combined, (
        f"--version output does not mention 0.0.0.\n"
        f"rc={version.returncode}\nstdout={version.stdout}\n"
        f"stderr={version.stderr}"
    )
