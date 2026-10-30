import { encodeFrame, KIND_AGENT } from "@voicecore/protocol/frame";
import { afterEach, expect, test, vi } from "vitest";
import { VoiceClient } from "./client.ts";

class FakeSocket {
  static OPEN = 1;
  static last: FakeSocket;
  readyState = 1;
  binaryType = "";
  sent: string[] = [];
  onopen?: () => void;
  onmessage?: (m: { data: string | ArrayBuffer }) => void;
  onclose?: (c: { code: number; reason: string }) => void;
  onerror?: () => void;
  constructor(_url: string) { FakeSocket.last = this; queueMicrotask(() => this.onopen?.()); }
  send(m: string) { this.sent.push(m); }
  close() {}
  deliver(m: string | Uint8Array) { this.onmessage?.({ data: typeof m === "string" ? m : m.buffer.slice(m.byteOffset, m.byteOffset + m.byteLength) as ArrayBuffer }); }
}

afterEach(() => vi.unstubAllGlobals());

test("agent frames go to playout and agent.cancel reaches playout before the app sees it", async () => {
  vi.stubGlobal("WebSocket", FakeSocket);
  const calls: string[] = [];
  const c = new VoiceClient({ url: "ws://x", token: "t" });
  c.playout = { push: (g, s, _x, end) => calls.push(`push ${g}:${s}${end ? " end" : ""}`), cancel: (g) => calls.push(`cancel ${g}`) };
  c.onEvent = (e) => calls.push(`event ${e.type}`);
  const welcome = c.connect();
  await Promise.resolve();
  const ws = FakeSocket.last;
  ws.deliver(JSON.stringify({ type: "welcome", session_id: "s-1", resume_window_ms: 10000, resumed: false }));
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
  FakeSocket.last.deliver(JSON.stringify({ type: "welcome", session_id: "s-9", resume_window_ms: 10000, resumed: false }));
  await first;
  void c.connect().catch(() => {});
  await Promise.resolve();
  expect(JSON.parse(FakeSocket.last.sent[0]!).session_id).toBe("s-9");
  c.close();
});
