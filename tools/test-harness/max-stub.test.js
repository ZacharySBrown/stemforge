/**
 * Self-tests for tools/test-harness/max-stub.js.
 *
 * Proves every primitive the device JS depends on works end-to-end with the
 * fixture LOM snapshots in tests/fixtures/lom_snapshots/. If any of these
 * regress, every device-JS test built on top of the stub regresses too.
 */

const path = require("node:path");

// Vitest globals (describe, test, expect, beforeEach) are injected by the
// harness config (vitest.harness.config.ts has `globals: true`). Avoids a
// `require("vitest")` here because vitest lives in web/configurator/node_modules
// and the harness tests run with the repo root as their cwd.

// Load the stub once; it installs Max globals on `global.*`.
require("./max-stub.js");

const FIXTURE = (name) => path.resolve(__dirname, "../../tests/fixtures/lom_snapshots", name);

beforeEach(() => {
  resetMaxStub();
});

describe("Dict", () => {
  test("set and get round-trip", () => {
    const d = new Dict("test");
    d.set("foo", 42);
    expect(d.get("foo")).toBe(42);
  });

  test("named dicts share storage across instances", () => {
    const a = new Dict("shared");
    const b = new Dict("shared");
    a.set("x", "hello");
    expect(b.get("x")).toBe("hello");
  });

  test("replace overwrites contents from JSON", () => {
    const d = new Dict("config");
    d.set("old", true);
    d.replace(JSON.stringify({ new: 1, also: "yes" }));
    expect(d.get("old")).toBeUndefined();
    expect(d.get("new")).toBe(1);
    expect(d.get("also")).toBe("yes");
  });

  test("getkeys returns current keys", () => {
    const d = new Dict("keys");
    d.set("a", 1);
    d.set("b", 2);
    expect(d.getkeys().sort()).toEqual(["a", "b"]);
  });

  test("set with nested object is deep-cloned (no aliasing)", () => {
    const d = new Dict("nested");
    const src = { nested: { value: 1 } };
    d.set("k", src);
    src.nested.value = 999;
    expect(d.get("k")).toEqual({ nested: { value: 1 } });
  });
});

describe("LiveAPI", () => {
  test("empty-set snapshot has zero tracks", () => {
    loadLomSnapshot(FIXTURE("empty-set.json"));
    const api = new LiveAPI("live_set");
    expect(api.getcount("tracks")).toBe(0);
  });

  test("forge-loaded snapshot exposes track names via path walk", () => {
    loadLomSnapshot(FIXTURE("forge-loaded.json"));
    const api = new LiveAPI("live_set");
    expect(api.getcount("tracks")).toBe(4);
    const track0 = new LiveAPI("live_set tracks 0");
    expect(track0.get("name")).toEqual(["FORGE/my-track/drum"]);
  });

  test("staging-4-pads-stg-a populates STG-A's clip slots", () => {
    loadLomSnapshot(FIXTURE("staging-4-pads-stg-a.json"));
    const stgA = new LiveAPI("live_set tracks 0");
    expect(stgA.get("name")).toEqual(["STG-A"]);
    expect(stgA.getcount("clip_slots")).toBe(12);
    const slot0 = new LiveAPI("live_set tracks 0 clip_slots 0 clip");
    expect(slot0.get("name")).toEqual(["A01-vocal-bar12-16"]);
    expect(slot0.get("warp_bpm")).toEqual([138.0]);
  });

  test("set() mutates the seeded snapshot", () => {
    loadLomSnapshot(FIXTURE("forge-loaded.json"));
    const t = new LiveAPI("live_set tracks 0");
    t.set("name", "RENAMED");
    expect(t.get("name")).toEqual(["RENAMED"]);
  });

  test("call() records invocation for assertion", () => {
    const api = new LiveAPI("live_set");
    api.call("create_audio_track", -1);
    expect(liveApiCalls).toEqual([
      { path: "live_set", verb: "create_audio_track", args: [-1] },
    ]);
  });

  test("goto() repositions to a different path", () => {
    loadLomSnapshot(FIXTURE("forge-loaded.json"));
    const api = new LiveAPI("live_set tracks 0");
    expect(api.get("name")).toEqual(["FORGE/my-track/drum"]);
    api.goto("live_set tracks 1");
    expect(api.get("name")).toEqual(["FORGE/my-track/bass"]);
  });

  test("getcount on missing collection returns 0", () => {
    loadLomSnapshot(FIXTURE("empty-set.json"));
    const api = new LiveAPI("live_set tracks 99");
    expect(api.getcount("clip_slots")).toBe(0);
  });

  test("id is 0 for non-existent paths", () => {
    loadLomSnapshot(FIXTURE("empty-set.json"));
    const ghost = new LiveAPI("live_set tracks 42 clip_slots 0 clip");
    expect(ghost.id).toBe(0);
  });

  test("id is non-zero for existing paths", () => {
    loadLomSnapshot(FIXTURE("forge-loaded.json"));
    const real = new LiveAPI("live_set tracks 0");
    expect(real.id).not.toBe(0);
  });
});

describe("outlet / messnamed / post", () => {
  test("outlet records emission with idx and args", () => {
    outlet(0, "hello", 42);
    outlet(1, { kind: "complex" });
    expect(outletEmissions).toEqual([
      { idx: 0, args: ["hello", 42] },
      { idx: 1, args: [{ kind: "complex" }] },
    ]);
  });

  test("messnamed records by name", () => {
    messnamed("max", "launchbrowser", "http://127.0.0.1:7430");
    expect(messnamedCalls).toEqual([
      { name: "max", args: ["launchbrowser", "http://127.0.0.1:7430"] },
    ]);
  });

  test("post captures string-formatted output", () => {
    post("hello", "world", 42);
    expect(postLog).toContain("hello world 42");
  });

  test("arrayfromargs returns a plain array", () => {
    const result = arrayfromargs([1, 2, 3]);
    expect(Array.isArray(result)).toBe(true);
    expect(result).toEqual([1, 2, 3]);
  });
});

describe("resetMaxStub", () => {
  test("clears all recorded emissions", () => {
    outlet(0, "x");
    messnamed("max", "y");
    post("z");
    resetMaxStub();
    expect(outletEmissions).toEqual([]);
    expect(messnamedCalls).toEqual([]);
    expect(postLog).toEqual([]);
  });

  test("clears the LOM tree", () => {
    loadLomSnapshot(FIXTURE("forge-loaded.json"));
    resetMaxStub();
    const api = new LiveAPI("live_set");
    expect(api.getcount("tracks")).toBe(0);
  });

  test("clears named Dict registry", () => {
    const d1 = new Dict("survives?");
    d1.set("ghost", "value");
    resetMaxStub();
    const d2 = new Dict("survives?");
    expect(d2.get("ghost")).toBeUndefined();
  });
});

describe("LiveAPI verb mutators (Phase 1C extension)", () => {
  test("create_audio_track appends a track with 12 empty clip slots", () => {
    loadLomSnapshot(FIXTURE("empty-set.json"));
    const api = new LiveAPI("live_set");
    expect(api.getcount("tracks")).toBe(0);
    api.call("create_audio_track", -1);
    expect(api.getcount("tracks")).toBe(1);
    const track = new LiveAPI("live_set tracks 0");
    expect(track.getcount("clip_slots")).toBe(12);
  });

  test("delete_track removes a track at the given index", () => {
    loadLomSnapshotObject({
      live_set: {
        tracks: [
          { name: "X", clip_slots: [] },
          { name: "Y", clip_slots: [] },
          { name: "Z", clip_slots: [] },
        ],
      },
    });
    const api = new LiveAPI("live_set");
    api.call("delete_track", 1);
    expect(api.getcount("tracks")).toBe(2);
    expect(new LiveAPI("live_set tracks 0").get("name")).toEqual(["X"]);
    expect(new LiveAPI("live_set tracks 1").get("name")).toEqual(["Z"]);
  });

  test("create_clip on a slot path installs a clip object", () => {
    loadLomSnapshotObject({
      live_set: {
        tracks: [
          { name: "T", clip_slots: [{ clip: null }, { clip: null }] },
        ],
      },
    });
    const slot = new LiveAPI("live_set tracks 0 clip_slots 0");
    slot.call("create_clip", 8);
    const clip = new LiveAPI("live_set tracks 0 clip_slots 0 clip");
    expect(clip.id).not.toBe(0);
    expect(clip.get("loop_end")).toEqual([8]);
  });
});

describe("File shim (Phase 1C extension)", () => {
  test("opens a real file when given an HFS-prefixed path", () => {
    const tmp = require("node:os").tmpdir();
    const filepath = path.join(tmp, `max-stub-file-${Date.now()}.txt`);
    require("node:fs").writeFileSync(filepath, "hello from disk");
    try {
      const f = new global.File("Macintosh HD:" + filepath);
      expect(f.isopen).toBe(true);
      expect(f.read()).toBe("hello from disk");
    } finally {
      require("node:fs").unlinkSync(filepath);
    }
  });

  test("readstring advances position chunkwise", () => {
    const tmp = require("node:os").tmpdir();
    const filepath = path.join(tmp, `max-stub-chunks-${Date.now()}.txt`);
    require("node:fs").writeFileSync(filepath, "abcdefghij");
    try {
      const f = new global.File(filepath);
      expect(f.readstring(3)).toBe("abc");
      expect(f.readstring(3)).toBe("def");
      expect(f.readstring(100)).toBe("ghij");
      expect(f.readstring(1)).toBe("");
    } finally {
      require("node:fs").unlinkSync(filepath);
    }
  });
});

describe("arrayfromargs (Max-magic flattener)", () => {
  test("flattens messagename + arguments-object into a single array", () => {
    function fakeHandler() {
      return arrayfromargs("loadCuration", arguments);
    }
    expect(fakeHandler("path/to/file.yaml", 42)).toEqual([
      "loadCuration",
      "path/to/file.yaml",
      42,
    ]);
  });

  test("treats strings as scalar tokens (does not spread chars)", () => {
    expect(arrayfromargs("hello")).toEqual(["hello"]);
  });
});

describe("acceptance gate (spec §7.5)", () => {
  test("empty-set.json → new LiveAPI('live_set').getcount('tracks') === 0", () => {
    loadLomSnapshot(FIXTURE("empty-set.json"));
    const api = new LiveAPI("live_set");
    expect(api.getcount("tracks")).toBe(0);
  });
});
