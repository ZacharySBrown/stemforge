// AUTO-GENERATED — do not edit. Run `uv run python scripts/gen_typescript_types.py` to regenerate.
// Source of truth: stemforge/configurator/schemas/


/**
 * One arrangement-view chunk in a forge.
 */
export interface ArrangementChunk {
  /** Relative path under the forge dir */
  audio_path: string;
  bar_position: number;
  chunk_id: string;
  duration_bars: number;
  duration_sec: number;
  source_position_sec: number;
  stem: "bass" | "drum" | "other" | "vocal";
}

/**
 * Arrangement manifest (``arrangement_manifest.json``).
 *
 * Schema shape from spec §2.2.
 */
export interface ArrangementManifest {
  bpm: number;
  chunks?: Array<ArrangementChunk>;
  first_downbeat_sec: number;
  forge_slug: string;
  /** SHA-256 of canonical chunks array */
  manifest_hash: string;
  schema_version?: 1;
  source_audio: string;
}

/**
 * Live-side clip state captured at COMMIT.
 *
 * Persisted so the next LOAD restores warp/loop faithfully.
 */
export interface ClipSettings {
  /** Loop end in bars (clip-relative) */
  loop_end_bar: number;
  /** Loop start in bars (clip-relative) */
  loop_start_bar?: number;
  /** Whether the clip is looping in Live */
  looping?: boolean;
  /** Clip's warp BPM in Live at commit time */
  warp_bpm: number;
}

/**
 * Top-level curation document.
 *
 * Persisted as YAML at ``~/stemforge/curations/<name>.yaml``.
 */
export interface Curation {
  /** Optional list of color hex strings (or named-palette refs) for the popup/device to render. Mirrors spec §2.3. */
  color_palette?: Array<string> | null;
  created_at: string;
  curation_version?: 1;
  /** Group letter (A, B, ...) → Group. Determined by target.groups. */
  groups?: Record<string, Group>;
  last_bounce?: LastBounce | null;
  last_export?: LastExport | null;
  modified_at: string;
  /** Unique curation name (matches filename without .yaml) */
  name: string;
  referenced_forges?: Array<ReferencedForge>;
  target: Target;
  /** Curation type. v1 implements 'deck' only; 'arrangement' reserved for v2. */
  type?: "arrangement" | "deck";
}

/**
 * One auto-curated clip in a forge.
 */
export interface ForgeClip {
  /** Relative path under the forge dir */
  audio_path: string;
  clip_id: string;
  duration_bars: number;
  /** [start_bar, end_bar] in source */
  source_bar_range: [number, number];
  stem: "bass" | "drum" | "other" | "vocal";
  tags?: Array<string>;
}

/**
 * Auto-curation manifest (``auto_curation_manifest.json``).
 *
 * Schema shape from spec §2.2.
 */
export interface ForgeManifest {
  bpm: number;
  clips?: Array<ForgeClip>;
  /** Template name to apply on LOAD-forge (no .adg suffix) */
  default_template?: string | null;
  first_downbeat_sec: number;
  forge_slug: string;
  /** SHA-256 of canonical clips array */
  manifest_hash: string;
  schema_version?: 1;
  /** Absolute path to original audio file */
  source_audio: string;
}

/**
 * A row of pads in a curation.
 *
 * EP-133 v1 has 4 groups (A/B/C/D), 12 pads each.
 */
export interface Group {
  /** Human-readable group label */
  label?: string;
  pads?: Array<Pad>;
  /** Template name (no .adg suffix). None = dry passthrough. */
  template?: string | null;
}

/**
 * Record of the most recent BOUNCE for this curation.
 */
export interface LastBounce {
  bounced_at: string;
  /** Relative path to bounce_manifest.json */
  manifest_path: string;
  /** pad_id → SHA-256 of bounced WAV (for diff detection) */
  pad_audio_hashes?: Record<string, string>;
}

/**
 * Record of the most recent EXPORT for this curation.
 */
export interface LastExport {
  exported_at: string;
  /** SHA-256 of the exported artifact bytes at write time. Mirrors LastBounce.pad_audio_hashes shape — used for diff detection so the popup can warn when a curation has changed since last export. */
  manifest_hash?: string | null;
  /** Absolute or relative path to exported artifact */
  output_path: string;
  target_format?: "ppak";
}

/**
 * A single slot in a curation's curated_layout.
 *
 * ``pad_id`` is required and identifies the slot (e.g. ``A01``).
 * ``source`` and ``clip_settings`` are omitted on empty pads.
 */
export interface Pad {
  clip_settings?: ClipSettings | null;
  /** Pad identifier, e.g. A01 */
  pad_id: string;
  source?: PadSource | null;
}

/**
 * Reference to the audio that lives in a pad.
 *
 * Two shapes are accepted, both honoured per spec §2.3:
 *
 * * **Forge-owned**: ``forge`` + ``clip_id`` + ``audio_path``. The pad's
 *   audio belongs to a discovered forge under ``~/stemforge/processed/``.
 *   Resolved at COMMIT time by the server's reverse-lookup.
 * * **External**: ``external_path`` alone. The pad's audio sits outside
 *   any tracked forge (user dragged in a file from elsewhere). The path
 *   is preserved verbatim; LOAD reads it as-is, no forge re-resolution.
 *
 * The two shapes are mutually exclusive — validated below.
 */
export interface PadSource {
  /** Cached resolved relative path under the forge dir (forge-owned only). Always recompute from the forge manifest at LOAD. */
  audio_path?: string | null;
  /** Clip ID within the forge's auto_curation_manifest (when forge-owned) */
  clip_id?: string | null;
  /** Absolute path to audio outside any known forge. Set iff this pad came from a file the server couldn't reverse-lookup. */
  external_path?: string | null;
  /** Forge slug (when forge-owned) */
  forge?: string | null;
}

/**
 * One entry in a curation's ``referenced_forges`` list.
 *
 * Used for stale-detection: if the forge's current manifest_hash differs
 * from the value recorded here, the popup surfaces a stale badge.
 */
export interface ReferencedForge {
  /** auto_curation_manifest hash at last commit */
  manifest_hash: string;
  slug: string;
}

/**
 * Server-side runtime state file.
 *
 * Keyed by the absolute path of a Live ``.als`` project file.
 */
export interface StemforgeState {
  /** Map of .als absolute path → active curation name */
  active_curations?: Record<string, string>;
  /** Most recent server port (mirrors .configurator_port) */
  last_known_port?: number | null;
  last_seen_at?: string | null;
  schema_version?: 1;
}

/**
 * Curation's target device + pad geometry.
 */
export interface Target {
  /** Target device identifier (ep133 only in v1) */
  device?: string;
  /** Number of groups */
  groups?: number;
  /** Optional human-readable label for the target hardware (e.g. 'Studio EP-133'). Distinct from per-group Group.label. */
  label?: string | null;
  /** Pads per group */
  pads_per_group?: number;
}
