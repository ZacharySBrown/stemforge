/**
 * Vitest config for the device-JS test harness (tools/test-harness/ + v0/src/m4l-js/).
 *
 * Lives under web/configurator/ so it can resolve `vitest/config` from the
 * existing node_modules. Test scope and root are intentionally outside this
 * directory (the harness tests are CommonJS Node code, not React).
 *
 * Run from repo root via:
 *   npx --prefix web/configurator vitest run --config web/configurator/vitest.harness.config.ts
 */

import { defineConfig } from "vitest/config";
import path from "node:path";

const repoRoot = path.resolve(__dirname, "../..");

export default defineConfig({
  test: {
    environment: "node",
    globals: true,
    include: [
      "tools/test-harness/**/*.test.js",
      "v0/src/m4l-js/**/*.test.js",
    ],
    root: repoRoot,
  },
});
