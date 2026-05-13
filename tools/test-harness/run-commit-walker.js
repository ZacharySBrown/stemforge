#!/usr/bin/env node
/**
 * run-commit-walker.js — drives the device-JS commit() walker against
 * an LOM snapshot, captures the resulting sf-commit-send payload, and
 * prints it as JSON to stdout.
 *
 * Used by tests/test_commit_keystone.py to bridge the device-side
 * walker and the server-side write path in a single deterministic
 * test (no Live, no Max, no UDP). The pytest side reads this script's
 * stdout, parses the JSON, and POSTs it to the FastAPI TestClient.
 *
 * Usage:
 *   node tools/test-harness/run-commit-walker.js \
 *        <lom-snapshot.json> <curation-name> [letterA,letterB,...]
 *
 * stdout:
 *   {
 *     "curation_name": "<name>",
 *     "payload": <DeviceCommitBody>,
 *     "status_lines": ["commit: walked N pads", ...]
 *   }
 *
 * stderr is reserved for debug noise (`require()` warnings etc).
 * Non-zero exit code signals walker rejection (e.g. unparseable
 * snapshot, missing active curation).
 */

"use strict";

const path = require("node:path");
const fs = require("node:fs");

const REPO_ROOT = path.resolve(__dirname, "../..");

require(path.join(REPO_ROOT, "tools/test-harness/max-stub.js"));
const loader = require(path.join(REPO_ROOT, "v0/src/m4l-js/stemforge_loader.v0.js"));
const T = loader.__test__;

function main() {
  const [snapshotPath, curationName, lettersArg] = process.argv.slice(2);
  if (!snapshotPath || !curationName) {
    process.stderr.write(
      "usage: run-commit-walker.js <lom-snapshot.json> <curation-name> [letters]\n"
    );
    process.exit(2);
  }
  const letters = (lettersArg || "A,B,C,D")
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);

  // Seed max-stub state.
  // eslint-disable-next-line no-undef
  resetMaxStub();
  // eslint-disable-next-line no-undef
  loadLomSnapshot(snapshotPath);

  // Activate the curation so commit() walks the right letters.
  T.setActiveCurationForTest(curationName, letters);

  // Drive the walker. Throws are surfaced as exit-1.
  let payload;
  try {
    payload = T.commit();
  } catch (e) {
    process.stderr.write("commit() threw: " + (e && e.message ? e.message : String(e)) + "\n");
    process.exit(1);
  }
  if (payload == null) {
    process.stderr.write("commit() returned null (no active curation?)\n");
    process.exit(1);
  }

  // Recover the messnamed send the walker emitted.
  // eslint-disable-next-line no-undef
  const sends = messnamedCalls.filter((c) => c.name === "sf-commit-send");
  if (sends.length !== 1) {
    process.stderr.write(
      "expected exactly one sf-commit-send call; got " + sends.length + "\n"
    );
    process.exit(1);
  }
  const sentCurationName = sends[0].args[0];
  let sentPayload;
  try {
    sentPayload = JSON.parse(sends[0].args[1]);
  } catch (e) {
    process.stderr.write("payload was not valid JSON: " + e.message + "\n");
    process.exit(1);
  }

  // Recover status lines for L3 status-assertion access.
  // eslint-disable-next-line no-undef
  const statusLines = outletEmissions
    .filter((e) => e.idx === 0 && e.args[0] === "set")
    .map((e) => String(e.args[1]));

  const out = {
    curation_name: sentCurationName,
    payload: sentPayload,
    status_lines: statusLines,
  };
  process.stdout.write(JSON.stringify(out));
}

main();

// Silence the unused-fs-import lint in editors that don't see the conditional
// shape of the require.
void fs;
