import { expect, test } from "@playwright/test";
import { mkdirSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

// Step 07: browser mic -> WebRTC (Opus/RTP) -> Pion peer -> rtp jitter buffer. One Pion process, so serial.
test.describe.configure({ mode: "serial" });
const stats = async (request: import("@playwright/test").APIRequestContext) => (await request.get("http://127.0.0.1:18090/stats")).json();

test("the browser connects to the Pion peer and Opus RTP flows through the jitter buffer", async ({ page, request }) => {
  await page.goto("http://127.0.0.1:18090/");
  await expect.poll(async () => (await stats(request)).webrtc?.stream.packets ?? 0, { timeout: 15_000 }).toBeGreaterThan(100);
  const s = await stats(request);
  const steps = s.steps.map((x: { step: string }) => x.step);
  expect(steps).toEqual(expect.arrayContaining(["offer applied", "answer sent", "ice connected", "dtls connected", "connection connected"]));
  expect(s.webrtc.stream.codec).toBe("audio/opus");
  expect(s.webrtc.stream.played).toBeGreaterThan(50);
  expect(s.webrtc.interarrival_ms.p50).toBeGreaterThan(15);
  expect(s.webrtc.interarrival_ms.p50).toBeLessThan(25);
});

// S07-T03 benchmark (not a CI gate): the same fake mic over both transports for 10 s each, timed by one process.
test("compare WebSocket and WebRTC mic streams on loopback", async ({ page, browser, request }) => {
  test.skip(!process.env.BENCH, "set BENCH=1 to run the transport comparison");
  test.setTimeout(60_000);
  await page.goto("http://127.0.0.1:18090/");
  await page.waitForTimeout(10_000);
  const ws = await browser.newPage();
  await ws.goto("/");
  await ws.evaluate(async () => {
    const w = window as any;
    const c = new w.voicecore.VoiceClient({ url: "ws://127.0.0.1:18090/ws", token: "n/a" });
    await c.connect();
    await c.startMic();
  });
  await ws.waitForTimeout(10_000);
  const s = await stats(request);
  const dir = fileURLToPath(new URL("../../../benchmarks/raw/", import.meta.url));
  mkdirSync(dir, { recursive: true });
  writeFileSync(`${dir}webrtc_vs_ws_${new Date().toISOString().replace(/[-:]/g, "").slice(0, 15)}Z.json`, JSON.stringify(s, null, 1));
  expect(s.webrtc.stream.packets).toBeGreaterThan(400);
  expect(s.websocket.stream.packets).toBeGreaterThan(400);
});
