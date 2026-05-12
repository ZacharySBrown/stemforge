# Three `SendMessage error 2` lines at Max startup — root cause + speculative fix

**Status:** Hypothesis fix applied in `fix/max-startup-sendmessage-errors` — needs on-device verification by the human (rebuild .amxd via `build_amxd.py`, reinstall pkg, reopen Live).

## Symptom

When Live opens the StemForge .als (or otherwise loads the StemForge .amxd), the Max console shows three identical lines BEFORE any StemForge JS chatter:

```
The Max function "SendMessage" returned with error 2: Bad parameter value.
The Max function "SendMessage" returned with error 2: Bad parameter value.
The Max function "SendMessage" returned with error 2: Bad parameter value.
```

Then the normal StemForge boot proceeds (`scanManifests`, `scanPresets`, `udpreceiver: binding ...`, `[StemForge-v0.1.0-loaded]: bang`).

## What we know

- Confirmed 2026-05-12: occurs on a fresh `.pkg` install + reopen Live.
- Doesn't break anything — `bounceTracks` still works, manifests still load.
- Not from our JS — would be prefixed `js: ` if it were.
- "SendMessage" is Max's internal IPC — usually emitted by `[thispatcher]` scripting, `[universal]`, or M4L's host-side parameter-enrollment probe.

## Root-cause investigation

### Search space surveyed

Read `v0/src/maxpat-builder/builder.py` end-to-end. Inventoried every emit site that fires at device load:

1. **`loadbang` → `deferlow` → `t b b b` → 3× scan messages** (lines ~1387–1478). Each message-box target (sf_preset_loader, sf_manifest_loader, sf_settings_mgr) is instantiated BEFORE the loadbang chain in the box list, and the `[deferlow]` already gates the sends until after instantiation — this path is correctly ordered. Not the culprit.
2. **`[v8ui]` canvas** (~line 286). One canvas, one `obj-sf-ui` varname. Doesn't fire SendMessages at boot — its `loadbang`/`onresize` triggers run JS code (which would print `js:` prefixes).
3. **UDP receivers `[udpreceive 7420]` / `[udpreceive 7421]`** (~lines 583, 617). Don't emit SendMessages; they emit `udpreceive: binding ...` printouts (already accounted for as normal chatter).
4. **`[dict ...]` boxes** (4×, lines 399–417). No init message dispatch.
5. **Native `[umenu]` boxes** (preset/source, lines 661–702). `autopopulate: 0` and `items: "Pick preset..."` — these populate from JS at scan time, not loadbang. No SendMessages emitted.
6. **`[js]` boxes** (9×). Their `loadbang` handlers run JS, which prefixes errors with `js:`. Not them.
7. **`[message]`, `[route]`, `[regexp]`, `[prepend]`, `[shell]`, `[opendialog]`** — none of these emit init-time SendMessages.

### Candidate set

That left M4L's host-side parameter-enrollment probe over `live.*` widgets — exactly the class that the [Max forum](https://cycling74.com/forums/) and prior-art M4L devices flag as the source of "Bad parameter value" boot noise.

The patcher contains exactly **3** `live.*` widgets:

| id                  | maxclass       | parameter_enable | saved_attribute_attributes |
|---------------------|----------------|------------------|----------------------------|
| `obj-sf-status-dot` | `live.text`    | `0` (already)    | _missing_                  |
| `obj-sf-status-text`| `live.comment` | _missing_        | _missing_                  |
| `obj-sf-version-text` | `live.comment` | _missing_      | _missing_                  |

**3 widgets ↔ 3 errors** is the count-match smoking gun.

### Hypothesis

When Live opens a M4L device, the host iterates every `live.*` widget to build the device's parameter inventory. Any widget lacking BOTH a `parameter_enable: 0` opt-out AND a `saved_attribute_attributes.valueof` table fails the host's parameter-slot lookup with internal `SendMessage` → "Bad parameter value" error 2.

`live.comment` and `live.text` are display-only in our usage (mode 0 button, static label). The clean fix is to declare `parameter_enable: 0` on each so they're opted out of the enrollment scan entirely.

> Caveat: `obj-sf-status-dot` already had `parameter_enable: 0` and was apparently still contributing one of the three errors. This is consistent with the host's enrollment pass running before reading the flag (i.e. the probe is unconditional per `live.*` instance and `parameter_enable: 0` only suppresses the parameter-slot allocation, not the probe itself). If the on-device test shows 1 error remaining after this fix, the dot needs `saved_attribute_attributes.valueof` with a `parameter_invisible: 1` stub as a follow-up.

### Fix applied

`v0/src/maxpat-builder/builder.py`:

- Added `"parameter_enable": 0` to the `extras` dict of both `live.comment` widgets (`obj-sf-status-text` and `obj-sf-version-text`).
- Inline comment on each pointing to this issue doc.
- New regression test `test_all_live_widgets_opt_out_of_parameter_enrollment` in `v0/src/maxpat-builder/tests/test_builder.py` — asserts every `live.*` widget carries either the flag or a `saved_attribute_attributes.valueof` block.

### Falsifiable expectation

After `build_amxd.py` rebuild + pkg reinstall + Live restart:

- **Best case:** all 3 `SendMessage error 2` lines gone — confirms the host probes the enabled flag pre-allocation and skips parameter probing entirely.
- **Partial:** 1 error remains (from the dot) — confirms the host probes unconditionally even with `parameter_enable: 0`. Follow-up: add the `saved_attribute_attributes.valueof` stub to all three widgets.
- **No change:** the SendMessage source is NOT live.* parameter enrollment. Re-investigate; next candidate set below.

### Next candidates if the live.* fix fails on-device

Static analysis ruled these out, but if the fix doesn't help, re-examine:

1. **M4L parameter bank persistence** — Live serializes/restores M4L parameter banks at device load. Even with no parameter-enabled widgets, the empty-bank serialization could throw 3 errors per some internal index. Probe by adding ONE parameter-enabled widget (e.g. an invisible `live.toggle` with full `saved_attribute_attributes`) and see if error count changes.
2. **`v8ui` canvas init handshake** — the v8ui's `onbang`/`onresize`/`onloadbang` runs sf_ui.js. If sf_ui.js synchronously calls `outlet()` before all its outlets are wired (highly unlikely given how `[v8ui]` lifecycle works, but possible), it could trigger 3 host-side rejects.
3. **`[shell]` external init probe** — the bundled `shell.mxo` is third-party. Some externals emit one host-message at init that gets rejected by the host if the external is loaded before its argument is parsed. Probe by removing the `[shell]` box and rebuilding.
4. **Dependency-cache JS preload** — `dependency_cache` lists 9+ JS files with `bootpath` hints. Each gets opened via Max's path resolver. If a path lookup goes via SendMessage to a non-existent host service, that's 3 of the 9 entries failing.
5. **The `project` field's `amxdtype: 1633771873`** — verified against `m4l_device_development_guide.md` pitfall #6. Correct value for audio effect. Almost certainly not this.

## Don't rebuild from worktree

Per `memory/feedback_test_deploy_discipline.md`: don't run `build_amxd.py` or install the .pkg from a worktree. The user runs the rebuild + reinstall + Live restart, then reports back which of the three falsifiable outcomes above occurred.

## References

- `v0/src/maxpat-builder/builder.py` lines ~316–392 (the three `live.*` widgets)
- `v0/src/maxpat-builder/tests/test_builder.py` `test_all_live_widgets_opt_out_of_parameter_enrollment`
- `memory/m4l_device_development_guide.md` pitfall #18 (live.slider needs full parameter attributes)
