/**
 * HTTP client for the StemForge configurator server (Lane A).
 *
 * Base URL resolution:
 *  - In production the popup is served at the same origin as the API (the
 *    Python server mounts `dist/` at `/`), so relative URLs Just Work.
 *  - In dev (`npm run dev`), `vite.config.ts` proxies the relevant prefixes
 *    to the local server.
 *  - An optional `VITE_STEMFORGE_API` env var overrides for advanced setups.
 *  - The popup may be hydrated with `window.__STEMFORGE_API__` by the
 *    [jweb] host, which is what Lane C will likely do once it wires the
 *    iframe — read that first.
 */

import type {
  AssignPadRequest,
  ClearPadRequest,
  ExportRequest,
  IntentResponse,
  LoadManifestRequest,
  ProjectSpec,
  SetGroupFormatRequest,
} from "./types";

declare global {
  interface Window {
    __STEMFORGE_API__?: string;
  }
}

export const API_BASE: string = (() => {
  if (typeof window !== "undefined" && window.__STEMFORGE_API__) {
    return window.__STEMFORGE_API__.replace(/\/$/, "");
  }
  const envBase = import.meta.env.VITE_STEMFORGE_API as string | undefined;
  if (envBase) return envBase.replace(/\/$/, "");
  return ""; // same-origin relative URLs
})();

function url(path: string): string {
  return `${API_BASE}${path}`;
}

async function jsonRequest<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  const resp = await fetch(url(path), {
    ...init,
    headers: {
      "Content-Type": "application/json",
      Accept: "application/json",
      ...(init?.headers ?? {}),
    },
  });
  if (!resp.ok) {
    // Try to surface server-supplied error context if present.
    let detail = `${resp.status} ${resp.statusText}`;
    try {
      const body = await resp.json();
      if (body && typeof body === "object" && "errors" in body) {
        detail += ` — ${(body as { errors: string[] }).errors.join("; ")}`;
      }
    } catch {
      // Body wasn't JSON; ignore.
    }
    throw new Error(detail);
  }
  return (await resp.json()) as T;
}

/** GET /state — full ProjectSpec snapshot (also delivered via SSE). */
export function fetchState(): Promise<ProjectSpec> {
  return jsonRequest<ProjectSpec>("/state");
}

/** GET /healthz — used by ConnectionStatus tooltip + initial probe. */
export interface HealthResponse {
  ok: boolean;
  version?: string;
}
export function fetchHealth(): Promise<HealthResponse> {
  return jsonRequest<HealthResponse>("/healthz");
}

/** SSE stream URL. The hook owns the EventSource lifecycle. */
export function streamUrl(): string {
  return url("/state/stream");
}

/** Audio preview URL — fed directly to `<audio src=...>`. */
export function previewUrl(clipId: string): string {
  return url(`/preview/${encodeURIComponent(clipId)}`);
}

// --- Intents ----------------------------------------------------------------

function postIntent<TBody>(
  path: string,
  body: TBody,
): Promise<IntentResponse> {
  return jsonRequest<IntentResponse>(path, {
    method: "POST",
    body: JSON.stringify(body ?? {}),
  });
}

export const intents = {
  loadManifest: (body: LoadManifestRequest) =>
    postIntent("/intent/load-manifest", body),
  commit: () => postIntent("/intent/commit", {}),
  assignPad: (body: AssignPadRequest) => postIntent("/intent/assign-pad", body),
  clearPad: (body: ClearPadRequest) => postIntent("/intent/clear-pad", body),
  setGroupFormat: (body: SetGroupFormatRequest) =>
    postIntent("/intent/set-group-format", body),
  recompute: () => postIntent("/intent/recompute", {}),
  export: (body: ExportRequest) => postIntent("/intent/export", body),
};
