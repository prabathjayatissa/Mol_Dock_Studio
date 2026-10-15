/// <reference types="vitest/config" />
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// The SPA talks to the local FastAPI service. In development Vite proxies /api
// to the backend so there is no CORS round-trip and no absolute host in the
// bundle; in production the same relative base is served by the packager or the
// backend's static mount. Change the target here if the backend runs elsewhere.
const DEV_API_TARGET = "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": { target: DEV_API_TARGET, changeOrigin: true },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: true,
    target: "es2022",
  },
  test: {
    // The unit tests cover pure logic (geometry, picking, packet decoding) and
    // deliberately need no DOM. Using the `node` environment avoids loading
    // jsdom in every worker, which keeps worker start-up fast (Vitest has a
    // hard 60 s worker-start timeout that a heavy environment can exceed on a
    // slow or network-backed filesystem).
    environment: "node",
    include: ["src/**/*.test.ts", "src/**/*.test.tsx"],
    globals: true,
    pool: "forks",
    maxWorkers: 1,
    // The unit tests share no mutable module state, so reusing one worker avoids
    // re-paying worker start-up (which is slow on network-backed filesystems).
    isolate: false,
  },
});
