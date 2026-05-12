"""CliRunner tests for two CLI feature additions:

  1. ``stemforge split --time-sig N/D`` (parity with ``forge`` /
     ``curate-bars``). Only verifies parser-level acceptance + rejection.
     The librosa/prechop semantics it overrides are already covered by
     ``tests/test_prechop.py`` and ``tests/test_pipelines.py``.

  2. ``stemforge ep133-clear-pad`` — a new subcommand that writes
     ``{"sym":0}`` to a pad's fileId to unassign its sample slot.
     Dry-run path is byte-checked; live path is hardware-pending.

The adjacent ``conftest.py`` handles worktree-aware ``sys.path`` setup
so the ``stemforge`` import below resolves to this worktree's source —
not the editable install registered against the main repo path.
"""

from __future__ import annotations

from click.testing import CliRunner

from stemforge.cli import cli


# ── Task 1: split --time-sig ─────────────────────────────────────────────────


def test_split_help_advertises_time_sig_flag():
    """--help mentions --time-sig with the librosa-fallback caveat."""
    runner = CliRunner()
    result = runner.invoke(cli, ["split", "--help"])
    assert result.exit_code == 0, result.output
    out = result.output
    assert "--time-sig" in out
    # The flag's help must NOT overpromise beat-this support — issue file's
    # "What 'fix' looks like" section 2 explicitly calls this out.
    assert "beat-this" in out or "librosa" in out


def test_split_time_sig_valid_value_accepted_by_parser():
    """``--time-sig 7/4`` is accepted at parse time (no 'No such option' error).

    We invoke with a non-existent audio file so the command fails *after*
    argument parsing, at the click.Path(exists=True) check on AUDIO_FILE.
    That gives us a clean parse/no-parse signal without booting Demucs.
    """
    runner = CliRunner()
    result = runner.invoke(cli, ["split", "/nonexistent/track.wav", "--time-sig", "7/4"])
    # We expect failure (file doesn't exist), but NOT a "no such option"
    # failure. Click's error for an unknown option is exit_code 2 with a
    # specific message; here we want the *file-does-not-exist* error.
    assert "No such option" not in result.output, result.output
    assert "AUDIO_FILE" in result.output or "does not exist" in result.output, result.output


def test_split_time_sig_invalid_value_rejected_no_slash():
    """``--time-sig 7`` (missing slash) is rejected with a clear message."""
    runner = CliRunner()
    # Use an existent dummy file so we get past click.Path(exists=True) and
    # land on our own BadParameter check. The standard click test runner's
    # isolated_filesystem gives us a writable tmp cwd.
    with runner.isolated_filesystem():
        from pathlib import Path

        Path("dummy.wav").write_bytes(b"RIFF\x00\x00\x00\x00WAVE")
        result = runner.invoke(cli, ["split", "dummy.wav", "--time-sig", "7"])
    assert result.exit_code != 0
    assert "--time-sig" in result.output
    assert "N/D" in result.output or "must be N/D" in result.output


def test_split_time_sig_invalid_value_rejected_non_numeric():
    """``--time-sig abc`` is rejected before any pipeline runs."""
    runner = CliRunner()
    with runner.isolated_filesystem():
        from pathlib import Path

        Path("dummy.wav").write_bytes(b"RIFF\x00\x00\x00\x00WAVE")
        result = runner.invoke(cli, ["split", "dummy.wav", "--time-sig", "abc"])
    assert result.exit_code != 0
    assert "--time-sig" in result.output


# ── Task 2: ep133-clear-pad ──────────────────────────────────────────────────


def test_ep133_clear_pad_help_runs():
    runner = CliRunner()
    result = runner.invoke(cli, ["ep133-clear-pad", "--help"])
    assert result.exit_code == 0, result.output
    assert "PROJECT_SLOT" in result.output
    assert "PAD" in result.output
    assert "--dry-run" in result.output
    # Both pad-coordinate forms must be documented in --help per the brief.
    assert "A1" in result.output or "letter" in result.output.lower()
    assert "1..48" in result.output or "numeric" in result.output.lower()


def test_ep133_clear_pad_dry_run_emits_expected_bytes_for_A1():
    """Dry-run output contains the SysEx frame for project=8, A1.

    Pad fileId formula (verified in tests/ep133/test_assign_pad.py):
        PAD_BASE + (project-1)*PROJECT_STRIDE + group_idx*GROUP_STRIDE + pad_num
        = 3200 + 7*1000 + 0 + 1 = 10201 = 0x27D9

    Payload layout: 07 01 [file_id:u16 BE] {"sym":0} \\0
    Expected raw payload bytes (before 7-bit packing):
        07 01 27 D9 7B 22 73 79 6D 22 3A 30 7D 00
    """
    runner = CliRunner()
    result = runner.invoke(cli, ["ep133-clear-pad", "8", "A1", "--dry-run"])
    assert result.exit_code == 0, result.output
    # Raw payload hex (unpacked) must be present in the dry-run output.
    assert "070127d97b2273796d223a307d00" in result.output, result.output
    # Frame begins F0 00 20 76 (TE manufacturer header).
    assert "f0002076" in result.output
    # Frame ends F7.
    assert "f7" in result.output
    assert "no MIDI I/O" in result.output


def test_ep133_clear_pad_dry_run_numeric_form_equivalence():
    """Numeric PAD=1 produces identical payload to letter form A1."""
    runner = CliRunner()
    r_letter = runner.invoke(cli, ["ep133-clear-pad", "8", "A1", "--dry-run"])
    r_numeric = runner.invoke(cli, ["ep133-clear-pad", "8", "1", "--dry-run"])
    assert r_letter.exit_code == 0
    assert r_numeric.exit_code == 0

    # Pull the raw-payload hex line out of each run and compare them.
    def _payload_hex(output: str) -> str:
        for line in output.splitlines():
            if "payload (raw):" in line:
                return line.split(":", 1)[1].strip()
        raise AssertionError(f"no payload line in output:\n{output}")

    assert _payload_hex(r_letter.output) == _payload_hex(r_numeric.output)


def test_ep133_clear_pad_dry_run_numeric_form_d12_is_48():
    """Numeric 48 maps to group=D, pad_num=12 (file_id = 3200+7000+300+12=10512)."""
    runner = CliRunner()
    r_letter = runner.invoke(cli, ["ep133-clear-pad", "8", "D12", "--dry-run"])
    r_numeric = runner.invoke(cli, ["ep133-clear-pad", "8", "48", "--dry-run"])
    assert r_letter.exit_code == 0
    assert r_numeric.exit_code == 0

    def _payload_hex(output: str) -> str:
        for line in output.splitlines():
            if "payload (raw):" in line:
                return line.split(":", 1)[1].strip()
        raise AssertionError(f"no payload line in output:\n{output}")

    letter_hex = _payload_hex(r_letter.output)
    numeric_hex = _payload_hex(r_numeric.output)
    assert letter_hex == numeric_hex
    # file_id 10512 = 0x2910 — payload begins 07 01 29 10 ...
    assert letter_hex.startswith("07012910")


def test_ep133_clear_pad_rejects_bad_pad_coord():
    """Bad pad coordinates fail before any MIDI work."""
    runner = CliRunner()

    # Bad group letter
    r = runner.invoke(cli, ["ep133-clear-pad", "8", "E1", "--dry-run"])
    assert r.exit_code != 0
    assert "A/B/C/D" in r.output or "group" in r.output.lower()

    # Bad pad_num (out of 1..12 range)
    r = runner.invoke(cli, ["ep133-clear-pad", "8", "A13", "--dry-run"])
    assert r.exit_code != 0

    # Numeric out of 1..48
    r = runner.invoke(cli, ["ep133-clear-pad", "8", "49", "--dry-run"])
    assert r.exit_code != 0

    # Empty/garbage
    r = runner.invoke(cli, ["ep133-clear-pad", "8", "ABC", "--dry-run"])
    assert r.exit_code != 0


def test_ep133_clear_pad_rejects_bad_project_slot():
    """Project slot must be 1..9 (matches build-deck convention)."""
    runner = CliRunner()
    r = runner.invoke(cli, ["ep133-clear-pad", "0", "A1", "--dry-run"])
    assert r.exit_code != 0
    r = runner.invoke(cli, ["ep133-clear-pad", "10", "A1", "--dry-run"])
    assert r.exit_code != 0


# ── ep133 client.clear_pad unit test ─────────────────────────────────────────


def test_ep133_client_clear_pad_writes_sym_zero():
    """``EP133Client.clear_pad`` delegates to ``assign_pad`` with slot=0.

    We do NOT open a real transport — replace ``EP133Client._send`` so the
    test runs without MIDI hardware and asserts on the payload bytes.
    """
    from stemforge.exporters.ep133.client import EP133Client
    from stemforge.exporters.ep133.payloads import build_assign_pad

    captured: dict = {}

    class _FakeClient(EP133Client):
        def __init__(self) -> None:  # bypass transport entirely
            from stemforge.exporters.ep133.sysex import RequestIdAllocator

            self._t = None  # type: ignore[assignment]
            self._identity_code = 0
            self._reqs = RequestIdAllocator(seed=0)

        def _send(self, command, payload):  # type: ignore[override]
            captured["command"] = command
            captured["payload"] = payload
            return 42

        def _await_response(self, request_id, timeout=5.0):  # type: ignore[override]
            return None

    fc = _FakeClient()
    fc.clear_pad(project=8, group="A", pad_num=1)

    # Byte-identical to the standalone build_assign_pad with slot=0.
    expected = build_assign_pad(8, "A", 1, slot=0)
    assert captured["payload"] == expected
    # cmd byte = TE_SYSEX_FILE (5).
    from stemforge.exporters.ep133.commands import TE_SYSEX_FILE

    assert captured["command"] == TE_SYSEX_FILE
