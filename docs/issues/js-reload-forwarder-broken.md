# `sf-remote fire forge reload` doesn't actually reload Max [js]

**Status:** Implemented (pending on-device validation) — 2026-05-12.

Phase 1 hardening dropped the optimistic "reload forwarded to loader"
log line in favor of an honest "reload forwarded to loader (no-op
without loader-side handler)" and added a CAVEAT block to
``sf_forge.js:reload()`` describing the three manual workarounds. The
loader-side handler (Option 1 below) landed 2026-05-12 in
`stemforge_loader.v0.js`. On-device behavior (does the autowatch
toggle actually cause Max [js] to re-eval the file?) still needs a
manual check on a live patch — see "Pending validation" below.

## Symptom (historical, pre-fix)

```bash
uv run sf-remote fire forge reload
```

…appeared to succeed (`reload forwarded to loader` shows in the log) but the `[js]` object in the patcher did NOT re-evaluate `stemforge_loader.v0.js` from disk. New JS changes didn't take effect.

## Root cause (historical)

`sf_forge.js:reload()` (line 449) outlets the symbol `"reload"` to outlet 2. The patcher routes outlet 2 into the `[js stemforge_loader.v0.js]` object's inlet. Max's [js] object dispatches inlet messages to top-level functions whose name matches the first atom. **There was no `function reload()` in `stemforge_loader.v0.js`**, so the message was silently dropped.

## Fix landed (2026-05-12)

Option 1 from the list below. `stemforge_loader.v0.js:reload()` now toggles
``this.autowatch`` 0 → 1, which re-arms Max's [js] file-watcher and (per
Max docs) causes a re-eval from disk. The fix is mirrored to the
`v0/src/m4l-package/` copy per the JS dual-location sync rule.

Test coverage: `tests/js_mocks/test_reload.test.js` (9 cases). Covers
function existence in both files, autowatch 0 → 1 transition, defensive
error handling, and Max-style symbol-name dispatch parity.

## Pending validation

The JS mock suite verifies that `reload()` is dispatchable, toggles
autowatch in the expected sequence, and surfaces a console diagnostic.
**What it cannot verify** is whether Max [js] actually re-reads the
source file from disk when autowatch flips 0 → 1 inside an M4L embed.
That requires:

1. Loading the StemForge device into a running Live set.
2. Editing `stemforge_loader.v0.js` on disk (add a `post()` line).
3. Running `uv run sf-remote fire forge reload`.
4. Confirming the new `post()` line fires on next inlet message.

If step 4 fails on-device, fall back to Option 2 or 3 below.

## Fix options (history)

1. **Add `function reload()` to the loader** that calls `this.autowatch = 1` or otherwise forces a re-eval. Max [js] has no documented `eval-file` verb, but `autowatch=1` followed by a touch of the source file works. **[CHOSEN — landed 2026-05-12]**

2. **Use the patcher [pcontrol] or scripting `script load` route** to swap the JS file. Adds patcher complexity.

3. **Wire `sf-remote fire forge reload`** to instead send a message that causes Max to delete + re-add the [js] object via thispatcher scripting. Heavy but reliable.

## Workarounds if the fix regresses

These remain useful escape hatches if on-device validation reveals
autowatch toggling is unreliable inside M4L embeds:

- Right-click `[js stemforge_loader.v0.js]` → **Edit Script** → Cmd+S → Max auto-reloads on save.
- Install via .pkg (heavy: includes a Live restart).
- Restart Live (heaviest).

## Done when

`uv run sf-remote fire forge reload` causes the loader to pick up on-disk JS changes without manual right-click + save — **verified on-device**, not just in the mock suite.
