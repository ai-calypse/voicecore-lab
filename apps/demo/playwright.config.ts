import { defineConfig } from "@playwright/test";
import { fileURLToPath } from "node:url";

// Ports 15173 / 1876x / 1808x / 18090 on purpose: never the dev ports (5173, 8765, 8080), where a live
// orchestrator may be running. Servers are never reused: a busy port fails the run instead of being trusted.
const root = fileURLToPath(new URL("../..", import.meta.url));
const experiments = fileURLToPath(new URL("../../experiments", import.meta.url));
const gateway = fileURLToPath(new URL("../../services/realtime-gateway", import.meta.url));
const fixture = fileURLToPath(new URL("../../fixtures/audio/dev/single_01.wav", import.meta.url));

export default defineConfig({
  testDir: "e2e",
  testMatch: "**/*.spec.ts", // *.test.ts files there are vitest unit tests
  timeout: 30_000,
  use: {
    baseURL: "http://127.0.0.1:15173",
    permissions: ["microphone"],
    launchOptions: {
      args: ["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream", `--use-file-for-fake-audio-capture=${fixture}%noloop`, "--autoplay-policy=no-user-gesture-required"],
    },
  },
  projects: [{ name: "chromium", use: { browserName: "chromium" } }],
  webServer: [
    { command: "pnpm exec vite --host 127.0.0.1 --port 15173 --strictPort", url: "http://127.0.0.1:15173", env: { VITE_GATEWAY: "http://127.0.0.1:18081" }, reuseExistingServer: false },
    { command: "go run ./cmd/fakeorch -addr 127.0.0.1:18765", cwd: gateway, port: 18765, reuseExistingServer: false },
    { command: "go run ./cmd/gateway -addr 127.0.0.1:18080 -upstream ws://127.0.0.1:18765", cwd: gateway, url: "http://127.0.0.1:18080/debug/counters", reuseExistingServer: false },
    // the real orchestrator with mock providers, behind a second gateway
    // builds the docs index at start: minutes on a cold CI runner without the vector cache
    { command: "uv run python -m voicecore.server --providers mock --port 18766", cwd: root, port: 18766, reuseExistingServer: false, timeout: 600_000 },
    { command: "go run ./cmd/gateway -addr 127.0.0.1:18081 -upstream ws://127.0.0.1:18766", cwd: gateway, url: "http://127.0.0.1:18081/debug/counters", reuseExistingServer: false },
    // Step 07 WebRTC spike (Pion)
    { command: "go run ./cmd/pion-peer -addr 127.0.0.1:18090", cwd: experiments, url: "http://127.0.0.1:18090/stats", reuseExistingServer: false },
  ],
});
