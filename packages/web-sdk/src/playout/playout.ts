// Ordered playout with generation fencing (SPEC.md section 3). Pull model: an adapter calls
// render() once per audio block. This class must stay self-contained (no imports, no outside
// references): worklet-adapter.ts injects its source text into an AudioWorklet.

export type PlayoutEvent =
  | { type: "playout.started"; gen: number; t_us: number }
  | { type: "playout.stopped"; gen: number; reason: "done" | "cancel"; t_us: number }
  | { type: "cancel.ack"; gen: number; played_until_seq: number };

type Chunk = { gen: number; seq: number; samples: Int16Array; end: boolean; offset: number };

export type PlayoutOptions = { rate: number; nowUs: () => number; emit: (e: PlayoutEvent) => void };

export class Playout {
  underrunMs = 0;
  private queue: Chunk[] = [];
  private fence = 0;
  private gen = 0; // generation being played; 0 = none
  private playedSeq = -1; // last frame of `gen` with at least one rendered sample
  private finished = { gen: 0, seq: -1 }; // the last generation that played to its end
  private paused = false;
  private opts: PlayoutOptions;

  constructor(opts: PlayoutOptions) {
    this.opts = opts;
  }

  push(gen: number, seq: number, samples: Int16Array, end: boolean): void {
    if (gen > this.fence) this.queue.push({ gen, seq, samples, end, offset: 0 });
  }

  /** Drops generation `gen` and every older one, now and later. */
  cancel(gen: number): void {
    this.fence = Math.max(this.fence, gen);
    this.queue = this.queue.filter((c) => c.gen > this.fence);
    let played = gen === this.finished.gen ? this.finished.seq : -1;
    if (this.gen !== 0 && this.gen <= this.fence) {
      played = this.gen === gen ? this.playedSeq : -1;
      this.opts.emit({ type: "playout.stopped", gen: this.gen, reason: "cancel", t_us: this.opts.nowUs() });
      this.gen = 0;
    }
    this.opts.emit({ type: "cancel.ack", gen, played_until_seq: played });
  }

  pause(): void {
    this.paused = true;
  }

  resume(): void {
    this.paused = false;
  }

  render(out: Float32Array): void {
    out.fill(0);
    if (this.paused) return;
    const t0 = this.opts.nowUs();
    const at = (i: number) => t0 + Math.round((i * 1e6) / this.opts.rate);
    let i = 0;
    while (i < out.length && this.queue.length > 0) {
      const c = this.queue[0]!;
      if (c.gen !== this.gen) {
        if (this.gen !== 0) this.opts.emit({ type: "playout.stopped", gen: this.gen, reason: "done", t_us: at(i) });
        this.gen = c.gen;
        this.playedSeq = -1;
        this.opts.emit({ type: "playout.started", gen: c.gen, t_us: at(i) });
      }
      const n = Math.min(c.samples.length - c.offset, out.length - i);
      for (let k = 0; k < n; k++) out[i + k] = c.samples[c.offset + k]! / 32768;
      if (n > 0) this.playedSeq = c.seq;
      c.offset += n;
      i += n;
      if (c.offset === c.samples.length) {
        this.queue.shift();
        if (c.end) {
          this.finished = { gen: c.gen, seq: c.seq };
          this.opts.emit({ type: "playout.stopped", gen: c.gen, reason: "done", t_us: at(i) });
          this.gen = 0;
        }
      }
    }
    if (this.gen !== 0 && i < out.length) this.underrunMs += ((out.length - i) * 1000) / this.opts.rate;
  }
}
