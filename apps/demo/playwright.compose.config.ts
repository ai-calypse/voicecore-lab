import { defineConfig, devices } from "@playwright/test";

// Specs that need the compose stack's nginx images (security headers). No web servers: the stack is already up.
export default defineConfig({
  testDir: "./e2e",
  testMatch: "**/*.compose.ts",
  timeout: 60_000,
  use: { ...devices["Desktop Chrome"] },
});
