import type { Playout } from "./playout.ts";

/** Renders `ms` of audio without a sound card (tests and the headless client). */
export function renderMs(p: Playout, ms: number, rate = 24000): Float32Array {
  const out = new Float32Array((rate * ms) / 1000);
  p.render(out);
  return out;
}
