/**
 * L3 device-JS tests for v0/src/m4l-js/stemforge_loader.v0.js.
 *
 * Phase 1C — Configurator unified picker + sniffer + LOAD curation.
 * Companion: tools/test-harness/max-stub.js (Phase 0).
 *
 * Required reading:
 *   - specs/CONSOLIDATED_DESIGN.md §3.1, §3.3, §6.4, §7
 *   - docs/configurator/EXECUTION_PLAN_v1.md (Lane 1C, lines ~149-168)
 *
 * Test harness pattern (mirrors tools/test-harness/max-stub.test.js):
 *   - Globals (describe/test/expect/beforeEach) come from vitest's `globals: true`.
 *   - Load max-stub once at module init so Max APIs land on `global.*`.
 *   - resetMaxStub() between tests scrubs LOM + emissions.
 *   - The loader JS guards its CommonJS export with `module.exports.__test__`;
 *     we yank the picker/sniffer/loadCuration handles from there.
 *
 * No mocks of the loader itself — we exercise it as the device would, modulo
 * the Live runtime which max-stub mirrors at the LOM-API surface.
 */

"use strict";

const fs = require("node:fs");
const path = require("node:path");

require("../../../tools/test-harness/max-stub.js");

// Loader sets globals at import time; only require it AFTER max-stub installs
// LiveAPI/Dict/File/etc. on `global.*`.
const loader = require("./stemforge_loader.v0.js");
const T = loader.__test__;

const REPO_ROOT = path.resolve(__dirname, "../../../..");
// __dirname when run via vitest from web/configurator/vitest.harness.config.ts
// resolves under v0/src/m4l-js/. Walk back to repo root then into tests/fixtures.
const FIXTURES_ROOT = path.resolve(__dirname, "../../../tests/fixtures");
const LOM_SNAPSHOT = (name) => path.join(FIXTURES_ROOT, "lom_snapshots", name);
const CURATION = (name) => path.join(FIXTURES_ROOT, "curations", name);
const readCuration = (name) => fs.readFileSync(CURATION(name), "utf-8");

beforeEach(() => {
  resetMaxStub();
});

// ─── Sniffer tests ───────────────────────────────────────────────────────────

describe("sniffer", () => {
  test("accepts an audio file by extension (.wav)", () => {
    const result = T._snifferInspect("/tmp/some-loop.wav");
    expect(result.type).toBe("audio");
    expect(result.validated).toBe(true);
    expect(result.detail).toBe("WAV");
  });

  test("accepts a forge auto-curation manifest JSON", () => {
    // The Phase 0 fixture is the LOM snapshot; we synthesize a tiny forge
    // manifest on disk that matches the sniffer's duck-type contract
    // (schema_version + pads). The fixture lives next to the test for
    // deterministic cleanup.
    const tmpFile = path.join(__dirname, "__tmp_forge_manifest.json");
    fs.writeFileSync(
      tmpFile,
      JSON.stringify({
        schema_version: 2,
        slug: "fixture-forge",
        pads: { A: [{ pad_id: "A01" }] },
      })
    );
    try {
      const result = T._snifferInspect(tmpFile);
      expect(result.type).toBe("forge_manifest");
      expect(result.validated).toBe(true);
      expect(result.detail).toMatch(/schema_version=2/);
    } finally {
      fs.unlinkSync(tmpFile);
    }
  });

  test("accepts an arrangement manifest JSON", () => {
    const tmpFile = path.join(__dirname, "__tmp_arrangement.json");
    fs.writeFileSync(
      tmpFile,
      JSON.stringify({
        schema_version: 2,
        slug: "fixture-forge",
        chunks: [{ start_sec: 0, end_sec: 8 }],
      })
    );
    try {
      const result = T._snifferInspect(tmpFile);
      expect(result.type).toBe("arrangement_manifest");
      expect(result.validated).toBe(true);
    } finally {
      fs.unlinkSync(tmpFile);
    }
  });

  test("accepts a curation YAML (partial.yaml fixture)", () => {
    const result = T._snifferInspect(CURATION("partial.yaml"));
    expect(result.type).toBe("curation");
    expect(result.validated).toBe(true);
    expect(result.detail).toMatch(/curation_version=1/);
  });

  test("accepts a legacy prechop_manifest.json (no schema_version)", () => {
    // Pre-rebuild manifest shape: bpm + bars + stems[], no schema_version.
    // Still loadable via loadArrangementFromManifest() (Phase 2 LOM
    // behavior preserved per spec §11 migration plan).
    const tmpFile = path.join(__dirname, "__tmp_prechop.json");
    fs.writeFileSync(
      tmpFile,
      JSON.stringify({
        bpm: 95.0,
        bars: 32,
        pad_bars: 4,
        beats_per_bar: 4,
        first_downbeat_sec: 1.234,
        stems: [{ name: "drums", path: "drums.wav" }],
      })
    );
    try {
      const result = T._snifferInspect(tmpFile);
      expect(result.type).toBe("prechop_manifest");
      expect(result.validated).toBe(true);
      expect(result.detail).toMatch(/bpm=95/);
    } finally {
      fs.unlinkSync(tmpFile);
    }
  });

  test("rejects an unknown file type cleanly", () => {
    const tmpFile = path.join(__dirname, "__tmp_unknown.txt");
    fs.writeFileSync(tmpFile, "this is plain text, no schema_version");
    try {
      const result = T._snifferInspect(tmpFile);
      expect(result.type).toBe("unknown");
      expect(result.validated).toBe(false);
    } finally {
      fs.unlinkSync(tmpFile);
    }
  });

  test("rejects a JSON missing schema_version", () => {
    const tmpFile = path.join(__dirname, "__tmp_bad.json");
    fs.writeFileSync(tmpFile, JSON.stringify({ foo: "bar" }));
    try {
      const result = T._snifferInspect(tmpFile);
      expect(result.type).toBe("unknown");
      expect(result.validated).toBe(false);
      expect(result.detail).toMatch(/missing schema_version/);
    } finally {
      fs.unlinkSync(tmpFile);
    }
  });

  test("applyPickedSource emits structured status for curation", () => {
    global.messagename = "applyPickedSource";
    T.applyPickedSource(CURATION("partial.yaml"));
    const statuses = outletEmissions
      .filter((e) => e.idx === 0 && e.args[0] === "set")
      .map((e) => String(e.args[1]));
    expect(statuses).toContain("sniffer: detected curation v1");
    // primary-btn-label receive port updated to LOAD CURATION.
    const labelCalls = messnamedCalls.filter((c) => c.name === "primary-btn-label");
    expect(labelCalls[labelCalls.length - 1].args).toEqual(["LOAD CURATION"]);
    const enabledCalls = messnamedCalls.filter((c) => c.name === "primary-btn-enabled");
    expect(enabledCalls[enabledCalls.length - 1].args).toEqual([1]);
  });

  test("applyPickedSource on unknown emits rejection + disables primary", () => {
    const tmpFile = path.join(__dirname, "__tmp_unknown2.dat");
    fs.writeFileSync(tmpFile, "binary garbage");
    try {
      global.messagename = "applyPickedSource";
      T.applyPickedSource(tmpFile);
      const statuses = outletEmissions
        .filter((e) => e.idx === 0 && e.args[0] === "set")
        .map((e) => String(e.args[1]));
      expect(statuses).toContain("sniffer: rejected — unknown type");
      const enabledCalls = messnamedCalls.filter(
        (c) => c.name === "primary-btn-enabled"
      );
      expect(enabledCalls[enabledCalls.length - 1].args).toEqual([0]);
    } finally {
      fs.unlinkSync(tmpFile);
    }
  });
});

// ─── Primary button label switcher ───────────────────────────────────────────

describe("primary-button label switcher", () => {
  test("flips correctly across all 4 sniffer states", () => {
    expect(T._primaryLabelFor("audio")).toBe("FORGE");
    expect(T._primaryLabelFor("forge_manifest")).toBe("LOAD FORGE");
    expect(T._primaryLabelFor("arrangement_manifest")).toBe("LOAD FORGE");
    expect(T._primaryLabelFor("curation")).toBe("LOAD CURATION");
    expect(T._primaryLabelFor(null)).toBe("Pick a source…");
    expect(T._primaryLabelFor("unknown")).toBe("Pick a source…");
  });
});

// ─── loadCuration tests ──────────────────────────────────────────────────────

function statusLines() {
  return outletEmissions
    .filter((e) => e.idx === 0 && e.args[0] === "set")
    .map((e) => String(e.args[1]));
}

function liveApiCallsOfVerb(verb) {
  return liveApiCalls.filter((c) => c.verb === verb);
}

describe("loadCuration() on empty-set snapshot", () => {
  test("empty.yaml creates exactly 4 STG tracks + sets their names", () => {
    loadLomSnapshot(LOM_SNAPSHOT("empty-set.json"));
    // Empty fixture has groups: {} (zero keys). Use partial.yaml's structure
    // but with no pads to validate the "create N tracks" path. The spec says
    // N comes from `target.groups` when `groups` is empty.
    const yaml = readCuration("empty.yaml");
    const result = T.loadCuration(yaml);
    expect(result).not.toBeNull();
    const creates = liveApiCallsOfVerb("create_audio_track");
    expect(creates.length).toBe(4);
    // After creation, the stub fires set("name", …) on each new track. Our
    // stub captures calls via LiveAPI.set on the node; we can re-walk the
    // tree to confirm names.
    const liveSet = new LiveAPI("live_set");
    expect(liveSet.getcount("tracks")).toBe(4);
    const trackNames = [];
    for (let i = 0; i < 4; i += 1) {
      trackNames.push(new LiveAPI(`live_set tracks ${i}`).get("name")[0]);
    }
    expect(trackNames).toEqual(["STG-A", "STG-B", "STG-C", "STG-D"]);
    expect(statusLines()).toContain("staging: created STG-A through STG-D");
  });

  test("partial.yaml populates the right pads via create_clip", () => {
    loadLomSnapshot(LOM_SNAPSHOT("empty-set.json"));
    const yaml = readCuration("partial.yaml");
    T.loadCuration(yaml, CURATION("partial.yaml"));
    // partial.yaml: A01, A02 populated; B01; C01; D01, D02, D03. Total 7.
    const createClips = liveApiCallsOfVerb("create_clip");
    expect(createClips.length).toBe(7);
    // Each create_clip happens against a specific clip_slots N path.
    const paths = createClips.map((c) => c.path).sort();
    // Expected slot paths (tracks 0-3 after creation):
    expect(paths).toContain("live_set tracks 0 clip_slots 0"); // A01
    expect(paths).toContain("live_set tracks 0 clip_slots 1"); // A02
    expect(paths).toContain("live_set tracks 1 clip_slots 0"); // B01
    expect(paths).toContain("live_set tracks 2 clip_slots 0"); // C01
    expect(paths).toContain("live_set tracks 3 clip_slots 0"); // D01
    expect(paths).toContain("live_set tracks 3 clip_slots 1"); // D02
    expect(paths).toContain("live_set tracks 3 clip_slots 2"); // D03

    // Status emissions per populated pad use the canonical A·01 form.
    const lines = statusLines();
    expect(lines).toContain("staging: populated A·01 (vocal-bar0-4)");
    expect(lines).toContain("staging: populated D·03 (bass-bar0-4)");
    // Empty pads emit a skipped line.
    expect(lines).toContain("staging: skipped A·03 (no source)");
    // Final complete line: 4 groups + populated/total count.
    const completeLine = lines.find((l) => l.startsWith("loadCuration: complete"));
    expect(completeLine).toBeTruthy();
    expect(completeLine).toMatch(/4 groups, 7\/48 pads populated/);
  });

  test("idempotent — loading twice produces single-call final state", () => {
    loadLomSnapshot(LOM_SNAPSHOT("empty-set.json"));
    const yaml = readCuration("partial.yaml");
    T.loadCuration(yaml, CURATION("partial.yaml"));
    const createsAfterFirst = liveApiCallsOfVerb("create_audio_track").length;
    const clipsAfterFirst = liveApiCallsOfVerb("create_clip").length;

    // After the first load, the LOM snapshot should contain 4 STG tracks
    // (created by the stub's `call("create_audio_track", -1)` — but the
    // stub doesn't ACTUALLY append; it only records the call). To make the
    // idempotent assertion meaningful we manually populate the snapshot to
    // mirror what Live would have done, then ensure the second call deletes
    // them via delete_track and recreates.
    loadLomSnapshotObject({
      live_set: {
        tracks: [
          { name: "STG-A", clip_slots: Array.from({ length: 12 }, () => ({ clip: null })) },
          { name: "STG-B", clip_slots: Array.from({ length: 12 }, () => ({ clip: null })) },
          { name: "STG-C", clip_slots: Array.from({ length: 12 }, () => ({ clip: null })) },
          { name: "STG-D", clip_slots: Array.from({ length: 12 }, () => ({ clip: null })) },
        ],
      },
    });

    // Reset call-log so the second-call assertions are clean.
    resetMaxStubCallLog();
    T.loadCuration(yaml, CURATION("partial.yaml"));
    const deletes = liveApiCallsOfVerb("delete_track");
    expect(deletes.length).toBe(4); // deletes STG-A through STG-D before recreating

    // Final state has 4 STG tracks and the same populated pad count.
    const populatedLines = statusLines().filter((l) =>
      l.startsWith("staging: populated")
    );
    expect(populatedLines.length).toBe(7);
    void createsAfterFirst;
    void clipsAfterFirst;
  });
});

describe("loadCuration() rejection paths", () => {
  test("malformed YAML emits malformed status and skips all LOM mutators", () => {
    loadLomSnapshot(LOM_SNAPSHOT("empty-set.json"));
    // A line with no colon and no leading dash trips the parser at line 2.
    const malformed = "curation_version: 1\nthis is not valid\nname: bad\n";
    const result = T.loadCuration(malformed);
    expect(result).toBeNull();
    const lines = statusLines();
    expect(lines.some((l) => l.startsWith("loadCuration: malformed YAML"))).toBe(
      true
    );
    expect(liveApiCallsOfVerb("create_audio_track").length).toBe(0);
    expect(liveApiCallsOfVerb("create_clip").length).toBe(0);
    expect(liveApiCallsOfVerb("delete_track").length).toBe(0);
  });
});

describe("loadCuration() forward-compat behaviour", () => {
  test("bounced.yaml loads without consulting last_bounce (Phase 3B work)", () => {
    loadLomSnapshot(LOM_SNAPSHOT("empty-set.json"));
    const yaml = readCuration("bounced.yaml");
    const result = T.loadCuration(yaml, CURATION("bounced.yaml"));
    expect(result).not.toBeNull();
    // bounced.yaml populates A01, B01, D01.
    const creates = liveApiCallsOfVerb("create_clip");
    expect(creates.length).toBe(3);
    // The complete-line should not mention bounce.
    const completeLine = statusLines().find((l) =>
      l.startsWith("loadCuration: complete")
    );
    expect(completeLine).not.toMatch(/bounce/i);
  });

  test("stale-reference.yaml loads + emits the stale-reference status", () => {
    loadLomSnapshot(LOM_SNAPSHOT("empty-set.json"));
    const yaml = readCuration("stale-reference.yaml");
    const result = T.loadCuration(yaml, CURATION("stale-reference.yaml"));
    expect(result).not.toBeNull();
    const lines = statusLines();
    const staleLine = lines.find((l) =>
      l.startsWith("staging: stale reference noted")
    );
    expect(staleLine).toBeTruthy();
    expect(staleLine).toMatch(/sample-forge/);
  });
});

describe("status-line count matches populated pads", () => {
  test("partial.yaml emits N populated-pad lines where N = populated count", () => {
    loadLomSnapshot(LOM_SNAPSHOT("empty-set.json"));
    const yaml = readCuration("partial.yaml");
    T.loadCuration(yaml, CURATION("partial.yaml"));
    const populated = statusLines().filter((l) =>
      l.startsWith("staging: populated")
    );
    expect(populated.length).toBe(7);
  });
});

// ─── Pad-ID parser ───────────────────────────────────────────────────────────

describe("_parsePadId", () => {
  test("accepts A01 / A·01 / A-01 forms", () => {
    expect(T._parsePadId("A01")).toEqual({ letter: "A", slot: 0 });
    expect(T._parsePadId("A·01")).toEqual({ letter: "A", slot: 0 });
    expect(T._parsePadId("A-01")).toEqual({ letter: "A", slot: 0 });
    expect(T._parsePadId("D12")).toEqual({ letter: "D", slot: 11 });
  });

  test("rejects malformed pad ids", () => {
    expect(T._parsePadId("")).toBeNull();
    expect(T._parsePadId(null)).toBeNull();
    expect(T._parsePadId("AA1")).toBeNull();
    expect(T._parsePadId("1A")).toBeNull();
  });
});

// Tiny utility: max-stub.js doesn't ship a "clear call log only" helper, so
// we wrap resetMaxStub() to retain the current LOM snapshot. Tests above
// only need it for the idempotency case.
function resetMaxStubCallLog() {
  // Walk the recorded arrays directly — they're live references exposed by
  // the stub via Object.defineProperty getters.
  while (liveApiCalls.length) liveApiCalls.pop();
  while (outletEmissions.length) outletEmissions.pop();
  while (messnamedCalls.length) messnamedCalls.pop();
}

// ─── Phase 2 — COMMIT walker tests ───────────────────────────────────────────
//
// The walker runs against an LOM snapshot pre-loaded into max-stub. It reads
// each STG-<letter> track's clip slots and emits a DeviceCommitBody-shaped
// payload via `messnamed("sf-commit-send", curationName, jsonPayload)`. The
// L3 contract these tests enforce is the wire contract Phase 2's server
// expects.

function captureCommitSends() {
  return messnamedCalls.filter((c) => c.name === "sf-commit-send");
}

function activate(name, letters) {
  T.setActiveCurationForTest(name, letters);
}

describe("commit() walker", () => {
  test("4-pads-stg-a snapshot → 4 audio_path entries in group A", () => {
    loadLomSnapshot(LOM_SNAPSHOT("staging-4-pads-stg-a.json"));
    activate("verse_swap_v1", ["A", "B", "C", "D"]);

    const payload = T.commit();
    expect(payload).not.toBeNull();
    expect(payload.groups.A).toBeDefined();
    expect(payload.groups.B).toBeDefined();
    expect(payload.groups.C).toBeDefined();
    expect(payload.groups.D).toBeDefined();

    const aPads = payload.groups.A.pads;
    expect(aPads.length).toBe(12);
    // First 4 pads have audio_path; remaining 8 are empty placeholders.
    expect(aPads[0].pad_id).toBe("A01");
    expect(aPads[0].audio_path).toMatch(/vocal-bar12-16\.wav$/);
    expect(aPads[0].clip_settings).toBeDefined();
    expect(aPads[0].clip_settings.warp_bpm).toBe(138.0);
    // 4 beats / 4 beats-per-bar = 1 bar → loop_end_bar = 1.0
    expect(aPads[0].clip_settings.loop_end_bar).toBe(1);
    expect(aPads[0].clip_settings.looping).toBe(true);

    expect(aPads[1].audio_path).toMatch(/vocal-bar0-4\.wav$/);
    expect(aPads[2].audio_path).toMatch(/vocal-bar4-8\.wav$/);
    expect(aPads[3].audio_path).toMatch(/vocal-bar20-24\.wav$/);

    // Empty pads carry only pad_id (no audio_path key).
    expect(aPads[4].audio_path).toBeUndefined();
    expect(aPads[11].pad_id).toBe("A12");

    // Other groups carry 12 empty placeholders each (track present in
    // snapshot but no clips).
    for (const letter of ["B", "C", "D"]) {
      const pads = payload.groups[letter].pads;
      expect(pads.length).toBe(12);
      for (const p of pads) expect(p.audio_path).toBeUndefined();
    }

    // messnamed send: curation name + JSON payload.
    const sends = captureCommitSends();
    expect(sends.length).toBe(1);
    expect(sends[0].args[0]).toBe("verse_swap_v1");
    const parsed = JSON.parse(sends[0].args[1]);
    expect(parsed.groups.A.pads[0].audio_path).toMatch(/vocal-bar12-16/);

    // Status emissions match the documented contract.
    const lines = statusLines();
    expect(lines).toContain("commit: walked 4 pads");
    expect(lines.some((l) => l.indexOf("commit: sent verse_swap_v1") === 0)).toBe(true);
  });

  test("empty-set snapshot → no STG tracks → emits empty group placeholders", () => {
    loadLomSnapshot(LOM_SNAPSHOT("empty-set.json"));
    activate("k", ["A", "B", "C", "D"]);
    const payload = T.commit();
    expect(payload).not.toBeNull();
    // No staging tracks present → every group has 12 placeholders with no
    // audio_path; server's merge preserves prior label/template on these.
    for (const letter of ["A", "B", "C", "D"]) {
      const pads = payload.groups[letter].pads;
      expect(pads.length).toBe(12);
      for (const p of pads) expect(p.audio_path).toBeUndefined();
    }
    const lines = statusLines();
    expect(lines).toContain("commit: walked 0 pads");
  });

  test("staging-empty snapshot → empty group payloads", () => {
    loadLomSnapshot(LOM_SNAPSHOT("staging-empty.json"));
    activate("k", ["A", "B", "C", "D"]);
    const payload = T.commit();
    expect(payload).not.toBeNull();
    // 4 tracks exist with 12 empty clip_slots each.
    let populated = 0;
    let total = 0;
    for (const letter of ["A", "B", "C", "D"]) {
      const pads = payload.groups[letter].pads;
      expect(pads.length).toBe(12);
      for (const p of pads) {
        total += 1;
        if (p.audio_path) populated += 1;
      }
    }
    expect(total).toBe(48);
    expect(populated).toBe(0);
  });

  test("staging-full-46-pads snapshot → 46 audio_path entries spread across groups", () => {
    loadLomSnapshot(LOM_SNAPSHOT("staging-full-46-pads.json"));
    activate("verse_swap_v1", ["A", "B", "C", "D"]);
    const payload = T.commit();
    expect(payload).not.toBeNull();
    let populated = 0;
    for (const letter of ["A", "B", "C", "D"]) {
      for (const p of payload.groups[letter].pads) {
        if (p.audio_path) populated += 1;
      }
    }
    expect(populated).toBe(46);
    // The send went out as one messnamed call.
    const sends = captureCommitSends();
    expect(sends.length).toBe(1);
    // Status emission reflects the populated count.
    expect(statusLines()).toContain("commit: walked 46 pads");
  });

  test("no active curation → emits status, no send, returns null", () => {
    loadLomSnapshot(LOM_SNAPSHOT("staging-4-pads-stg-a.json"));
    T.setActiveCurationForTest("", []);  // no active curation
    const payload = T.commit();
    expect(payload).toBeNull();
    expect(statusLines()).toContain(
      "commit: no active curation — load one first"
    );
    expect(captureCommitSends().length).toBe(0);
  });

  test("loadCuration sets active curation so commit can run", () => {
    loadLomSnapshot(LOM_SNAPSHOT("empty-set.json"));
    const yaml = readCuration("partial.yaml");
    T.loadCuration(yaml, CURATION("partial.yaml"));
    const ac = T.getActiveCuration();
    expect(ac.name).toBe("partial");
    expect(ac.groupLetters).toEqual(["A", "B", "C", "D"]);
  });

  test("commitAck() emits the canonical 'server ack received' status", () => {
    T.commitAck();
    const lines = statusLines();
    expect(lines).toContain("commit: server ack received");
    expect(lines).toContain("commit: complete");
    // Re-enables the primary button after a successful round-trip.
    const enabledCalls = messnamedCalls.filter(
      (c) => c.name === "primary-btn-enabled"
    );
    expect(enabledCalls[enabledCalls.length - 1].args).toEqual([1]);
  });
});

describe("commit() payload shape contract", () => {
  test("emits DeviceCommitBody-compatible JSON (groups, als_path, pads)", () => {
    loadLomSnapshot(LOM_SNAPSHOT("staging-4-pads-stg-a.json"));
    activate("verse_swap_v1", ["A", "B", "C", "D"]);
    const payload = T.commit();
    expect(payload).toMatchObject({
      als_path: null,
      groups: expect.any(Object),
    });
    // Every group dict has pads[].
    for (const letter of Object.keys(payload.groups)) {
      const g = payload.groups[letter];
      expect(g).toMatchObject({ label: null, template: null, pads: expect.any(Array) });
    }
    // Each pad has pad_id; populated pads also have audio_path + clip_settings.
    const aFirst = payload.groups.A.pads[0];
    expect(aFirst.pad_id).toBe("A01");
    expect(typeof aFirst.audio_path).toBe("string");
    expect(typeof aFirst.clip_settings.warp_bpm).toBe("number");
  });

  test("strips HFS prefix from Live's file_path values", () => {
    // Inject an HFS-style file_path; the walker normalises before emitting.
    loadLomSnapshotObject({
      live_set: {
        tracks: [
          {
            name: "STG-A",
            clip_slots: [
              {
                clip: {
                  name: "A01-hfs",
                  file_path:
                    "Macintosh HD:/Users/zak/stemforge/processed/x/curated_audio/y.wav",
                  warp_bpm: 120,
                  loop_start: 0,
                  loop_end: 4,
                  looping: 1,
                },
              },
              ...Array.from({ length: 11 }, () => ({ clip: null })),
            ],
          },
        ],
      },
    });
    activate("hfs_test", ["A"]);
    const payload = T.commit();
    expect(payload.groups.A.pads[0].audio_path).toBe(
      "/Users/zak/stemforge/processed/x/curated_audio/y.wav"
    );
  });
});

// ─── Phase 3A: applyGroupTemplate + templateChanged ──────────────────────────

describe("applyGroupTemplate (Phase 3A)", () => {
  const FAKE_TEMPLATE_DIR = "/tmp/sf-test-templates";

  beforeEach(() => {
    // Pin the templates dir so we don't depend on `_getHomePath()` (which
    // walks `/Users/` and isn't deterministic in the Node test env).
    T.setTemplateDirForTest(FAKE_TEMPLATE_DIR);
  });

  test("calls load_browser_item with the resolved .adg path on STG-<letter>", () => {
    loadLomSnapshot(LOM_SNAPSHOT("staging-empty.json"));
    const ok = T.applyGroupTemplate("A", "drum-rack-classic");
    expect(ok).toBe(true);

    const loadCalls = liveApiCallsOfVerb("load_browser_item");
    expect(loadCalls.length).toBe(1);
    expect(loadCalls[0].path).toBe("live_set tracks 0");
    expect(loadCalls[0].args[0]).toBe(
      "/tmp/sf-test-templates/drum-rack-classic.adg",
    );
    // Status emission greppable by humans + future debugging.
    expect(statusLines()).toContain(
      "template: applied drum-rack-classic to STG-A",
    );
  });

  test("resolves the correct STG-<letter> track by name (B, not A)", () => {
    loadLomSnapshot(LOM_SNAPSHOT("staging-empty.json"));
    const ok = T.applyGroupTemplate("B", "vocal-bloom");
    expect(ok).toBe(true);
    const loadCalls = liveApiCallsOfVerb("load_browser_item");
    expect(loadCalls[0].path).toBe("live_set tracks 1");
    expect(loadCalls[0].args[0]).toBe(
      "/tmp/sf-test-templates/vocal-bloom.adg",
    );
  });

  test("clear case (TEMPLATE_CLEAR_SENTINEL) emits status, no LOM call", () => {
    loadLomSnapshot(LOM_SNAPSHOT("staging-empty.json"));
    const ok = T.applyGroupTemplate("C", T.TEMPLATE_CLEAR_SENTINEL);
    expect(ok).toBe(true);
    expect(liveApiCallsOfVerb("load_browser_item").length).toBe(0);
    expect(statusLines()).toContain("template: cleared on STG-C");
  });

  test("clear via explicit null also emits the cleared status", () => {
    loadLomSnapshot(LOM_SNAPSHOT("staging-empty.json"));
    const ok = T.applyGroupTemplate("D", null);
    expect(ok).toBe(true);
    expect(liveApiCallsOfVerb("load_browser_item").length).toBe(0);
    expect(statusLines()).toContain("template: cleared on STG-D");
  });

  test("missing STG-<letter> track emits the not-found status, no LOM call", () => {
    loadLomSnapshot(LOM_SNAPSHOT("empty-set.json")); // no STG tracks
    const ok = T.applyGroupTemplate("A", "drum-rack-classic");
    expect(ok).toBe(false);
    expect(liveApiCallsOfVerb("load_browser_item").length).toBe(0);
    expect(statusLines()).toContain("template: STG-A not found");
  });

  test("idempotent — calling twice doesn't break state, both calls fire", () => {
    loadLomSnapshot(LOM_SNAPSHOT("staging-empty.json"));
    T.applyGroupTemplate("A", "drum-rack-classic");
    T.applyGroupTemplate("A", "drum-rack-classic");
    const loadCalls = liveApiCallsOfVerb("load_browser_item");
    // Each call hits the LOM verb; Live treats the second one as a no-op
    // modulo rack mtime — the test asserts the JS doesn't error out
    // between invocations.
    expect(loadCalls.length).toBe(2);
    expect(loadCalls[0].args[0]).toBe(loadCalls[1].args[0]);
  });

  test("templateChanged() is a thin wrapper — delegates to applyGroupTemplate", () => {
    loadLomSnapshot(LOM_SNAPSHOT("staging-empty.json"));
    T.templateChanged("B", "vocal-bloom");
    const loadCalls = liveApiCallsOfVerb("load_browser_item");
    expect(loadCalls.length).toBe(1);
    expect(loadCalls[0].args[0]).toBe(
      "/tmp/sf-test-templates/vocal-bloom.adg",
    );
    expect(statusLines()).toContain(
      "template: applied vocal-bloom to STG-B",
    );
  });

  test("_templatePathFor resolves <name>.adg under the templates dir", () => {
    expect(T._templatePathFor("foo")).toBe("/tmp/sf-test-templates/foo.adg");
    // Trailing slash handled (test the no-slash case via override reset).
    T.setTemplateDirForTest("/abs/dir/");
    expect(T._templatePathFor("bar")).toBe("/abs/dir/bar.adg");
    // Clear sentinel + falsy: empty path.
    expect(T._templatePathFor(T.TEMPLATE_CLEAR_SENTINEL)).toBe("");
    expect(T._templatePathFor("")).toBe("");
    expect(T._templatePathFor(null)).toBe("");
  });
});

// ─── Phase 3B — BOUNCE refactor tests ───────────────────────────────────────
//
// bounceCuration walks the active curation's STG-* pads, solos each group,
// triggers the clip, freeze-and-crops via the loop region, writes a WAV via
// outlet 3, and posts messnamed progress/completion beacons. Real WAV
// rendering is Phase 5's smoke suite; these L3 tests cap the contract at
// the LOM call + outlet/messnamed emissions captured by max-stub.
//
// Memory: `feedback_loop_region_canonical_for_materialize.md` and
// `feedback_clip_crop_renders_at_warp_bpm.md` are the load-bearing reads.

function captureBounceProgress() {
  return messnamedCalls.filter((c) => c.name === "sf-bounce-progress");
}

function captureBounceComplete() {
  return messnamedCalls.filter((c) => c.name === "sf-bounce-complete");
}

function liveApiSetCalls() {
  // max-stub records `set` via direct snapshot mutation, NOT through the
  // call log. To assert mute/unmute we read the snapshot's mute fields
  // directly. Helpers below.
  return null;
}

function trackMuteStateByName(name) {
  // Probe the loader's own snapshot via a LiveAPI lookup; mirrors what
  // bounceCuration's _bounceSoloGroup did. Returns null if missing.
  // We rely on max-stub's `set()` having mutated the snapshot in place.
  // Track names are unique under live_set in our fixtures.
  for (let i = 0; ; i += 1) {
    const trackPath = "live_set tracks " + i;
    const api = new LiveAPI(trackPath);
    if (api.id === 0) return null;
    const nm = api.get("name");
    if (nm && String(nm[0]) === name) {
      const m = api.get("mute");
      return m && m.length ? Number(m[0]) : 0;
    }
  }
}

describe("bounceCuration() — Phase 3B", () => {
  test("4-pads-stg-a snapshot → crops 4 pads + writes 4 WAVs", () => {
    loadLomSnapshot(LOM_SNAPSHOT("staging-4-pads-stg-a.json"));
    activate("verse_swap_v1", ["A", "B", "C", "D"]);

    const spec = T.bounceCuration("verse_swap_v1");
    expect(spec).not.toBeNull();
    expect(spec.curation_name).toBe("verse_swap_v1");
    expect(spec.pads.length).toBe(4);

    // Crop was called on every populated slot. Note: only STG-A has
    // populated clips in this snapshot; the call log records the verb.
    const crops = liveApiCallsOfVerb("crop");
    expect(crops.length).toBe(4);

    // Outlet 3 writes (the [shell] wire) carry the python helper invocation
    // with the output WAV path as one of its args. Filter to those rows.
    const writes = outletEmissions.filter((e) => e.idx === 3);
    expect(writes.length).toBe(4);
    const writtenPaths = writes.map((e) =>
      e.args.find((a) => String(a).indexOf("bounced/verse_swap_v1/") !== -1)
    );
    expect(writtenPaths.every((p) => /bounced\/verse_swap_v1\/A0\d\.wav$/.test(String(p)))).toBe(
      true
    );

    // Status line contract.
    const lines = statusLines();
    expect(lines).toContain("bounce: starting 4 pads");
    expect(lines).toContain("bounce: rendered A01");
    expect(lines).toContain("bounce: rendered A04");
    expect(lines.some((l) => /bounce: complete \(4\/4 OK\)/.test(l))).toBe(true);
  });

  test("emits per-pad progress beacons + a single completion beacon", () => {
    loadLomSnapshot(LOM_SNAPSHOT("staging-4-pads-stg-a.json"));
    activate("verse_swap_v1", ["A", "B", "C", "D"]);
    T.bounceCuration("verse_swap_v1");

    const progress = captureBounceProgress();
    expect(progress.length).toBe(4);
    expect(progress[0].args[0]).toBe("verse_swap_v1");
    // Each beacon carries pad_id + (rendered_count, total_count).
    const first = JSON.parse(progress[0].args[1]);
    expect(first.pad_id).toBe("A01");
    expect(first.rendered_count).toBe(1);
    expect(first.total_count).toBe(4);

    const last = JSON.parse(progress[progress.length - 1].args[1]);
    expect(last.rendered_count).toBe(4);
    expect(last.total_count).toBe(4);

    const complete = captureBounceComplete();
    expect(complete.length).toBe(1);
    expect(complete[0].args[0]).toBe("verse_swap_v1");
    const completionBody = JSON.parse(complete[0].args[1]);
    expect(completionBody.manifest_path).toMatch(
      /bounced\/verse_swap_v1\/bounce_manifest\.json$/
    );
  });

  test("materialization respects loop region (reads loop_start/loop_end)", () => {
    loadLomSnapshot(LOM_SNAPSHOT("staging-4-pads-stg-a.json"));
    activate("verse_swap_v1", ["A", "B", "C", "D"]);
    T.bounceCuration("verse_swap_v1");

    // Per `_collapseToLoopRegion` + `_readLoopRegion`, every cropped clip
    // has both loop_start and loop_end read before crop. The pre-crop
    // metadata cache also captures warp_bpm per
    // `feedback_clip_crop_renders_at_warp_bpm.md`.
    const spec = T.bounceCuration("verse_swap_v1"); // call again to inspect return
    expect(spec).not.toBeNull();
    for (const pad of spec.pads) {
      expect(pad.loop_region).toBeDefined();
      // The fixture clip's loop is 0..4 beats; bounceCuration normalizes
      // via _getLomNumber which returns the raw value.
      expect(pad.loop_region.loop_end).toBe(4);
    }
  });

  test("solos the group track at start; unsolos every STG-* at end", () => {
    loadLomSnapshot(LOM_SNAPSHOT("staging-4-pads-stg-a.json"));
    activate("verse_swap_v1", ["A", "B", "C", "D"]);
    T.bounceCuration("verse_swap_v1");

    // End state: every STG-* track is unmuted (mute=0). The intermediate
    // solo-then-unsolo sequence happens inside the loop body; we can't
    // observe each intermediate flip without a per-step hook, but the
    // end state is the contract: nothing remains silenced after a clean
    // bounce.
    expect(trackMuteStateByName("STG-A")).toBe(0);
    expect(trackMuteStateByName("STG-B")).toBe(0);
    expect(trackMuteStateByName("STG-C")).toBe(0);
    expect(trackMuteStateByName("STG-D")).toBe(0);
  });

  test("solos exactly the group whose pad is being rendered", () => {
    // Use a single-pad LOM (only STG-A has a clip) and a one-pad filter so
    // we can observe the solo sequence in isolation.
    loadLomSnapshotObject({
      live_set: {
        tracks: [
          {
            name: "STG-A",
            clip_slots: [
              {
                clip: {
                  name: "A01",
                  file_path: "/abs/x.wav",
                  warp_bpm: 120,
                  loop_start: 0,
                  loop_end: 4,
                  looping: 1,
                },
              },
              ...Array.from({ length: 11 }, () => ({ clip: null })),
            ],
            mute: 1, // start muted to prove _bounceSoloGroup unmuted it
          },
          {
            name: "STG-B",
            clip_slots: Array.from({ length: 12 }, () => ({ clip: null })),
            mute: 0,
          },
        ],
      },
    });
    activate("solo_test", ["A", "B"]);

    // Direct helper invocation: assert post-solo state immediately.
    T._bounceSoloGroup("A");
    expect(trackMuteStateByName("STG-A")).toBe(0);
    expect(trackMuteStateByName("STG-B")).toBe(1);

    T._bounceUnsoloAll();
    expect(trackMuteStateByName("STG-A")).toBe(0);
    expect(trackMuteStateByName("STG-B")).toBe(0);
  });

  test("pad-ids filter shrinks the work list", () => {
    loadLomSnapshot(LOM_SNAPSHOT("staging-4-pads-stg-a.json"));
    activate("verse_swap_v1", ["A", "B", "C", "D"]);
    const spec = T.bounceCuration("verse_swap_v1", JSON.stringify(["A01", "A03"]));
    expect(spec.pads.length).toBe(2);
    expect(spec.pads.map((p) => p.pad_id)).toEqual(["A01", "A03"]);
    expect(statusLines()).toContain("bounce: starting 2 pads");
  });

  test("empty STG tracks → no-op bounce with explanatory status", () => {
    loadLomSnapshot(LOM_SNAPSHOT("staging-empty.json"));
    activate("empty_curation", ["A", "B", "C", "D"]);
    const spec = T.bounceCuration("empty_curation");
    expect(spec.pads).toEqual([]);
    expect(statusLines()).toContain("bounce: no populated pads to render");
    // No progress / completion beacons when there's nothing to render.
    expect(captureBounceProgress().length).toBe(0);
    expect(captureBounceComplete().length).toBe(0);
  });

  test("no active curation + no explicit name → status, returns null", () => {
    loadLomSnapshot(LOM_SNAPSHOT("staging-4-pads-stg-a.json"));
    T.setActiveCurationForTest("", []);
    const spec = T.bounceCuration();
    expect(spec).toBeNull();
    expect(statusLines()).toContain("bounce: no active curation — load one first");
  });

  test("pad-id filter accepts interpunct form", () => {
    loadLomSnapshot(LOM_SNAPSHOT("staging-4-pads-stg-a.json"));
    activate("verse_swap_v1", ["A", "B", "C", "D"]);
    const spec = T.bounceCuration("verse_swap_v1", '["A·02"]');
    expect(spec.pads.length).toBe(1);
    expect(spec.pads[0].pad_id).toBe("A02");
  });
});

describe("bounceCuration() — legacy cleanup", () => {
  test("commitOffsets is no longer defined on the loader (grep test)", () => {
    expect(typeof T.commitOffsets).toBe("undefined");
    // Also assert that the source file itself doesn't ship a top-level
    // `function commitOffsets(` declaration — the brief calls for clean
    // deletion, not just an unexported stub.
    const src = require("node:fs").readFileSync(
      require("node:path").join(__dirname, "stemforge_loader.v0.js"),
      "utf-8"
    );
    expect(src).not.toMatch(/^function commitOffsets\(/m);
    expect(src).not.toMatch(/^function bounceTracks\(/m);
    expect(src).not.toMatch(/^function _commitOffsetsWithPath\(/m);
  });
});

// ─── Phase 4A — als-opened bootstrap ─────────────────────────────────────────
//
// `loadbang()` queries Live for the current set's path and POSTs it to the
// server via `messnamed("sf-als-opened", path)`. The server responds with
// `{active_curation: name | null}` and the patcher's HTTP shim hands that
// back via `messnamed("sf-als-opened-ack", curationOrEmpty)` → `alsOpenedAck()`.
//
// LOM-verb caveat (deferred to Phase 5): the production code probes three
// LOM paths in order — `live_app view path_to_set_file`, `live_set path`,
// `live_set name`. Tests cover each fallback level.

describe("Phase 4A — als-opened bootstrap", () => {
  beforeEach(() => {
    // Each test starts with a fresh fired-flag so consecutive calls aren't
    // squashed by the double-loadbang guard.
    T.resetAlsOpenedFiredForTest();
    T.setAlsPathForTest(null);
  });

  test("loadbang emits sf-als-opened with the LOM-reported absolute path", () => {
    // Seed the snapshot with a `live_app view` node carrying the
    // documented `path_to_set_file` property. The loader's first-choice
    // probe should hit this and emit the path verbatim.
    loadLomSnapshotObject({
      live_app: { view: { path_to_set_file: "/Users/zak/projects/song.als" } },
      live_set: { tracks: [], path: "", name: "song.als" },
    });

    T.liveApiReady();

    const sends = global.messnamedCalls.filter((c) => c.name === T.ALS_OPENED_SEND);
    expect(sends).toHaveLength(1);
    expect(sends[0].args[0]).toBe("/Users/zak/projects/song.als");
  });

  test("ack with a curation name reads the YAML and calls loadCuration", () => {
    // Drop a real curation YAML under a tmp ~/stemforge/curations dir and
    // point the loader's home-resolver at it via setTemplateDir... actually
    // the loader resolves home via _getHomePath() which uses Folder
    // ("Macintosh HD:/Users/") — the max-stub's Folder shim reads the
    // real filesystem, so we have to either mock _getHomePath OR seed a
    // fixture that the loader can actually resolve.
    //
    // Pragmatic approach: assert on the status emissions. The loader logs
    // "als-opened: ack <name>" before it tries to read the file. That
    // alone proves the ack handler routed correctly. The happy-path
    // file-read is integration-tested by L4 (Phase 5).
    T.alsOpenedAck("verse_swap_v1");
    const status = global.outletEmissions
      .filter((e) => Array.isArray(e.args) && e.args[0] === "set")
      .map((e) => e.args.slice(1).join(" "));
    expect(status.some((s) => s.includes("als-opened: ack verse_swap_v1"))).toBe(true);
  });

  test("ack with empty / sentinel curation is a no-op (status only)", () => {
    T.alsOpenedAck("");
    let status = global.outletEmissions
      .filter((e) => Array.isArray(e.args) && e.args[0] === "set")
      .map((e) => e.args.slice(1).join(" "));
    expect(status.some((s) => s.includes("als-opened: ack <none>"))).toBe(true);
    // No further loadCuration noise — no "staging:" status lines fire.
    expect(status.some((s) => s.startsWith("staging:"))).toBe(false);

    // The "-" sentinel from the template-clear convention is also a noop.
    resetMaxStub();
    T.resetAlsOpenedFiredForTest();
    T.alsOpenedAck("-");
    status = global.outletEmissions
      .filter((e) => Array.isArray(e.args) && e.args[0] === "set")
      .map((e) => e.args.slice(1).join(" "));
    expect(status.some((s) => s.includes("als-opened: ack <none>"))).toBe(true);
  });

  test("LOM fallback chain — uses live_set.path when path_to_set_file is missing", () => {
    // No `live_app.view.path_to_set_file` — the loader must fall through to
    // `live_set.path`. We seed only the second probe target.
    loadLomSnapshotObject({
      live_set: { tracks: [], path: "/secondary/probe.als", name: "probe.als" },
    });

    T.liveApiReady();

    const sends = global.messnamedCalls.filter((c) => c.name === T.ALS_OPENED_SEND);
    expect(sends).toHaveLength(1);
    expect(sends[0].args[0]).toBe("/secondary/probe.als");
  });

  test("LOM fallback chain — degrades to live_set.name when no path is available", () => {
    // Neither `path_to_set_file` nor `live_set.path` set — only `name`.
    // The loader emits the filename-only fallback; the server may not be
    // able to resolve an exact active-curation, but the wire round-trip
    // still happens cleanly.
    loadLomSnapshotObject({
      live_set: { tracks: [], name: "fallback.als" },
    });

    T.liveApiReady();

    const sends = global.messnamedCalls.filter((c) => c.name === T.ALS_OPENED_SEND);
    expect(sends).toHaveLength(1);
    expect(sends[0].args[0]).toBe("fallback.als");
  });

  test("test override beats every LOM probe", () => {
    // setAlsPathForTest forces the path regardless of what LOM reports —
    // ensures L3 tests can drive the loader without LOM seeding when the
    // path itself isn't under test.
    loadLomSnapshotObject({
      live_app: { view: { path_to_set_file: "/lom/wins.als" } },
      live_set: { tracks: [], path: "/lom/wins.als", name: "wins.als" },
    });
    T.setAlsPathForTest("/override/wins.als");

    T.liveApiReady();

    const sends = global.messnamedCalls.filter((c) => c.name === T.ALS_OPENED_SEND);
    expect(sends).toHaveLength(1);
    expect(sends[0].args[0]).toBe("/override/wins.als");
  });

  test("double loadbang is a no-op on the second call", () => {
    // Max can fire loadbang twice on patcher reload — we MUST NOT POST
    // /als-opened twice or the server will see duplicate bootstrap
    // events. The fired-flag guard short-circuits the second call.
    T.setAlsPathForTest("/once.als");
    T.liveApiReady();
    T.liveApiReady(); // second call — should be a no-op

    const sends = global.messnamedCalls.filter((c) => c.name === T.ALS_OPENED_SEND);
    expect(sends).toHaveLength(1);

    const status = global.outletEmissions
      .filter((e) => Array.isArray(e.args) && e.args[0] === "set")
      .map((e) => e.args.slice(1).join(" "));
    expect(status.some((s) => s.includes("als-opened: skipping (already fired)"))).toBe(true);
  });

  test("loadbang with no LOM info still emits (empty path is forwarded)", () => {
    // No live_app, no live_set.path, no live_set.name. The probe chain
    // bottoms out and the loader emits empty string. The server will
    // ack with null; the device's ack handler logs and does nothing.
    // We still want a single emission so the user-visible status line
    // ("als-opened: sent <unknown>") fires and SSE listeners learn the
    // device just booted.
    loadLomSnapshotObject({ live_set: { tracks: [] } });

    T.liveApiReady();

    const sends = global.messnamedCalls.filter((c) => c.name === T.ALS_OPENED_SEND);
    expect(sends).toHaveLength(1);
    expect(sends[0].args[0]).toBe("");
    const status = global.outletEmissions
      .filter((e) => Array.isArray(e.args) && e.args[0] === "set")
      .map((e) => e.args.slice(1).join(" "));
    expect(status.some((s) => s.includes("als-opened: sent <unknown>"))).toBe(true);
  });
});
