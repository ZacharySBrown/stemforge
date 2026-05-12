/**
 * Type mirrors of Lane A's Pydantic ProjectSpec shapes.
 *
 * NOTE: these are the runtime shapes the frontend consumes. The authoritative
 * definition lives in `stemforge/scene_model/` on the server side. Treat all
 * fields as optional-tolerant — Lane A may evolve the contract and we should
 * not crash if a field is missing.
 *
 * Per Decision 14, the pad canvas is the slot table. Per Decision 16, format
 * is per-group. Per Decision 13, clip identity is `audio_hash`.
 */

export type GroupKey = "A" | "B" | "C" | "D";

export type FormatProfile =
  | "vocal"
  | "drum"
  | "texture"
  | "preserve_source";

/** A single audio clip — content-addressed by `audio_hash`. */
export interface ClipRef {
  audio_hash: string;
  /** Display name (filename stem, curated label, etc.). */
  name?: string;
  /** Source path (advisory; identity is the hash). */
  path?: string;
  /** Duration in seconds (post-trim). */
  duration_sec?: number;
  /** Source-tempo BPM if known. */
  source_bpm?: number | null;
  /** Stem family if classified — drums / vocals / bass / other / texture. */
  stem?: string | null;
}

/** One pad cell — Group × pad-index → optional clip. */
export interface PadSpec {
  pad: number;                  // 1..12
  clip_id?: string | null;      // audio_hash; null = empty slot
  name?: string | null;
  mode?: "oneshot" | "key" | "loop" | null;
  /** Trim points in seconds, relative to source clip. */
  start_offset_sec?: number | null;
  end_offset_sec?: number | null;
}

/** A group of 12 pads with shared format settings. */
export interface GroupSpec {
  group: GroupKey;
  format_profile: FormatProfile;
  pads: PadSpec[];
  /** Display label override; falls back to group-key conventions. */
  label?: string | null;
}

/** A single scene — collection of group/pad assignments. */
export interface SceneSpec {
  id: string;
  name: string;
  groups: GroupSpec[];
}

/** A song — container for scenes. v1 forces n=1; schema is multi-song-ready. */
export interface Song {
  id: string;
  name: string;
  scenes: SceneSpec[];
}

/** Target capacity report, derived server-side. */
export interface CapacityReport {
  used_bytes: number;
  cap_bytes: number;          // 64 MiB on EP-133
  /** Optional per-group rollup so the status bar can show drift hot-spots. */
  per_group?: Partial<Record<GroupKey, number>>;
}

/** Full project state as broadcast by the SSE stream. */
export interface ProjectSpec {
  schema_version: 2;
  project_name?: string | null;
  /** Target chip — "ep133" for v1; future Koala/Chompi land here. */
  target?: "ep133" | "koala" | "chompi" | string;
  songs: Song[];
  /** Server-computed memory rollup (Decision 16). */
  capacity?: CapacityReport | null;
  /** Manifest path currently loaded — surfaced in TopBar microcopy. */
  manifest_path?: string | null;
  /** Clip-count rollup for top-bar microcopy. */
  clip_count?: number | null;
  /** Timing for last operation, surfaced in StatusBar. */
  last_operation?: {
    name: string;
    duration_ms: number;
    finished_at: string;       // ISO timestamp
  } | null;
}

/** Standard intent response shape from the HTTP server. */
export interface IntentResponse {
  ok: boolean;
  state: ProjectSpec | null;
  warnings: string[];
  errors: string[];
}

// --- SSE event envelopes ------------------------------------------------------

/** State events deliver a full ProjectSpec snapshot. */
export interface SseStateEvent {
  type: "state";
  payload: ProjectSpec;
}

/** Log events are advisory and routed to the toast layer. */
export interface SseLogEvent {
  type: "log";
  payload: {
    level: "info" | "warn" | "error";
    message: string;
  };
}

/** Progress events drive the inline progress bar. */
export interface SseProgressEvent {
  type: "progress";
  payload: {
    operation: string;
    fraction: number; // 0..1
    message?: string;
    /** When true, the operation completed; UI hides the bar. */
    done?: boolean;
  };
}

/** Server-side errors get a discrete event. */
export interface SseErrorEvent {
  type: "error";
  payload: {
    message: string;
    context?: string;
  };
}

export type SseEvent =
  | SseStateEvent
  | SseLogEvent
  | SseProgressEvent
  | SseErrorEvent;

// --- Intent request bodies ----------------------------------------------------

export interface LoadManifestRequest {
  manifest_path: string;
}

export interface AssignPadRequest {
  group: GroupKey;
  pad: number;
  clip_id: string;
}

export interface ClearPadRequest {
  group: GroupKey;
  pad: number;
}

export interface SetGroupFormatRequest {
  group: GroupKey;
  format: FormatProfile;
}

export interface ExportRequest {
  target: "ep133";
  out_path: string;
}

/** Connection state for the live SSE stream. */
export type ConnectionStatus =
  | "idle"
  | "connecting"
  | "connected"
  | "disconnected"
  | "error";
