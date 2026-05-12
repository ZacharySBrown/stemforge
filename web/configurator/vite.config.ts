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
      // Forward intent/state/preview/healthz to the local Python HTTP server
      // when running `npm run dev`. The Lane A server picks its own port at
      // startup; override via VITE_STEMFORGE_API or rely on relative URLs in
      // production (the server itself serves the built bundle at /).
      "^/(state|intent|preview|healthz)": {
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
