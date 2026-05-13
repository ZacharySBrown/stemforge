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
