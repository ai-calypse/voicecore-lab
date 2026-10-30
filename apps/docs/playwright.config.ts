import { defineConfig } from "@playwright/test";

// The built docs site (run `pnpm build` first; `pnpm e2e` does both).
export default defineConfig({
  testDir: "e2e",
  timeout: 30_000,
  use: { baseURL: "http://127.0.0.1:13000" },
  projects: [{ name: "chromium", use: { browserName: "chromium" } }],
  webServer: { command: "pnpm exec docusaurus serve --host 127.0.0.1 --port 13000 --no-open", url: "http://127.0.0.1:13000", reuseExistingServer: false },
});
