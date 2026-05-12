"""Range-aware WAV serving for the configurator's clip preview surface.

The popup's ``<audio>`` tag (or future waveform viewer) issues ``Range``
requests to scrub through a clip without downloading the whole file.
:func:`build_audio_response` parses an HTTP ``Range`` header against a
file's byte length and returns a FastAPI :class:`Response` with the
correct slice and ``Content-Range`` / ``Accept-Ranges`` headers.

This is intentionally a pure-bytes path — no decoding, no resampling.
The browser handles WAV decoding; the server just serves the slice.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from fastapi import Response

WAV_MIME = "audio/wav"


@dataclass(frozen=True)
class ByteRange:
    """Resolved byte range for a single ``Range: bytes=START-END`` request."""

    start: int
    end: int  # inclusive
    total: int

    @property
    def length(self) -> int:
        return self.end - self.start + 1


def parse_range(header_value: str | None, total: int) -> ByteRange | None:
    """Parse an HTTP ``Range`` header against a file's byte length.

    Returns ``None`` when the header is absent or malformed. Returns a
    :class:`ByteRange` clamped to ``0..total-1`` otherwise.

    Supports only the single-range ``bytes=START-END`` form. Multi-range
    requests are rare; for the configurator's purposes we 200-fallback
    via the caller's ``None`` branch when this returns ``None``.
    """
    if not header_value or total <= 0:
        return None
    header = header_value.strip().lower()
    if not header.startswith("bytes="):
        return None
    spec = header[len("bytes=") :].split(",", 1)[0].strip()
    if "-" not in spec:
        return None
    start_s, end_s = spec.split("-", 1)
    start_s, end_s = start_s.strip(), end_s.strip()
    try:
        if start_s == "":
            # Suffix range: bytes=-N → last N bytes.
            if end_s == "":
                return None
            length = int(end_s)
            if length <= 0:
                return None
            start = max(0, total - length)
            end = total - 1
        else:
            start = int(start_s)
            end = int(end_s) if end_s else total - 1
    except ValueError:
        return None
    if start < 0 or start >= total:
        return None
    if end < start:
        return None
    end = min(end, total - 1)
    return ByteRange(start=start, end=end, total=total)


def build_audio_response(
    path: Path,
    *,
    range_header: str | None,
    mime: str = WAV_MIME,
) -> Response:
    """Build a FastAPI response for ``path``, honoring an optional ``Range``.

    - Without a ``Range`` header → 200 with the full body and
      ``Accept-Ranges: bytes`` (so the browser knows it can request slices).
    - With a parseable ``Range`` header → 206 with the slice +
      ``Content-Range: bytes START-END/TOTAL``.
    - With a malformed range → 200 fallback (lenient; matches most CDN
      behavior).
    """
    if not path.is_file():
        return Response(status_code=404, content=f"clip not found: {path.name}")

    total = path.stat().st_size
    rng = parse_range(range_header, total)
    headers = {
        "Accept-Ranges": "bytes",
        "Content-Type": mime,
    }
    if rng is None:
        return Response(
            content=path.read_bytes(),
            status_code=200,
            headers={**headers, "Content-Length": str(total)},
        )
    with path.open("rb") as fh:
        fh.seek(rng.start)
        chunk = fh.read(rng.length)
    return Response(
        content=chunk,
        status_code=206,
        headers={
            **headers,
            "Content-Range": f"bytes {rng.start}-{rng.end}/{total}",
            "Content-Length": str(len(chunk)),
        },
    )


__all__ = [
    "ByteRange",
    "WAV_MIME",
    "build_audio_response",
    "parse_range",
]
