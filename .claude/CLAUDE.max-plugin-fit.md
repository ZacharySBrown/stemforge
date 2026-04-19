# Max-Plugin Template Fit Analysis (Dogfood)

Honest assessment of how the `max-plugin` quickstart template would map onto
stemforge, and where it rubs. **This is a sidecar analysis, not a replacement
for `CLAUDE.md`.** Read alongside the main project doc.

## TL;DR

**Partial fit, 55–60%.** The template optimizes for projects that *author DSP
algorithms in Max/RNBO and export to plugins*. Stemforge's core value is
different: *Python orchestration + external stem separation APIs +
manifest-driven M4L loading*. Migrating would force-fit half of stemforge
into zones that don't apply, while leaving its most important concerns
(backends, pipelines, manifest, curator) without a clear home.

**Recommendation**: adopt the **patterns** (zone purity, parameter contracts,
four-role agents, /design → /plan workflow, RNBO param diff tooling if we
export any patches), not the **layout**.

## Zone-by-zone Mapping

| Template zone | Stemforge equivalent | Fit |
|---|---|---|
| `models/` | — (no local ML models; backends call external APIs) | ❌ empty |
| `dsp/` | — (no in-repo DSP; we pipe audio through Demucs / LALAL.AI / Music AI) | ❌ empty |
| `device/` | `m4l/` | ✅ clean map |
| `export/` | — (no RNBO exports) | ❌ empty |
| `node/` | maybe: `m4l/` has a Node-for-Max bridge per the root CLAUDE.md | ⚠️ unclear |
| `tools/` | `tools/` | ✅ clean map |
| `tests/` | `tests/` | ✅ clean map |

**Homeless concerns in stemforge:**

- `stemforge/` (the Python package: CLI, backends, slicer, analyzer, curator, manifest) — no template zone fits. It's the *heart* of stemforge and would need a new `core/` zone.
- `pipelines/` — YAML pipeline configs. No analog in the template.
- `specs/` — would map to `docs/`, already aligned.
- `v0/` — track-based experimental structure. Orthogonal to zones.

## What the Template Gets Right for Stemforge

1. **Zone rules: "M4L reads Core's output (stems.json) but never imports Core code"** — this IS exactly the DSP→Device forward-only rule, just renamed. Stemforge already does this.
2. **Manifest as contract** — stems.json is stemforge's manifest; RNBO `[param]` names are the template's contract. Same principle.
3. **Four-role agent model** — already in stemforge's CLAUDE.md, nearly verbatim. The template inherits this.
4. **RNBO param diff tool** — IF stemforge ever exports an M4L device's embedded RNBO to a VST, this would be useful. Not today.

## What the Template Gets Wrong for Stemforge

1. **Assumes in-repo DSP.** Stemforge outsources DSP to third-party backends. The `dsp/` zone would be permanently empty, and the template's strongest review gates (RNBO param contracts, DSP regression hashes) wouldn't fire.
2. **No `core/` zone for Python orchestration.** Stemforge's backends, slicer, curator, and manifest code are its crown jewels. The template relegates Python to `tools/` (CLI helpers, not business logic).
3. **No "pipelines" concept.** Stemforge's YAML→JSON pipeline compilation is central. No template analog.
4. **v0 track-based structure conflicts.** Template assumes zones are permanent; stemforge's v0 assumes parallel tracks with per-track write lanes.

## What to Steal

Even without migrating, these pieces of the template are worth adopting in stemforge:

| Piece | Where in stemforge | Why |
|---|---|---|
| `tools/validate_patches.py` | `tools/` | M4L devices in `m4l/` should be uncompressed-JSON-linted |
| `tools/param_diff.py` | `tools/` | If any M4L device embeds a RNBO patch, guard against breaking param renames |
| `.github/workflows/ci.yml` patch-validation job | `.github/` | Prevent compressed .amxd from landing in main |
| `docs/design-docs/future-directions.md` format | `docs/` | Roadmap doc with Reddit-sourced reference DSP developers already captured |
| Node contracts pattern (`node/src/contracts.js`) | m4l bridge | Typed message boundary between M4L and any Node-for-Max work |

## What Would a Hybrid Look Like?

If we ever wanted the template to fit stemforge-class projects, we'd add:

- A `core/` zone for Python orchestration (stemforge's case: backends, slicer, curator)
- A `pipelines/` zone for declarative pipeline configs
- A way to mark zones as "external-backend-backed" so DSP regression tests skip gracefully

This is tracked in the template's Future Directions doc as a proposal, not committed scope.

## Next Step Options

1. **Do nothing.** Keep stemforge's existing CLAUDE.md. Steal the validator + param_diff into `tools/`. Stop.
2. **Shallow dogfood.** Copy `validate_patches.py` and `param_diff.py` into stemforge's `tools/`, wire them into CI. One afternoon of work.
3. **Deep dogfood.** Propose a `max-plugin + core` variant of the template. Pull stemforge's backend/pipeline concerns into the template as a new zone. Bigger: probably a design doc first.

Recommend (2). It's the cheapest way to dogfood the tooling without fighting the layout.
