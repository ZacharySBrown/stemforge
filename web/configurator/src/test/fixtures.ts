/**
 * Test fixtures — sample server responses that mirror spec §4.3.
 *
 * These shapes are the contract between Lane 1B's server and Lane 1D's UI.
 * When Lane 1B's tests load YAML fixtures (`stale-reference.yaml` et al),
 * those fixtures should produce equivalent JSON to what's here.
 */

import type { Curation } from "@/lib/api-types.generated";
import type {
  CurationIndexResponse,
  ForgeIndexResponse,
  TemplateIndexResponse,
} from "@/lib/popup-types";

export const FORGE_INDEX_OK: ForgeIndexResponse = {
  forges: [
    {
      slug: "definition-of-sound",
      name: "Definition Of Sound",
      source_audio: "/Users/zak/mus/raw/definition.wav",
      bpm: 90.0,
      clip_count: 46,
      chunk_count: 12,
      manifest_hash: "sha256:abc123fresh",
      loaded: true,
    },
    {
      slug: "ooh-la-la",
      name: "Ooh La La",
      source_audio: "/Users/zak/mus/raw/ooh-la-la.wav",
      bpm: 116.2,
      clip_count: 32,
      chunk_count: 8,
      manifest_hash: "sha256:def456fresh",
      loaded: false,
    },
    {
      slug: "believer",
      bpm: 124.0,
      clip_count: 28,
      chunk_count: 6,
      manifest_hash: "sha256:newhash789",
      loaded: false,
    },
  ],
};

export const FORGE_INDEX_EMPTY: ForgeIndexResponse = { forges: [] };

export const TEMPLATE_INDEX_OK: TemplateIndexResponse = {
  templates: [
    {
      name: "drum-rack-classic",
      path: "/Users/zak/stemforge/templates/drum-rack-classic.adg",
      modified_at: "2026-05-12T08:00:00Z",
      size_bytes: 24576,
      description: "Tight-comp drum rack",
    },
    {
      name: "VOCAL_HI_KEY",
      path: "/Users/zak/stemforge/templates/VOCAL_HI_KEY.adg",
      modified_at: "2026-05-11T12:00:00Z",
      size_bytes: 12288,
    },
    {
      name: "vocal-bloom",
      path: "/Users/zak/stemforge/templates/vocal-bloom.adg",
      modified_at: "2026-05-10T10:00:00Z",
      size_bytes: 18432,
    },
  ],
};

export const TEMPLATE_INDEX_EMPTY: TemplateIndexResponse = { templates: [] };

export const CURATION_INDEX_OK: CurationIndexResponse = {
  curations: [
    {
      name: "verse_swap_v1",
      target_device: "ep133",
      target_groups: 4,
      target_pads_per_group: 12,
      modified_at: "2026-05-13T16:30:00Z",
      created_at: "2026-05-12T10:00:00Z",
      last_bounced_at: "2026-05-13T15:00:00Z",
      last_exported_at: null,
      active: true,
    },
    {
      name: "live_set_oct_2026",
      target_device: "ep133",
      target_groups: 4,
      target_pads_per_group: 12,
      modified_at: "2026-05-10T08:00:00Z",
      active: false,
    },
  ],
};

export const CURATION_INDEX_EMPTY: CurationIndexResponse = { curations: [] };

/**
 * Curation fixture with a reference at the FRESH hash (no stale badges).
 */
export const CURATION_FRESH: Curation = {
  name: "verse_swap_v1",
  created_at: "2026-05-12T10:00:00Z",
  modified_at: "2026-05-13T16:30:00Z",
  target: { device: "ep133", groups: 4, pads_per_group: 12 },
  referenced_forges: [
    { slug: "definition-of-sound", manifest_hash: "sha256:abc123fresh" },
  ],
  groups: {
    A: {
      label: "vocal hi",
      template: "VOCAL_HI_KEY",
      pads: [
        {
          pad_id: "A01",
          source: {
            forge: "definition-of-sound",
            clip_id: "vocal-bar4-8",
            audio_path: "clips/vocal-bar4-8.wav",
          },
        },
        { pad_id: "A02" },
      ],
    },
    B: {
      label: "drums",
      template: "DRUM_PUNCH",
      pads: [
        {
          pad_id: "B01",
          source: {
            forge: "definition-of-sound",
            clip_id: "drum-bar2-4",
            audio_path: "clips/drum-bar2-4.wav",
          },
        },
      ],
    },
  },
  last_bounce: null,
  last_export: null,
};

/**
 * Curation fixture where the referenced forge has a DIFFERENT hash from
 * the current forge — drives the stale-badge tests. Mirrors the
 * `stale-reference.yaml` fixture Lane 1B keeps server-side.
 */
export const CURATION_STALE: Curation = {
  ...CURATION_FRESH,
  name: "stale_curation",
  referenced_forges: [
    { slug: "definition-of-sound", manifest_hash: "sha256:OLD-hash-mismatch" },
  ],
};
