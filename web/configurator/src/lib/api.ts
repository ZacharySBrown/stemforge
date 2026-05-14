/**
 * HTTP client for the StemForge configurator server (Lane 1B).
 *
 * Base URL resolution:
 *  - In production the popup is served at the same origin as the API (the
 *    Python server mounts `dist/` at `/`), so relative URLs Just Work.
 *  - In dev (`npm run dev`), `vite.config.ts` proxies the relevant prefixes
 *    to the local server.
 *  - An optional `VITE_STEMFORGE_API` env var overrides for advanced setups.
 *  - The popup may be hydrated with `window.__STEMFORGE_API__` by the
 *    [jweb] host (Lane 1C).
 *
 * Endpoint catalog mirrors spec §4.3. Types come from `popup-types.ts`
 * which re-exports the Phase 0 generated TS types and adds server-defined
 * wrapper shapes (`ForgeIndexResponse`, `CurationIndexResponse`, etc.).
 */

import type { Curation } from "./api-types.generated";
import type {
  ApiResult,
  CreateCurationRequest,
  CurationIndexResponse,
  ExportCurationRequest,
  ForgeIndexResponse,
  ReAnchorRequest,
  ReCurateRequest,
  SaveAsRequest,
  SetCurationTargetRequest,
  SetGroupTemplateRequest,
  TemplateIndexResponse,
} from "./popup-types";

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

/**
 * Sentinel `als_path` for popup-initiated curation intents.
 *
 * The Phase 4B server keys per-host active curations on `als_path` and
 * accepts `__popup__` as the standalone-popup identifier. Sending it
 * explicitly is a noop against the post-P0-3 server (which defaults missing
 * `als_path` to this same sentinel) but ALSO unblocks the pre-fix server
 * that 422'd on empty bodies. Keep both endpoints sending it.
 */
const POPUP_ALS_SENTINEL_BODY = JSON.stringify({ als_path: "__popup__" });

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
    public errors: string[] = [],
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function jsonRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(url(path), {
    ...init,
    headers: {
      "Content-Type": "application/json",
      Accept: "application/json",
      ...(init?.headers ?? {}),
    },
  });
  if (!resp.ok) {
    let errors: string[] = [];
    try {
      const body = await resp.json();
      if (body && typeof body === "object" && "errors" in body) {
        errors = (body as { errors: string[] }).errors ?? [];
      }
    } catch {
      // Body wasn't JSON; leave errors empty.
    }
    const detail =
      errors.length > 0
        ? `${resp.status} ${resp.statusText} — ${errors.join("; ")}`
        : `${resp.status} ${resp.statusText}`;
    throw new ApiError(detail, resp.status, errors);
  }
  return (await resp.json()) as T;
}

// ── Health + SSE ────────────────────────────────────────────────────────────

export interface HealthResponse {
  ok: boolean;
  version?: string;
}
export function fetchHealth(): Promise<HealthResponse> {
  return jsonRequest<HealthResponse>("/healthz");
}

/** SSE stream URL — owned by `useProjectState`. */
export function streamUrl(): string {
  return url("/state/stream");
}

/** Audio preview URL — fed directly to `<audio src=...>`. */
export function previewUrl(clipId: string): string {
  return url(`/preview/${encodeURIComponent(clipId)}`);
}

// ── /templates (Phase 3A) ───────────────────────────────────────────────────

/** Scan `~/stemforge/templates/*.adg` and return one row per template. */
export function fetchTemplates(): Promise<TemplateIndexResponse> {
  return jsonRequest<TemplateIndexResponse>("/templates");
}

// ── /forges ─────────────────────────────────────────────────────────────────

export function fetchForges(): Promise<ForgeIndexResponse> {
  return jsonRequest<ForgeIndexResponse>("/forges");
}

export function loadForge(slug: string): Promise<ApiResult> {
  return jsonRequest<ApiResult>(`/forges/${encodeURIComponent(slug)}/load`, {
    method: "POST",
    body: "{}",
  });
}

export function unloadForge(slug: string): Promise<ApiResult> {
  return jsonRequest<ApiResult>(`/forges/${encodeURIComponent(slug)}/unload`, {
    method: "POST",
    body: "{}",
  });
}

export function reAnchorForge(
  slug: string,
  body: ReAnchorRequest,
): Promise<ApiResult> {
  return jsonRequest<ApiResult>(
    `/forges/${encodeURIComponent(slug)}/re-anchor`,
    { method: "POST", body: JSON.stringify(body) },
  );
}

export function reCurateForge(
  slug: string,
  body: ReCurateRequest = {},
): Promise<ApiResult> {
  return jsonRequest<ApiResult>(
    `/forges/${encodeURIComponent(slug)}/re-curate`,
    { method: "POST", body: JSON.stringify(body) },
  );
}

export function showForgeInFinder(slug: string): Promise<ApiResult> {
  return jsonRequest<ApiResult>(
    `/forges/${encodeURIComponent(slug)}/reveal`,
    { method: "POST", body: "{}" },
  );
}

// ── /curations ──────────────────────────────────────────────────────────────

export function fetchCurations(): Promise<CurationIndexResponse> {
  return jsonRequest<CurationIndexResponse>("/curations");
}

/** Fetch a single curation YAML doc (for the center panel). */
export function fetchCuration(name: string): Promise<Curation> {
  return jsonRequest<Curation>(`/curations/${encodeURIComponent(name)}`);
}

export function createCuration(body: CreateCurationRequest): Promise<ApiResult> {
  return jsonRequest<ApiResult>("/curations", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function openCuration(name: string): Promise<ApiResult> {
  return jsonRequest<ApiResult>(
    `/curations/${encodeURIComponent(name)}/open`,
    { method: "POST", body: POPUP_ALS_SENTINEL_BODY },
  );
}

export function saveCurationAs(
  name: string,
  body: SaveAsRequest,
): Promise<ApiResult> {
  return jsonRequest<ApiResult>(
    `/curations/${encodeURIComponent(name)}/save-as`,
    { method: "POST", body: JSON.stringify(body) },
  );
}

export function renameCuration(
  name: string,
  body: SaveAsRequest,
): Promise<ApiResult> {
  return jsonRequest<ApiResult>(
    `/curations/${encodeURIComponent(name)}/rename`,
    { method: "POST", body: JSON.stringify(body) },
  );
}

export function deleteCuration(name: string): Promise<ApiResult> {
  return jsonRequest<ApiResult>(`/curations/${encodeURIComponent(name)}`, {
    method: "DELETE",
  });
}

export function patchCurationTemplate(
  name: string,
  body: SetGroupTemplateRequest,
): Promise<ApiResult> {
  return jsonRequest<ApiResult>(
    `/curations/${encodeURIComponent(name)}/template`,
    { method: "PATCH", body: JSON.stringify(body) },
  );
}

export function patchCurationTarget(
  name: string,
  body: SetCurationTargetRequest,
): Promise<ApiResult> {
  return jsonRequest<ApiResult>(
    `/curations/${encodeURIComponent(name)}/target`,
    { method: "PATCH", body: JSON.stringify(body) },
  );
}

export function exportCuration(
  name: string,
  body: ExportCurationRequest,
): Promise<ApiResult> {
  return jsonRequest<ApiResult>(
    `/curations/${encodeURIComponent(name)}/export`,
    { method: "POST", body: JSON.stringify(body) },
  );
}

export function triggerBounce(name: string): Promise<ApiResult> {
  return jsonRequest<ApiResult>(
    `/curations/${encodeURIComponent(name)}/trigger-bounce`,
    { method: "POST", body: "{}" },
  );
}

/**
 * Phase 4B — "Refresh from forge": re-derive every forge-owned pad's
 * `audio_path` against the current `auto_curation_manifest.json` and
 * rewrite `referenced_forges` hashes so the curation no longer reads as
 * stale.
 *
 * Returns the refreshed `Curation` document. Idempotent: a curation with
 * no stale references comes back unchanged (modulo `modified_at`).
 */
export function refreshCuration(name: string): Promise<Curation> {
  return jsonRequest<Curation>(
    `/curations/${encodeURIComponent(name)}/refresh`,
    { method: "POST", body: "{}" },
  );
}

/** Close the currently-active curation (clears the active marker server-side). */
export function closeActiveCuration(): Promise<ApiResult> {
  return jsonRequest<ApiResult>("/curations/active/close", {
    method: "POST",
    body: POPUP_ALS_SENTINEL_BODY,
  });
}

/** Trigger the server-side native file dialog → load-manifest cascade. */
export function pickManifest(): Promise<ApiResult> {
  return jsonRequest<ApiResult>("/intent/pick-manifest", {
    method: "POST",
    body: "{}",
  });
}

/** Response shape for `POST /intent/pick-save-path`. */
export interface PickSavePathResponse {
  ok: boolean;
  /** Chosen POSIX path, or null when the user cancelled the dialog. */
  path: string | null;
}

/** Body for `POST /intent/pick-save-path`. */
export interface PickSavePathRequest {
  default_name?: string;
  default_dir?: string;
  prompt?: string;
}

/** Trigger the server-side osascript save-as dialog and return the chosen path. */
export function pickSavePath(
  body: PickSavePathRequest = {},
): Promise<PickSavePathResponse> {
  return jsonRequest<PickSavePathResponse>("/intent/pick-save-path", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

// Convenience namespace for the legacy import-shape callers expect.
export const api = {
  fetchHealth,
  streamUrl,
  previewUrl,
  fetchForges,
  fetchTemplates,
  loadForge,
  unloadForge,
  reAnchorForge,
  reCurateForge,
  showForgeInFinder,
  fetchCurations,
  fetchCuration,
  createCuration,
  openCuration,
  saveCurationAs,
  renameCuration,
  deleteCuration,
  patchCurationTemplate,
  patchCurationTarget,
  exportCuration,
  triggerBounce,
  refreshCuration,
  closeActiveCuration,
  pickManifest,
  pickSavePath,
};
