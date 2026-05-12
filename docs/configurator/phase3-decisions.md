# Phase 3 — Design Decisions

Captures the 3 design calls the [Phase 3 Fresh Session Handoff](PHASE_3_FRESH_SESSION_HANDOFF.md) flagged as gating Phase 3 implementation. Resolved 2026-05-12 in the session that immediately followed v0.2.0 ship + the configurator-specs commit.

## (a) Frontend stack — React + TypeScript

**Decision:** React 18 + TypeScript 5 + Vite + Tailwind CSS + shadcn/ui + Framer Motion + Lucide-react.

**Why over SolidJS** (the spec's lead candidate):

- **shadcn/ui** ships 50+ accessibility-polished components (Radix primitives + Tailwind styling) — instant Linear/Vercel-aesthetic. SolidJS has analogues (kobalte for Radix, motionone for Framer Motion) but maturity is meaningfully lower.
- **Framer Motion** is the highest-quality motion library available; for "snazzy and modern" the velocity advantage matters more than SolidJS's reactivity edge.
- The configurator's runtime perf isn't bound by frontend reactivity — it's bound by Python-server round-trips and audio decode. React's overhead is invisible at this scale.
- Architecture is portable (one component library swap) if we ever want to migrate.

**Stack details:**
- **Build:** Vite. Static `index.html` + JS bundle served by the Python server, or `vite dev` directly during local development.
- **Styling:** Tailwind with custom theme tokens (CSS variables). Dark theme default.
- **Components:** shadcn/ui (copied into `src/components/ui/` per shadcn convention — owned source, not a npm dep).
- **Animation:** Framer Motion for transitions, layout, hover/tap states.
- **Icons:** Lucide-react.
- **Font:** Inter via Google Fonts with system fallback stack.
- **Notifications:** sonner (shadcn's pick).
- **State / data:** TanStack Query for HTTP + a small custom hook for SSE subscription.

**Visual design language (binding):**
- Dark first. Light theme optional later.
- Reference aesthetics: Linear, Vercel dashboard, Arc browser settings, Raycast preferences.
- Generous whitespace. Monospace for technical numeric fields. Bold display type for project name + scene name.
- Skeleton loading states (shadcn Skeleton component) — never empty rectangles.
- Subtle glassmorphism on modals + dropdowns.
- Micro-interactions on every button (hover scale 1.02, active scale 0.98, transition `ease-out` 100–150 ms).
- Motion entry on the popup itself (fade + 4px slide) when it first opens.

## (b) HTTP server API shape — intent-receiver

Per Decision 15 in the spec: server is an intent-receiver, not a thin CRUD layer over the ProjectSpec file.

### Endpoints

```
GET    /state                      → current ProjectSpec JSON (200)
GET    /state/stream               → SSE; pushes ProjectSpec on every mutation
                                     event types: state, log, progress, error

GET    /preview/<clip_id>          → serves WAV bytes (Range-aware) for audio
                                     preview; 206 Partial Content on Range hits

POST   /intent/load-manifest       body: {manifest_path: str}
                                   loads a curated manifest as the source for
                                   slot-claim seeding; clears the working ProjectSpec

POST   /intent/commit              body: {} (or {session_tracks: ...} from M4L COMMIT)
                                   pulls session view → slot table; populates
                                   audio_hash on every entry; emits state event

POST   /intent/assign-pad          body: {group: "A"|"B"|"C"|"D", pad: 1..12,
                                          clip_id: str | null}
                                   explicit user assignment per Decision 14;
                                   clip_id=null clears

POST   /intent/clear-pad           body: {group, pad}
                                   syntactic sugar over assign-pad with clip_id=null

POST   /intent/set-group-format    body: {group, format: "preserve_source"|"vocal"|
                                          "vocal-tight"|"drum"|"texture"}
                                   per-group sample format (Decision 16)

POST   /intent/recompute           body: {}
                                   re-runs curate/forge against the loaded manifest;
                                   refreshes available clips for slot table

POST   /intent/export              body: {target: "ep133", out_path: str}
                                   produces a .ppak via Ep133Projector; returns
                                   {ok: bool, out_path, byte_count}
```

### Response envelopes

All `/intent/*` POSTs return:
```json
{
  "ok": true,
  "state": { /* ProjectSpec JSON */ },
  "warnings": [],
  "errors": []
}
```

On error: `ok: false`, populated `errors`, no state mutation.

### SSE event types

- `state` — full ProjectSpec dump (sent on every mutation)
- `log` — `{level, message, ts}` for human-readable debug
- `progress` — `{op, fraction}` for long-running operations (e.g. export)
- `error` — `{op, message}` for non-fatal warnings during operations

### Auth

None. Bound to `127.0.0.1` only. If the user opens it to the network later, that's an explicit decision.

### Stack

- **FastAPI** (not bare stdlib) — Pydantic schemas, OpenAPI docs for free, SSE-friendly via StreamingResponse, fast.
- **Uvicorn** with `--host 127.0.0.1` only.
- Port discovery: read `STEMFORGE_CONFIGURATOR_PORT` env var; fallback to free port from a small range (start 7430, try 7430–7440). Strip device queries `/healthz` to find the right port.

## (c) `audio_hash` population — server-side at COMMIT ingest

Per Phase 2 loose-end: `audio_hash` is empty-string at COMMIT time today.

**Decision:** populate server-side when `/intent/commit` ingests session_tracks from M4L.

**Why server, not JS:**
- M4L `[js]` doesn't have crypto primitives suitable for SHA-256 over audio sample bytes.
- Server already opens each WAV for `audio_hash`-adjacent work (duration, channel count, sample rate validation for the memory budget). Bundling hash compute into that read is free.
- Slot-table reconciliation (Decision 14) keys on `audio_hash` — having it populated at first-write avoids a second pass.

**Algorithm:**
1. Open WAV file via soundfile.
2. Read all samples as float32 mono mixdown if stereo (so the hash is channel-collapse-invariant; useful since EP-133 downmixes anyway).
3. SHA-256 of the raw byte stream of the mono samples.
4. Hex-encode, 16-char truncation. Store as `audio_hash` on the slot entry.

**Cache:** computed hashes cached in `~/stemforge/.audio_hash_cache.json` keyed by `(file_path, mtime, size)`. Cold cache hit pays the read once; subsequent COMMITs are fast.

**Truncated hex caveat:** 16 hex chars = 64 bits. Birthday collision at ~4 billion entries — fine for slot-table identity within a single project (which tops out at 48 pads).

## Implementation parallelism

Phase 3 splits cleanly into three lanes that share only this design doc as interface:

- **Lane A — Python HTTP server.** `tools/m4l_configurator_server.py` + `stemforge/configurator/` module (schemas, intent handlers, hash, projector wiring).
- **Lane B — Frontend.** `web/configurator/` (Vite app); static build artifacts served by Lane A's server at `/`.
- **Lane C — M4L strip device.** New `v0/src/m4l-devices/configurator-strip/` device built from scratch per memory `project_configurator_device_decision.md`. Contains operations strip + `[jweb]` opening the popup.

Each lane is a separate worktree + PR. Order of merge doesn't strongly matter; they connect via the API surface defined above. A trivial smoke test wires all three together: load a manifest from the strip → popup shows project state → manual export produces a `.ppak`.
