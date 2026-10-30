import { expect, test } from "@playwright/test";

// Seam 9b in CI: browser fake mic -> Go gateway -> Python orchestrator (Silero VAD, floor, generation runtime,
// mock STT/LLM/TTS) -> browser playout.
test("a spoken turn through the gateway and orchestrator gets an answer that plays", async ({ page }) => {
  await page.goto("/");
  await page.evaluate(async () => {
    const w = window as any;
    const events: any[] = [];
    w.events = events;
    const { token } = await (await fetch("http://127.0.0.1:8081/v1/session", { method: "POST" })).json();
    const c = new w.voicecore.VoiceClient({ url: "ws://127.0.0.1:8081/v1/ws", token });
    c.playout = await w.voicecore.startPlayout((e: any) => { events.push(e); c.send(e); });
    c.onEvent = (e: any) => events.push(e);
    await c.connect();
    await c.startMic();
  });
  const types = () => page.evaluate(() => (window as any).events.map((e: any) => e.type));
  await expect.poll(types, { timeout: 25_000 }).toEqual(expect.arrayContaining(
    ["user.speech_started", "transcript.final", "agent.generation_started", "agent.text", "playout.started"]));
  const final = await page.evaluate(() => (window as any).events.find((e: any) => e.type === "transcript.final"));
  expect(final.text).toBe("how does eager endpointing work?");
});
