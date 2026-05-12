# `sf-remote fire forge reload` doesn't actually reload Max [js]

**Status:** Documented (not fixed) — 2026-05-12.

Phase 1 hardening dropped the optimistic "reload forwarded to loader"
log line in favor of an honest "reload forwarded to loader (no-op
without loader-side handler)" and added a CAVEAT block to
``sf_forge.js:reload()`` describing the three manual workarounds. The
real fix (Option 1 below — add ``function reload()`` to the loader)
remains TODO; deferred because we can't verify autowatch-toggle
behavior triggers re-eval without on-device testing.

## Symptom

```bash
uv run sf-remote fire forge reload
```

…appears to succeed (`reload forwarded to loader` shows in the log) but the `[js]` object in the patcher does NOT re-evaluate `stemforge_loader.v0.js` from disk. New JS changes don't take effect.

## Root cause

`sf_forge.js:reload()` (line 449) outlets the symbol `"reload"` to outlet 2. The patcher routes outlet 2 into the `[js stemforge_loader.v0.js]` object's inlet. Max's [js] object dispatches inlet messages to top-level functions whose name matches the first atom. **There is no `function reload()` in `stemforge_loader.v0.js`**, so the message is silently dropped.

## Workarounds (today)

- Right-click `[js stemforge_loader.v0.js]` → **Edit Script** → Cmd+S → Max auto-reloads.
- Restart Live (heavy).
- Install via .pkg (also heavy, includes Live restart).

## Fix options

1. **Add `function reload()` to the loader** that calls `this.autowatch = 1` or otherwise forces a re-eval. Max [js] has no documented `eval-file` verb, but `autowatch=1` followed by a touch of the source file works.

2. **Use the patcher [pcontrol] or scripting `script load` route** to swap the JS file. Adds patcher complexity.

3. **Wire `sf-remote fire forge reload`** to instead send a message that causes Max to delete + re-add the [js] object via thispatcher scripting. Heavy but reliable.

Option 1 is the cleanest if `autowatch=1` toggling does the job.

## Done when

`uv run sf-remote fire forge reload` causes the loader to pick up on-disk JS changes without manual right-click + save.
