# StemForge Configurator — Frontend Popup

Phase 3 deliverable. React + TypeScript + Vite + Tailwind + shadcn/ui + Framer Motion.

The popup is opened by the M4L strip device via `[jweb]` pointing at the
local Python HTTP server (Lane A), which mounts the built bundle at `/`.

## Architecture

```
[jweb]  ──┐
          ▼
   ┌─────────────────────────────┐
   │  configurator popup (here)  │
   │  ─────────────────────────  │
   │  • SSE   /state/stream  →   │
   │      useProjectState hook   │
   │  • POST  /intent/*      →   │
   │      useIntent mutations    │
   │  • GET   /preview/:id   →   │
   │      <audio src=...>        │
   └─────────────────────────────┘
              │
              ▼ HTTP
   ┌─────────────────────────────┐
   │  FastAPI server (Lane A)    │
   │  single-writer ProjectSpec  │
   └─────────────────────────────┘
```

The frontend is intentionally a thin renderer over server state — no
client-side write-through, no optimistic mutations. Per Decision 15
(single-writer-per-fact), the Python server is the canonical writer of the
slot table; the popup sends *intents* and waits for SSE state to bounce back.

## Develop

```bash
cd web/configurator
npm install
npm run dev          # vite dev server on :5173 with /intent /state proxy
npm run test         # vitest
npm run build        # outputs to dist/
npm run build:deploy # rsync dist/ -> ../../stemforge/configurator/static/
```

If the Python server is on a non-default port, override:

```bash
VITE_STEMFORGE_API=http://127.0.0.1:8888 npm run dev
```

## Module layout

```
src/
  main.tsx                  # root + providers (TanStack Query, Tooltip, Toaster)
  App.tsx                   # TopBar + LeftRail + main + StatusBar layout
  components/
    ui/                     # shadcn primitives (button, badge, card, ...)
    TopBar.tsx              # project name + target chip + connection status
    LeftRail.tsx            # operations buttons
    PadCanvas.tsx           # 4×12 grid (read-only for Phase 3)
    StatusBar.tsx           # memory / format chips / last-op elapsed
    ConnectionStatus.tsx    # SSE dot with pulse + tooltip
    EmptyState.tsx          # centered icon + 2-line copy + CTA
    Skeletons.tsx           # mirror-shape loading placeholders
  hooks/
    useProjectState.ts      # SSE subscription, ProgressState, log queue
    useIntent.ts            # TanStack Query mutations per /intent/*
  lib/
    api.ts                  # fetch wrappers + base URL resolution
    types.ts                # ProjectSpec / SseEvent / request bodies
    utils.ts                # cn(), formatMB, formatElapsed
  styles/
    globals.css             # Tailwind layers + CSS-var palette
```

## Phase 3 scope (what ships)

- Polished popup shell — TopBar, LeftRail, 4×12 pad canvas, StatusBar.
- Live ProjectSpec render via SSE.
- Operation intents wired (load-manifest, commit, recompute, export).
- Progress bar + toasts on long operations.
- Empty / skeleton states.

## Phase 4 (deliberately deferred)

- Drag-to-assign on pads.
- Inspector panel + multi-axis selection.
- Splice editor / slicer mini-UI.
- Audio preview scrubber widget.
