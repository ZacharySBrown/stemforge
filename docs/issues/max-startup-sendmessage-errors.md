# Three `SendMessage error 2` lines at Max startup — unexplained

**Status:** Open / low-priority — captured 2026-05-12.

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
- Doesn't appear to break anything — `bounceTracks` still works, manifests still load.
- Not from our JS — would be prefixed `js: ` if it were.
- "SendMessage" is Max's internal IPC — usually emitted by `[thispatcher]` scripting, `[universal]`, or related infrastructure.

## Hypothesis

Likely one of our patcher objects' init scripts tries to send a message before its target object's inlet is ready. The "Bad parameter value" with error 2 typically means a destination scripting name was unresolved at the moment the send fired.

## How to investigate

1. **Strip down `builder.py`** patcher emit and bisect — comment out groups of objects to find which subgraph emits the errors.
2. **Watch `[print]` or `[error]` taps** in the patcher to localize.
3. **Search for `SendMessage` in Max docs / Cycling forums** — error 2 specifically.

## Done when

Either:
- Root cause identified and fixed (no errors at startup).
- Confirmed harmless and explicitly documented (downgraded to "expected boot noise").

Not blocking for release — but a clean boot console is presentable; three errors at top isn't.
