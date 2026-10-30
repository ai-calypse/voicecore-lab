// Headless client: the real SDK client and playout module in Node, a WAV fixture as the microphone.
//   node packages/web-sdk/bin/headless-client.ts --fixture clip.wav --out log.jsonl [--gateway http://127.0.0.1:8080] [--tail 15] [--text "..."]
// Mic frames are paced in real time (20 ms); playout renders 20 ms every 20 ms. Every event is logged with
// this process's monotonic clock (performance.now, us) so the harness timeline can align it.
import { appendFileSync, readFileSync, writeFileSync } from "node:fs";
import { parseArgs } from "node:util";
import { VoiceClient } from "../src/client.ts";
import { renderMs } from "../src/playout/offline-adapter.ts";
import { Playout } from "../src/playout/playout.ts";

const { values: a } = parseArgs({ options: {
  gateway: { type: "string", default: "http://127.0.0.1:8080" },
  fixture: { type: "string" },
  out: { type: "string" },
  tail: { type: "string", default: "15" },
  text: { type: "string" },
} });
if (!a.out || (!a.fixture && !a.text)) throw new Error("need --out and --fixture or --text");
const out = a.out;
writeFileSync(out, "");
const nowUs = () => Math.round(performance.now() * 1000);
const log = (e: object) => appendFileSync(out, JSON.stringify({ t_us: nowUs(), process: "headless", ...e }) + "\n");
const sleep = (ms: number) => new Promise((r) => setTimeout(r, Math.max(0, ms)));

function readWav(path: string): Int16Array {
  const b = readFileSync(path);
  let i = 12;
  while (i + 8 <= b.length) {
    const id = b.toString("ascii", i, i + 4), size = b.readUInt32LE(i + 4);
    if (id === "data") return new Int16Array(b.buffer.slice(b.byteOffset + i + 8, b.byteOffset + i + 8 + size));
    i += 8 + size + (size % 2);
  }
  throw new Error("no data chunk");
}

const pcm = a.fixture ? readWav(a.fixture) : new Int16Array(0);
const tailMs = Number(a.tail) * 1000;
const { token } = await (await fetch(`${a.gateway}/v1/session`, { method: "POST" })).json();
const client = new VoiceClient({
  url: a.gateway.replace(/^http/, "ws") + "/v1/ws", token, nowUs,
  // fake microphone: the fixture, then silence, paced at 20 ms
  startMic: async (onFrame) => {
    let stop = false;
    void (async () => {
      const t0 = nowUs(), total = Math.ceil(pcm.length / 320) + tailMs / 20;
      log({ type: "mic.start", t0_us: t0 }); // capture_us of frame k is t0 + 20,000 k: fixture labels map onto this clock
      for (let seq = 0; seq < total && !stop; seq++) {
        await sleep((t0 + (seq + 1) * 20_000 - nowUs()) / 1000); // a frame leaves when its last sample is captured
        const samples = new Int16Array(320);
        samples.set(pcm.subarray(seq * 320, seq * 320 + 320));
        onFrame({ sequence: seq, capture_us: BigInt(t0 + seq * 20_000), samples });
      }
    })();
    return () => { stop = true; };
  },
});
const playout = new Playout({ rate: 24000, nowUs, emit: (e) => { log({ dir: "out", ...e }); client.send(e); } });
client.playout = { push: (g, s, x, end) => playout.push(g, s, x, end), cancel: (g) => playout.cancel(g) };
client.onEvent = (e) => log({ dir: "in", ...e });
const render = setInterval(() => renderMs(playout, 20), 20);

log({ type: "client.start", fixture: a.fixture ?? null });
await client.connect();
if (a.fixture) await client.startMic();
if (a.text) client.send({ type: "text.input", text: a.text });
await sleep(pcm.length / 16 + tailMs);
log({ type: "client.end", underrun_ms: playout.underrunMs });
clearInterval(render);
client.close();
setTimeout(() => process.exit(0), 200);
