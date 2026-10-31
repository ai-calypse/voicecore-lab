import { defineConfig } from "vitest/config";

// Unit tests only; Playwright's e2e/*.spec.ts files are never picked up here.
export default defineConfig({ test: { include: ["src/**/*.test.ts"] } });
