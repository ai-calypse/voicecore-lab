import { defineConfig } from "vitest/config";

// Unit tests only; Playwright's e2e/*.spec.ts files are never picked up here.
export default defineConfig({ test: { include: ["e2e/**/*.test.ts", "src/**/*.test.ts"] } });
