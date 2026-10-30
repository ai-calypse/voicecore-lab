import { beforeEach, expect, test } from "vitest";
import { Playout, type PlayoutEvent } from "./playout.ts";
import { renderMs } from "./offline-adapter.ts";

const RATE = 24000;
let clock = 0; // us
let events: PlayoutEvent[] = [];
let p: Playout;

beforeEach(() => {
  clock = 1_000_000;
  events = [];
  p = new Playout({ rate: RATE, nowUs: () => clock, emit: (e) => events.push(e) });
});

const frame = (value: number) => new Int16Array(480).fill(value); // 20 ms at 24 kHz
const tick = (ms = 20) => {
  const out = renderMs(p, ms, RATE);
  clock += ms * 1000;
  return out;
};

test("first rendered sample of gen 1 emits playout.started{gen:1,t}", () => {
  tick();
  p.push(1, 0, frame(1000), false);
  const out = tick();
  expect(out[0]).toBeCloseTo(1000 / 32768);
  expect(events).toEqual([{ type: "playout.started", gen: 1, t_us: 1_020_000 }]);
});

test("no frame for 100 ms during a generation -> silence rendered, underrun_ms = 100", () => {
  p.push(1, 0, frame(1000), false);
  tick();
  const silent = [tick(), tick(), tick(), tick(), tick()];
  expect(silent.every((b) => b.every((s) => s === 0))).toBe(true);
  expect(p.underrunMs).toBe(100);
  p.push(1, 1, frame(1000), true);
  tick();
  tick(); // after end_of_stream, silence is not an underrun
  expect(p.underrunMs).toBe(100);
  expect(events.at(-1)).toEqual({ type: "playout.stopped", gen: 1, reason: "done", t_us: 1_140_000 });
});

test("after cancel(1) no sample of gen <= 1 is rendered; emits stopped{cancel} and cancel.ack", () => {
  for (let s = 0; s < 5; s++) p.push(1, s, frame(1000), false);
  tick();
  tick();
  p.cancel(1);
  p.push(1, 5, frame(1000), false); // late frame of the cancelled generation
  expect(tick().every((s) => s === 0)).toBe(true);
  expect(events).toEqual([
    { type: "playout.started", gen: 1, t_us: 1_000_000 },
    { type: "playout.stopped", gen: 1, reason: "cancel", t_us: 1_040_000 },
    { type: "cancel.ack", gen: 1, played_until_seq: 1 },
  ]);
  expect(p.underrunMs).toBe(0);
});

test("cancel before any sample was rendered acks with played_until_seq -1 and no stopped event", () => {
  p.push(1, 0, frame(1000), false);
  p.cancel(1);
  expect(tick().every((s) => s === 0)).toBe(true);
  expect(events).toEqual([{ type: "cancel.ack", gen: 1, played_until_seq: -1 }]);
});

test("gen 2 plays after cancel(1)", () => {
  p.push(1, 0, frame(1000), false);
  tick();
  p.cancel(1);
  p.push(2, 0, frame(2000), true);
  expect(tick()[0]).toBeCloseTo(2000 / 32768);
  expect(events.map((e) => [e.type, e.gen])).toEqual([
    ["playout.started", 1], ["playout.stopped", 1], ["cancel.ack", 1], ["playout.started", 2], ["playout.stopped", 2],
  ]);
});

test("pause stops rendering without counting underrun; resume continues from the next sample", () => {
  const ramp = Int16Array.from({ length: 480 }, (_, i) => i);
  p.push(1, 0, ramp, false);
  renderMs(p, 10, RATE); // first 240 samples
  p.pause();
  expect(tick().every((s) => s === 0)).toBe(true);
  expect(p.underrunMs).toBe(0);
  p.resume();
  expect(renderMs(p, 1, RATE)[0]).toBeCloseTo(240 / 32768);
});
