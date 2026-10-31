import { defineConfig } from "@playwright/test";
import { fileURLToPath } from "node:url";

// The console end to end (Step 10, seam 23): the built UI on the real console, a free orchestrator and a gateway,
// all reading one agents folder. Ports 18010 / 18082 / 18767: never the dev ports. Nothing is reused.
const root = fileURLToPath(new URL("../..", import.meta.url));
const gateway = fileURLToPath(new URL("../../services/realtime-gateway", import.meta.url));
const data = fileURLToPath(new URL("./.e2e-data", import.meta.url));

export default defineConfig({
  testDir: "e2e",
  testMatch: "**/*.spec.ts",
  globalSetup: "./e2e/global-setup.ts",
  timeout: 120_000,
  use: { baseURL: "http://127.0.0.1:18010" },
  projects: [{ name: "chromium", use: { browserName: "chromium" } }],
  webServer: [
    {
      command: `rm -rf ${data} && mkdir -p ${data}/agents && uv run python -m voicecore_console serve --host 127.0.0.1 --port 18010 --data-dir ${data}/console --agents-dir ${data}/agents`,
      cwd: root, url: "http://127.0.0.1:18010/api/status", reuseExistingServer: false, timeout: 120_000,
      env: { CONSOLE_SETUP_TOKEN: "e2e-setup", VOICECORE_PROVIDERS: "free", PUBLIC_VOICE_URL: "http://127.0.0.1:18082", CONSOLE_STATIC: `${root}apps/console/dist`, VOICECORE_VECTORS_DIR: `${data}/vectors` },
    },
    { command: `uv run python -m voicecore.server --providers free --port 18767 --agents-dir ${data}/agents --default-agent off`, cwd: root, url: "http://127.0.0.1:18767/readyz", reuseExistingServer: false, timeout: 600_000 },
    { command: `go run ./cmd/gateway -addr 127.0.0.1:18082 -upstream ws://127.0.0.1:18767 -agents-dir ${data}/agents -widget ${root}apps/demo/public/embed/voicecore.js`, cwd: gateway, url: "http://127.0.0.1:18082/healthz", reuseExistingServer: false },
  ],
});
