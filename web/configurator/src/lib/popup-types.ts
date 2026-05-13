/**
 * Popup-only runtime types — UI helpers and contract shapes that aren't
 * generated from the Pydantic schemas in `stemforge/configurator/schemas/`.
 *
 * The authoritative types for `Curation`, `ForgeManifest`, `Pad`, etc. are
 * in `api-types.generated.ts` and re-exported below for convenience.
 *
 * Endpoint contract shapes (`GET /forges` index entries, `GET /curations`
 * index entries) are duplicated here because they are SERVER-DEFINED ad-hoc
 * response wrappers, not first-class Pydantic models. When Lane 1B nails
 * the response wrapper down, we'll regenerate them via codegen and delete
 * the manual mirrors.
 */

import type { Curation, ForgeManifest, ReferencedForge } from "./api-types.generated";

export type {
  ArrangementChunk,
  ArrangementManifest,
  ClipSettings,
  Curation,
  ForgeClip,
  ForgeManifest,
  Group,
  LastBounce,
  LastExport,
  Pad,
  PadSource,
  ReferencedForge,
  StemforgeState,
  Target,
} from "./api-types.generated";

// ── Endpoint response wrappers (server-defined; not in generated schema) ────

/**
 * One row in `GET /forges` — a lightweight projection of a forge for the
 * left-rail list view.
 */
export interface ForgeIndexEntry {
  /** Forge slug (matches dir name under ~/stemforge/processed/) */
  slug: string;
  /** Display name; falls back to slug */
  name?: string;
  /** Absolute path of the source audio (advisory) */
  source_audio?: string;
  /** Tempo from the auto_curation_manifest */
  bpm?: number;
  /** Total clips count */
  clip_count?: number;
  /** Total arrangement-view chunks */
  chunk_count?: number;
  /** Current manifest_hash — UI diffs against curation refs for staleness */
  manifest_hash: string;
  /** True if the device has this forge loaded into Live right now */
  loaded?: boolean;
}

/** Response shape for `GET /forges`. */
export interface ForgeIndexResponse {
  forges: ForgeIndexEntry[];
}

/**
 * One row in `GET /curations` — a list-view projection of a curation file.
 */
export interface CurationIndexEntry {
  name: string;
  /** Target device, e.g. "ep133" */
  target_device?: string;
  /** Group × pads_per_group, for the rail target chip */
  target_groups?: number;
  target_pads_per_group?: number;
  modified_at: string;
  created_at?: string;
  /** Last-bounce ISO timestamp if any */
  last_bounced_at?: string | null;
  /** Last-export ISO timestamp if any */
  last_exported_at?: string | null;
  /** Whether this curation is the active one (popup highlights it) */
  active?: boolean;
}

/** Response shape for `GET /curations`. */
export interface CurationIndexResponse {
  curations: CurationIndexEntry[];
}

/** Standard server response wrapper for write endpoints. */
export interface ApiResult {
  ok: boolean;
  warnings?: string[];
  errors?: string[];
}

// ── PATCH bodies ─────────────────────────────────────────────────────────────

/** Body for `PATCH /curations/{name}/template`. */
export interface SetGroupTemplateRequest {
  group: string; // "A" | "B" | ...
  template_name: string | null;
}

/** Body for `PATCH /curations/{name}/target`. */
export interface SetCurationTargetRequest {
  device?: string;
  groups?: number;
  pads_per_group?: number;
  /** Optional label edit, surfaced because Lane 1B's contract attaches the
   *  group-label edit to the target endpoint by spec convention. */
  label?: { group: string; label: string };
}

/** Body for `POST /curations`. */
export interface CreateCurationRequest {
  name: string;
  target: {
    device: string;
    groups: number;
    pads_per_group: number;
  };
}

/** Body for `POST /curations/{name}/save-as`. */
export interface SaveAsRequest {
  new_name: string;
}

/** Body for `POST /curations/{name}/export`. */
export interface ExportCurationRequest {
  out_path: string;
  target_format?: "ppak";
}

/** Body for `POST /forges/{slug}/re-anchor`. */
export interface ReAnchorRequest {
  downbeat_sec: number;
}

/** Body for `POST /forges/{slug}/re-curate`. */
export interface ReCurateRequest {
  params?: Record<string, unknown>;
}

// ── SSE event envelopes ──────────────────────────────────────────────────────

/**
 * Typed SSE event payloads emitted by Lane 1B's server.
 *
 * The server emits events with `event: state`, `event: progress`, `event: log`
 * lines (per spec §4.4 fix and the 2026-05-13 SSE-pattern bug). The popup
 * subscribes via `addEventListener(<type>, …)`, NOT `onmessage`.
 */
export interface SseStatePayload {
  /** Current active curation, or null if none */
  curation: Curation | null;
  /** Most recent active-curation set timestamp */
  active_curation_name?: string | null;
}

export interface SseProgressPayload {
  operation: string;
  fraction: number; // 0..1
  message?: string;
  done?: boolean;
}

export interface SseLogPayload {
  level: "info" | "warn" | "error";
  message: string;
}

/** Connection state for the live SSE stream. */
export type ConnectionStatus =
  | "idle"
  | "connecting"
  | "connected"
  | "disconnected"
  | "error";

// ── Stale-reference helpers ──────────────────────────────────────────────────

/**
 * Compare a curation's `referenced_forges` against a forge's current
 * manifest_hash. Returns true if the curation references the forge AT A
 * DIFFERENT hash than the current one (i.e. the forge has been re-curated
 * or re-anchored since this curation last touched it).
 *
 * Returns false if the curation doesn't reference the forge at all.
 */
export function isForgeStale(
  refs: ReferencedForge[] | undefined,
  forge: Pick<ForgeIndexEntry, "slug" | "manifest_hash">,
): boolean {
  if (!refs) return false;
  const ref = refs.find((r) => r.slug === forge.slug);
  if (!ref) return false;
  return ref.manifest_hash !== forge.manifest_hash;
}

/**
 * Variant for `ForgeManifest` rather than the lighter `ForgeIndexEntry`.
 */
export function isManifestStale(
  refs: ReferencedForge[] | undefined,
  forge: Pick<ForgeManifest, "forge_slug" | "manifest_hash">,
): boolean {
  return isForgeStale(refs, {
    slug: forge.forge_slug,
    manifest_hash: forge.manifest_hash,
  });
}
