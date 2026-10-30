import { Playout, type PlayoutEvent } from "./playout.ts";

// The Playout class runs on the audio thread; its source is injected so no bundler step is needed.
const source = () => `const Playout = ${Playout.toString()};
registerProcessor("vc-playout", class extends AudioWorkletProcessor {
  constructor() {
    super();
    this.p = new Playout({ rate: sampleRate, nowUs: () => currentTime * 1e6, emit: (e) => this.port.postMessage(e) });
    this.port.onmessage = ({ data: m }) => {
      if (m.op === "push") this.p.push(m.gen, m.seq, m.samples, m.end);
      else if (m.op === "cancel") this.p.cancel(m.gen);
      else if (m.op === "pause") this.p.pause();
      else if (m.op === "resume") this.p.resume();
    };
  }
  process(_inputs, outputs) { this.p.render(outputs[0][0]); return true; }
});`;

export type PlayoutHandle = {
  push(gen: number, seq: number, samples: Int16Array, end: boolean): void;
  cancel(gen: number): void;
  pause(): void;
  resume(): void;
  close(): void;
};

/** Starts browser playout at 24 kHz. Event times are converted to the page clock (performance.now, us). */
export async function startPlayout(onEvent: (e: PlayoutEvent) => void): Promise<PlayoutHandle> {
  const ctx = new AudioContext({ sampleRate: 24000, latencyHint: "interactive" });
  const url = URL.createObjectURL(new Blob([source()], { type: "text/javascript" }));
  await ctx.audioWorklet.addModule(url);
  URL.revokeObjectURL(url);
  const node = new AudioWorkletNode(ctx, "vc-playout", { numberOfInputs: 0, outputChannelCount: [1] });
  node.connect(ctx.destination);
  node.port.onmessage = ({ data: e }: MessageEvent<PlayoutEvent>) => {
    if ("t_us" in e) {
      const ts = ctx.getOutputTimestamp();
      e.t_us = Math.round((ts.performanceTime ?? 0) * 1000 + (e.t_us - (ts.contextTime ?? 0) * 1e6));
    }
    onEvent(e);
  };
  await ctx.resume();
  const post = (m: object) => node.port.postMessage(m);
  return {
    push: (gen, seq, samples, end) => post({ op: "push", gen, seq, samples, end }),
    cancel: (gen) => post({ op: "cancel", gen }),
    pause: () => post({ op: "pause" }),
    resume: () => post({ op: "resume" }),
    close: () => void ctx.close(),
  };
}
