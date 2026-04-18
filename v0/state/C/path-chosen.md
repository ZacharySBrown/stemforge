# Track C path decision

**Path chosen:** Path 1 — fully programmatic `.maxpat` JSON generation + `.amxd` container write.

## Rationale

Path 1 succeeded within the 2-hour budget. Reverse-engineering the `.amxd` container format was straightforward once I inspected `m4l/StemForgeTemplateBuilder.amxd` (the simplest reference device committed to the repo). No community library was needed.

## `.amxd` container format (verified against Ableton Live 12 / Max 9 output)

```
Offset  Field          Value / meaning
------  -------------  -----------------------------------------------------
0       magic          b"ampf"
4       version        u32 LE = 0x00000004  (container format v4)
8       iiii sentinel  b"iiii" (fixed)
12      meta tag       b"meta"
16      meta_len       u32 LE = 4
20      meta_val       u32 LE. Observed values:
                         1 → plain audio effect (e.g. StemForgeTemplateBuilder)
                         7 → audio effect + embedded project resources
                             (e.g. StemForgeLoader — .js appended after JSON)
24      ptch tag       b"ptch"
28      ptch_len       u32 LE — byte length of what follows (incl. any trailer)
32      ptch body      UTF-8 patcher JSON. Max's writer terminates with \n\x00.
                         For Node-for-Max projects, additional chunks may
                         follow the JSON (mx@c header + .js text). v0 device
                         does not need that — we ship a pure-JSON patch.
```

Confirmed by `test_can_unpack_reference_amxd_from_repo` and
`test_repack_of_reference_opens_as_same_patcher` — we can round-trip the
existing `StemForgeTemplateBuilder.amxd` through our packer and get back the
same patcher dict.

## What was built

- `v0/src/maxpat-builder/amxd_pack.py` — container writer + reader
- `v0/src/maxpat-builder/builder.py` — `device.yaml` → Max patcher JSON
- `v0/src/maxpat-builder/build_amxd.py` — CLI: `python build_amxd.py` →
  `v0/build/StemForge.amxd`
- `v0/src/m4l-js/stemforge_bridge.v0.js` — node.script child; spawns
  stemforge-native, parses NDJSON, emits Max outlets
- `v0/src/m4l-js/stemforge_loader.v0.js` — classic js; LiveAPI duplicates
  template tracks + loads stem WAVs on `complete`
- 26 unit tests (amxd-pack, patcher-builder, bridge-js NDJSON parsing)
  all green.

## Path 2 status

Not attempted. `v0/assets/StemForge.template.amxd` was not created; no
one-time human asset needed.
