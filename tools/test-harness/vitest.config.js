/**
 * Vitest config for the device-JS test harness.
 *
 * Runs from the repo root via:
 *   npx --prefix web/configurator vitest run -c tools/test-harness/vitest.config.js
 *
 * (Reuses the web/configurator node_modules so we don't double-install
 * vitest. The harness has no React deps so the bare environment works.)
 */

import { defineConfig } from "vitest/config";
import path from "node:path";

export default defineConfig({
  test: {
    environment: "node",
    globals: false,
    include: [
      // Self-tests for the stub itself.
      "tools/test-harness/**/*.test.js",
      // Future: device-JS tests under v0/src/m4l-js/.
      "v0/src/m4l-js/**/*.test.js",
    ],
    root: path.resolve(__dirname, "../.."),
  },
});
