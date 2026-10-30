import { expect, test } from "vitest";
import { Framer } from "./framer.ts";
import { floatToPcm16 } from "./pcm.ts";
import { Resampler } from "./resample.ts";

const sine = (hz: number, rate: number, seconds: number) =>
  Float32Array.from({ length: rate * seconds }, (_, i) => 0.5 * Math.sin((2 * Math.PI * hz * i) / rate));

const zeroCrossings = (x: Float32Array) => {
  let n = 0;
  for (let i = 1; i < x.length; i++) if (x[i - 1]! < 0 !== x[i]! < 0) n++;
  return n;
};

test("48 kHz 1 kHz sine -> 16 kHz keeps 1 kHz (2000 zero-crossings/s +-1%)", () => {
  const out = new Resampler(48000).push(sine(1000, 48000, 1));
  expect(zeroCrossings(out)).toBeGreaterThanOrEqual(1980);
  expect(zeroCrossings(out)).toBeLessThanOrEqual(2020);
});

test("4800 samples at 48 kHz -> 1600; 4410 at 44.1 kHz -> 1600, also when pushed in 128-sample chunks", () => {
  expect(new Resampler(48000).push(new Float32Array(4800)).length).toBe(1600);
  expect(new Resampler(44100).push(new Float32Array(4410)).length).toBe(1600);
  const r = new Resampler(44100);
  let n = 0;
  for (let i = 0; i < 4410; i += 128) n += r.push(new Float32Array(Math.min(128, 4410 - i))).length;
  expect(n).toBe(1600);
});

test("8 kHz tone above 16 kHz Nyquist is attenuated by at least 20 dB", () => {
  const out = new Resampler(48000).push(sine(9000, 48000, 1)).slice(100);
  const rms = Math.sqrt(out.reduce((s, v) => s + v * v, 0) / out.length);
  expect(rms).toBeLessThan((0.5 / Math.SQRT2) * 0.1);
});

test("rule clamp(-1,1) then round(s<0 ? s*32768 : s*32767): 0.5 -> 0x4000, 1.5 -> 0x7FFF, -1.5 -> -0x8000", () => {
  expect(Array.from(floatToPcm16(Float32Array.of(0.5, 1.5, -1.5, 0)))).toEqual([16384, 32767, -32768, 0]);
});

test("330 samples -> one 320-sample frame, 10 kept; sequence 0,1,2...", () => {
  const f = new Framer(320);
  const first = f.push(new Int16Array(330));
  expect(first.map((x) => [x.sequence, x.samples.length])).toEqual([[0, 320]]);
  expect(f.push(new Int16Array(630)).map((x) => [x.sequence, x.samples.length])).toEqual([[1, 320], [2, 320]]);
});
