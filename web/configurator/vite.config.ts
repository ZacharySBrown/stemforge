import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    port: 5173,
    strictPort: false,
    proxy: {
      // Forward server endpoints to the local Python HTTP server when running
      // `npm run dev`. The Lane A server picks its own port at startup;
      // override via VITE_STEMFORGE_API or rely on relative URLs in production
      // (the server itself serves the built bundle at /).
      //
      // Keep this regex in lock-step with the endpoint catalog in
      // `web/configurator/src/lib/api.ts`. The pre-UAT review (P0-6) caught
      // /curations, /forges, /templates, and /als-opened being unproxied.
      "^/(state|intent|preview|healthz|curations|forges|templates|als-opened)": {
        target: process.env.VITE_STEMFORGE_API || "http://127.0.0.1:8765",
        changeOrigin: true,
        secure: false,
        ws: true,
      },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: true,
    target: "es2022",
  },
});
