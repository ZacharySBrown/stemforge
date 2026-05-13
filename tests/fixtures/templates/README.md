# Templates fixtures

Sentinel `.adg` blobs for Phase 3A configurator template-index tests.

These files are intentionally empty (zero bytes). The server-side
template-index code only looks at filename + mtime + size; the device-side
`load_browser_item` call accepts whatever Live's browser dereferences,
which is exercised via mocked LiveAPI calls in the L3 tests, not by
actually opening these files in Ableton.

`*.description` siblings exercise the optional plain-text sidecar reader.
