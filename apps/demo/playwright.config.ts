import { defineConfig } from "@playwright/test";
import { fileURLToPath } from "node:url";

const gateway = fileURLToPath(new URL("../../services/realtime-gateway", import.meta.url));
const fixture = fileURLToPath(new URL("../../fixtures/audio/dev/single_01.wav", import.meta.url));

export default defineConfig({
  testDir: "e2e",
  timeout: 30_000,
  use: {
    baseURL: "http://127.0.0.1:5173",
    permissions: ["microphone"],
    launchOptions: {
      args: ["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream", `--use-file-for-fake-audio-capture=${fixture}%noloop`, "--autoplay-policy=no-user-gesture-required"],
    },
  },
  projects: [{ name: "chromium", use: { browserName: "chromium" } }],
  webServer: [
    { command: "pnpm exec vite --host 127.0.0.1 --port 5173 --strictPort", url: "http://127.0.0.1:5173", reuseExistingServer: true },
    { command: "go run ./cmd/fakeorch -addr 127.0.0.1:8765", cwd: gateway, port: 8765, reuseExistingServer: true },
    { command: "go run ./cmd/gateway -addr 127.0.0.1:8080 -upstream ws://127.0.0.1:8765", cwd: gateway, url: "http://127.0.0.1:8080/debug/counters", reuseExistingServer: true },
  ],
});
