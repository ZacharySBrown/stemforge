/**
 * msw handlers — mirror spec §4.3 endpoint catalog.
 *
 * Each handler returns a canned fixture so the popup tests can mount a
 * panel and assert against a deterministic response. Lane 1B's actual
 * server should produce equivalent responses; when it lands, these
 * handlers double as a contract spec.
 */

import { http, HttpResponse } from "msw";
import {
  CURATION_FRESH,
  CURATION_INDEX_EMPTY,
  CURATION_INDEX_OK,
  CURATION_STALE,
  FORGE_INDEX_EMPTY,
  FORGE_INDEX_OK,
} from "./fixtures";
import type { ApiResult } from "@/lib/popup-types";

const OK: ApiResult = { ok: true, warnings: [], errors: [] };

/** "Happy path" handlers — populated fixtures, all writes succeed. */
export const okHandlers = [
  http.get("/forges", () => HttpResponse.json(FORGE_INDEX_OK)),
  http.get("/curations", () => HttpResponse.json(CURATION_INDEX_OK)),
  http.get("/curations/verse_swap_v1", () => HttpResponse.json(CURATION_FRESH)),
  http.get("/curations/stale_curation", () => HttpResponse.json(CURATION_STALE)),

  // Forge writes
  http.post("/forges/:slug/load", () => HttpResponse.json(OK)),
  http.post("/forges/:slug/unload", () => HttpResponse.json(OK)),
  http.post("/forges/:slug/re-anchor", () => HttpResponse.json(OK)),
  http.post("/forges/:slug/re-curate", () => HttpResponse.json(OK)),
  http.post("/forges/:slug/reveal", () => HttpResponse.json(OK)),

  // Curation lifecycle
  http.post("/curations", () => HttpResponse.json(OK)),
  http.post("/curations/:name/open", () => HttpResponse.json(OK)),
  http.post("/curations/:name/save-as", () => HttpResponse.json(OK)),
  http.post("/curations/:name/rename", () => HttpResponse.json(OK)),
  http.delete("/curations/:name", () => HttpResponse.json(OK)),
  http.patch("/curations/:name/template", () => HttpResponse.json(OK)),
  http.patch("/curations/:name/target", () => HttpResponse.json(OK)),
  http.post("/curations/:name/export", () => HttpResponse.json(OK)),
  http.post("/curations/:name/trigger-bounce", () => HttpResponse.json(OK)),
  http.post("/curations/active/close", () => HttpResponse.json(OK)),

  // Server-side native picker
  http.post("/intent/pick-manifest", () => HttpResponse.json(OK)),

  http.get("/healthz", () => HttpResponse.json({ ok: true, version: "0.1.0" })),
];

/** Empty-state handlers — the lists return zero rows. */
export const emptyHandlers = [
  http.get("/forges", () => HttpResponse.json(FORGE_INDEX_EMPTY)),
  http.get("/curations", () => HttpResponse.json(CURATION_INDEX_EMPTY)),
];

/** Loading-state handlers — every request hangs. Use with vitest fake timers. */
export const slowHandlers = [
  http.get("/forges", () => new Promise(() => {})),
  http.get("/curations", () => new Promise(() => {})),
];

/** Failure handlers — `GET /forges` and `GET /curations` 500 out. */
export const failingHandlers = [
  http.get("/forges", () =>
    HttpResponse.json({ errors: ["server exploded"] }, { status: 500 }),
  ),
  http.get("/curations", () =>
    HttpResponse.json({ errors: ["server exploded"] }, { status: 500 }),
  ),
];
