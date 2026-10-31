import { defineConfig } from "vite";

// The console UI. In development the API comes from a console on :8000; the build is served by the console itself.
// VITE_DEMO=1 builds the read-only demo (snapshots from demo/) under /console/ on the docs site.
export default defineConfig({
  base: process.env.VITE_DEMO === "1" ? "/console/" : "/",
  server: { proxy: { "/api": "http://127.0.0.1:8000", "/preview": "http://127.0.0.1:8000" } },
  build: { outDir: process.env.VITE_DEMO === "1" ? "dist-demo" : "dist" },
});
