import { Framer } from "./framer.ts";
import { floatToPcm16 } from "./pcm.ts";
import { Resampler } from "./resample.ts";

// Thin AudioWorklet adapter: copies each 128-sample render quantum of channel 0 to the main thread.
const WORKLET = `registerProcessor("vc-capture", class extends AudioWorkletProcessor {
  process(inputs) { const ch = inputs[0] && inputs[0][0]; if (ch) this.port.postMessage(ch.slice(0)); return true; }
});`;

export type MicFrame = { sequence: number; capture_us: bigint; samples: Int16Array };

/** Asks for the microphone, then emits 20 ms PCM16 frames at 16 kHz. Nothing is captured before consent. */
export async function startCapture(onFrame: (f: MicFrame) => void, nowUs = () => performance.now() * 1000): Promise<() => void> {
  const stream = await navigator.mediaDevices.getUserMedia({
    audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
  });
  const ctx = new AudioContext();
  await ctx.resume(); // the user gesture may have expired while the permission prompt was open
  const url = URL.createObjectURL(new Blob([WORKLET], { type: "text/javascript" }));
  await ctx.audioWorklet.addModule(url);
  URL.revokeObjectURL(url);
  const node = new AudioWorkletNode(ctx, "vc-capture", { numberOfOutputs: 0 });
  const resampler = new Resampler(ctx.sampleRate);
  const framer = new Framer(320);
  let startUs: number | undefined;
  node.port.onmessage = (e: MessageEvent<Float32Array>) => {
    startUs ??= nowUs() - (e.data.length / ctx.sampleRate) * 1e6;
    for (const f of framer.push(floatToPcm16(resampler.push(e.data)))) {
      onFrame({ sequence: f.sequence, capture_us: BigInt(Math.round(startUs + f.sequence * 20000)), samples: f.samples });
    }
  };
  ctx.createMediaStreamSource(stream).connect(node);
  return () => {
    node.port.onmessage = null;
    for (const t of stream.getTracks()) t.stop();
    void ctx.close();
  };
}
