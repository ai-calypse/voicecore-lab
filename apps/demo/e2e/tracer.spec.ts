import { expect, test } from "@playwright/test";

test("fake-mic audio round-trips through the gateway and the page emits playout.started", async ({ page, request }) => {
  await page.goto("/");
  await page.evaluate(async () => {
    type Any = any;
    const vc = (window as Any).voicecore;
    const events: Any[] = [];
    (window as Any).events = events;
    const { token } = await (await fetch("http://127.0.0.1:18080/v1/session", { method: "POST" })).json();
    const c = new vc.VoiceClient({ url: "ws://127.0.0.1:18080/v1/ws", token });
    c.playout = await vc.startPlayout((e: Any) => { events.push(e); c.send(e); });
    c.onEvent = (e: Any) => events.push(e);
    await c.connect();
    await c.startMic();
  });
  await expect.poll(() => page.evaluate(() => (window as any).events.map((e: any) => e.type)), { timeout: 10_000 })
    .toEqual(expect.arrayContaining(["welcome", "agent.generation_started", "playout.started"]));
  const started = await page.evaluate(() => (window as any).events.find((e: any) => e.type === "playout.started"));
  expect(started.gen).toBe(1);
  expect(started.t_us).toBeGreaterThan(0);
  const counters = await (await request.get("http://127.0.0.1:18080/debug/counters")).json();
  expect(counters).toMatchObject({ drops_duplicate: 0, drops_stale: 0, drops_overload: 0, gaps: 0 });
});
