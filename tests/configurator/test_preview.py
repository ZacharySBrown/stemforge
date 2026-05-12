"""Range-aware WAV serving."""

from __future__ import annotations

from pathlib import Path

from stemforge.configurator.preview import (
    build_audio_response,
    parse_range,
)


def test_parse_range_basic():
    r = parse_range("bytes=0-99", total=1000)
    assert r is not None and r.start == 0 and r.end == 99


def test_parse_range_open_ended():
    r = parse_range("bytes=500-", total=1000)
    assert r is not None and r.start == 500 and r.end == 999


def test_parse_range_suffix():
    r = parse_range("bytes=-100", total=1000)
    assert r is not None and r.start == 900 and r.end == 999


def test_parse_range_malformed_returns_none():
    assert parse_range("blah", total=1000) is None
    assert parse_range("bytes=abc-def", total=1000) is None
    assert parse_range("bytes=", total=1000) is None
    assert parse_range(None, total=1000) is None


def test_parse_range_out_of_bounds():
    assert parse_range("bytes=2000-3000", total=1000) is None
    # End past total clamped down.
    r = parse_range("bytes=0-5000", total=1000)
    assert r is not None and r.end == 999


def test_build_audio_response_full_body(make_wav, tmp_path: Path):
    wav = make_wav("a.wav")
    resp = build_audio_response(wav, range_header=None)
    assert resp.status_code == 200
    assert resp.headers["Accept-Ranges"] == "bytes"
    assert int(resp.headers["Content-Length"]) == wav.stat().st_size


def test_build_audio_response_range_returns_206(make_wav, tmp_path: Path):
    wav = make_wav("a.wav")
    total = wav.stat().st_size
    resp = build_audio_response(wav, range_header=f"bytes=0-{min(99, total - 1)}")
    assert resp.status_code == 206
    assert "Content-Range" in resp.headers
    assert resp.headers["Content-Range"].startswith("bytes 0-")
    assert resp.headers["Content-Range"].endswith(f"/{total}")


def test_build_audio_response_missing_file(tmp_path: Path):
    resp = build_audio_response(tmp_path / "nope.wav", range_header=None)
    assert resp.status_code == 404
