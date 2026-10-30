import { expect, test } from "@playwright/test";
import { decodeEvent } from "@voicecore/protocol/events";
import { decodeFrame } from "@voicecore/protocol/frame";
import { once } from "node:events";
import { WebSocketServer } from "ws";

test("test WS server gets 0 binary frames before start(), then 20 ms frames at 16 kHz", async ({ page }) => {
  const wss = new WebSocketServer({ port: 0, host: "127.0.0.1" });
  const frames: Buffer[] = [];
  const events: string[] = [];
  wss.on("connection", (ws) => ws.on("message", (data, isBinary) => {
    if (isBinary) frames.push(data as Buffer);
    else {
      const e = decodeEvent(String(data));
      events.push(e.type);
      if (e.type === "hello") ws.send(JSON.stringify({ type: "welcome", session_id: "s-gw-test", resume_key: "k", resume_window_ms: 10000, resumed: false }));
    }
  }));
  await once(wss, "listening");
  const url = `ws://127.0.0.1:${(wss.address() as { port: number }).port}`;
  await page.goto("/");
  await page.evaluate(async (url) => {
    const w = window as unknown as { voicecore: { VoiceClient: new (o: object) => { connect(): Promise<unknown>; startMic(): Promise<void> } }; client: unknown };
    const c = new w.voicecore.VoiceClient({ url, token: "t" });
    w.client = c;
    await c.connect();
  }, url);
  await page.waitForTimeout(500);
  expect(events).toEqual(["hello"]);
  expect(frames).toHaveLength(0);

  await page.evaluate(() => (window as unknown as { client: { startMic(): Promise<void> } }).client.startMic());
  await page.waitForTimeout(2500);
  expect(frames.length).toBeGreaterThan(50);
  const decoded = frames.map((b) => decodeFrame(new Uint8Array(b.buffer, b.byteOffset, b.byteLength)));
  expect(new Set(decoded.map((f) => f.kind))).toEqual(new Set([1]));
  expect(new Set(decoded.map((f) => f.samples))).toEqual(new Set([320]));
  expect(decoded.map((f) => f.sequence)).toEqual(decoded.map((_, i) => i));
  const step = decoded.slice(1).map((f, i) => Number(f.capture_us - decoded[i]!.capture_us));
  expect(new Set(step)).toEqual(new Set([20000]));
  const peak = Math.max(...decoded.map((f) => Math.max(...Array.from(f.payload, Math.abs))));
  expect(peak).toBeGreaterThan(1000); // the fixture's speech starts at 1.0 s
  wss.close();
});
