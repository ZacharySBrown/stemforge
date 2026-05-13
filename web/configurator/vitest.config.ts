import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import path from "node:path";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  test: {
    // jsdom rather than happy-dom because msw v2 + happy-dom fetch has a
    // ReadableStream double-consume bug (2026-05-13). jsdom defers fetch
    // to node's native fetch, which msw can intercept cleanly.
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    css: false,
  },
});
