// Streaming resampler to 16 kHz: windowed-sinc low-pass (7 kHz cutoff, Hann, 64 taps) evaluated at
// fractional input positions. Deterministic, stateful across chunks, delay = HALF input samples.
const HALF = 32;

export class Resampler {
  private readonly step: number;
  private readonly fc: number; // cutoff in cycles per input sample
  private buf = new Float32Array(2 * HALF); // zero history so the first outputs have a full window
  private base = -2 * HALF; // absolute input index of buf[0]
  private n = 0; // input samples received
  private k = 0; // next output index

  constructor(inRate: number, outRate = 16000) {
    this.step = inRate / outRate;
    this.fc = (0.4375 * Math.min(inRate, outRate)) / inRate;
  }

  push(x: Float32Array): Float32Array {
    const joined = new Float32Array(this.buf.length + x.length);
    joined.set(this.buf);
    joined.set(x, this.buf.length);
    this.buf = joined;
    this.n += x.length;
    const out: number[] = [];
    for (let t = this.k * this.step; t < this.n; t = ++this.k * this.step) {
      const c = t - HALF; // kernel centre; needs samples up to floor(t) <= n - 1
      const j0 = Math.floor(c) - HALF + 1;
      let acc = 0, wsum = 0;
      for (let j = j0; j < j0 + 2 * HALF; j++) {
        const d = c - j;
        const w = (0.5 + 0.5 * Math.cos((Math.PI * d) / HALF)) * (d === 0 ? 1 : Math.sin(2 * Math.PI * this.fc * d) / (2 * Math.PI * this.fc * d));
        acc += w * this.buf[j - this.base]!;
        wsum += w;
      }
      out.push(acc / wsum);
    }
    const keep = Math.floor(this.k * this.step - HALF) - HALF + 1 - this.base; // first sample the next output needs
    if (keep > 0) {
      this.buf = this.buf.slice(keep);
      this.base += keep;
    }
    return Float32Array.from(out);
  }
}
