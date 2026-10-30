import { encodeFrame, KIND_AGENT } from "@voicecore/protocol/frame";
import { afterEach, expect, test, vi } from "vitest";
import { VoiceClient } from "./client.ts";

class FakeSocket {
  static OPEN = 1;
  static last: FakeSocket;
  static all: FakeSocket[] = [];
  readonly url: string;
  readyState = 1;
  binaryType = "";
  sent: string[] = [];
  onopen?: () => void;
  onmessage?: (m: { data: string | ArrayBuffer }) => void;
  onclose?: (c: { code: number; reason: string }) => void;
  onerror?: () => void;
  constructor(url: string) { this.url = url; FakeSocket.last = this; FakeSocket.all.push(this); queueMicrotask(() => this.onopen?.()); }
  drop(code = 1006) { this.readyState = 3; this.onclose?.({ code, reason: "" }); }
  send(m: string) { this.sent.push(m); }
  close() {}
  deliver(m: string | Uint8Array) { this.onmessage?.({ data: typeof m === "string" ? m : m.buffer.slice(m.byteOffset, m.byteOffset + m.byteLength) as ArrayBuffer }); }
}

afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); FakeSocket.all = []; });

test("agent frames go to playout and agent.cancel reaches playout before the app sees it", async () => {
  vi.stubGlobal("WebSocket", FakeSocket);
  const calls: string[] = [];
  const c = new VoiceClient({ url: "ws://x", token: "t" });
  c.playout = { push: (g, s, _x, end) => calls.push(`push ${g}:${s}${end ? " end" : ""}`), cancel: (g) => calls.push(`cancel ${g}`) };
  c.onEvent = (e) => calls.push(`event ${e.type}`);
  const welcome = c.connect();
  await Promise.resolve();
  const ws = FakeSocket.last;
  ws.deliver(JSON.stringify({ type: "welcome", session_id: "s-1", resume_key: "k1", resume_window_ms: 10000, resumed: false }));
  await welcome;
  expect(JSON.parse(ws.sent[0]!).type).toBe("hello");
  ws.deliver(encodeFrame({ kind: KIND_AGENT, flags: 0, stream_id: 3, sequence: 0, capture_us: 0n, generation_id: 3, payload: new Int16Array(480) }));
  ws.deliver(JSON.stringify({ type: "agent.cancel", gen: 3 }));
  expect(calls).toEqual(["event welcome", "push 3:0", "cancel 3", "event agent.cancel"]);
  c.close();
});

test("a reconnecting client resumes the session it was given", async () => {
  vi.stubGlobal("WebSocket", FakeSocket);
  const c = new VoiceClient({ url: "ws://x", token: "t" });
  const first = c.connect();
  await Promise.resolve();
  FakeSocket.last.deliver(JSON.stringify({ type: "welcome", session_id: "s-gw-9", resume_key: "k9", resume_window_ms: 10000, resumed: false }));
  await first;
  void c.connect().catch(() => {});
  await Promise.resolve();
  const hello = JSON.parse(FakeSocket.last.sent[0]!);
  expect([hello.session_id, hello.resume_key]).toEqual(["s-gw-9", "k9"]); // the key proves the session is ours
  c.close();
});


const welcome = (resumed: boolean, id = "s-gw-9", key = "k9") =>
  JSON.stringify({ type: "welcome", session_id: id, resume_key: key, resume_window_ms: 10000, resumed });

async function connected(opts: Partial<ConstructorParameters<typeof VoiceClient>[0]> = {}) {
  vi.useFakeTimers();
  vi.stubGlobal("WebSocket", FakeSocket);
  const c = new VoiceClient({ url: "ws://gw/v1/ws", token: "t1", ...opts });
  const events: string[] = [];
  c.onEvent = (e) => events.push(e.type === "welcome" ? `welcome resumed=${e.resumed}` : e.type);
  const first = c.connect();
  await vi.advanceTimersByTimeAsync(0);
  FakeSocket.last.deliver(welcome(false));
  await first;
  return { c, events };
}

test("a dropped socket reconnects with the session and its key, and audio keeps flowing", async () => {
  const { c, events } = await connected();
  const pushed: number[] = [];
  c.playout = { push: (g) => pushed.push(g), cancel: () => {} };
  FakeSocket.last.drop();
  expect(events).toContain("socket.reconnecting");
  await vi.advanceTimersByTimeAsync(499);
  expect(FakeSocket.all.length).toBe(1);
  await vi.advanceTimersByTimeAsync(1);
  const ws = FakeSocket.last;
  expect(ws.url).toBe("ws://gw/v1/ws?resume=s-gw-9"); // lets a load balancer send it to the copy that owns the session
  const hello = JSON.parse(ws.sent[0]!);
  expect([hello.session_id, hello.resume_key, hello.token]).toEqual(["s-gw-9", "k9", "t1"]);
  ws.deliver(welcome(true));
  ws.deliver(encodeFrame({ kind: KIND_AGENT, flags: 0, stream_id: 3, sequence: 0, capture_us: 0n, generation_id: 4, payload: new Int16Array(480) }));
  expect(events.slice(-1)).toEqual(["welcome resumed=true"]);
  expect(pushed).toEqual([4]);
  expect(events).not.toContain("socket.closed");
  c.close();
});

test("three failed attempts at 0.5, 1 and 2 s end in socket.closed", async () => {
  const { c, events } = await connected();
  FakeSocket.last.drop();
  for (const ms of [500, 1000, 2000]) {
    await vi.advanceTimersByTimeAsync(ms);
    FakeSocket.last.drop(); // the gateway is not back
  }
  await vi.advanceTimersByTimeAsync(10_000);
  expect(FakeSocket.all.length).toBe(4);
  expect(events.filter((e) => e === "socket.closed")).toEqual(["socket.closed"]);
  c.close();
});

test("a resume refused with 4001 (the window passed, the token is spent) gets a fresh token", async () => {
  const tokens = ["t2"];
  const { c } = await connected({ getToken: async () => tokens.shift()! });
  FakeSocket.last.drop();
  await vi.advanceTimersByTimeAsync(500);
  FakeSocket.last.drop(4001);
  await vi.advanceTimersByTimeAsync(1000);
  expect(JSON.parse(FakeSocket.last.sent[0]!).token).toBe("t2");
  c.close();
});

test("closing on purpose never reconnects", async () => {
  const { c, events } = await connected();
  c.close();
  FakeSocket.last.drop(1000);
  await vi.advanceTimersByTimeAsync(10_000);
  expect(FakeSocket.all.length).toBe(1);
  expect(events).not.toContain("socket.reconnecting");
});
