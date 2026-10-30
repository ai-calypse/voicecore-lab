// Headless client: the real SDK client and playout module in Node, a WAV fixture as the microphone.
//   node packages/web-sdk/bin/headless-client.ts --fixture clip.wav --out log.jsonl [--gateway http://127.0.0.1:8080] [--tail 15] [--text "..."]
// Barge-in scripts: --text asks first; --interrupt-after MS starts the fixture MS after playback begins;
// --echo-db -15 mixes the client's own rendered audio back into the mic 40 ms later (a simulated room);
// --onset-ms is the fixture's labelled speech start; --exit-after-cancel-ms ends the run after a cancel.
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
  "interrupt-after": { type: "string" },
  "echo-db": { type: "string" },
  "onset-ms": { type: "string", default: "0" },
  "exit-after-cancel-ms": { type: "string" },
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
const interruptAfter = a["interrupt-after"] === undefined ? null : Number(a["interrupt-after"]);
const echoGain = a["echo-db"] === undefined ? 0 : 10 ** (Number(a["echo-db"]) / 20);
let fixtureStart: number | null = interruptAfter === null ? 0 : null; // mic frame index where the fixture starts
let micSeq = 0, micT0 = 0;
const echo: Float32Array[] = [new Float32Array(320), new Float32Array(320)]; // 2 frames = 40 ms acoustic delay
let done: () => void = () => {};
const finished = new Promise<void>((r) => { done = r; });

function micFrame(seq: number): Int16Array {
  const out = new Int16Array(320);
  if (fixtureStart !== null && seq >= fixtureStart) out.set(pcm.subarray((seq - fixtureStart) * 320, (seq - fixtureStart + 1) * 320));
  const e = echoGain ? echo.shift() : undefined;
  if (e) for (let i = 0; i < 320; i++) out[i] = Math.max(-32768, Math.min(32767, out[i]! + Math.round(e[i]! * 32767 * echoGain)));
  return out;
}
const { token } = await (await fetch(`${a.gateway}/v1/session`, { method: "POST" })).json();
const client = new VoiceClient({
  url: a.gateway.replace(/^http/, "ws") + "/v1/ws", token, nowUs,
  // fake microphone: the fixture, then silence, paced at 20 ms
  startMic: async (onFrame) => {
    let stop = false;
    void (async () => {
      const t0 = (micT0 = nowUs());
      log({ type: "mic.start", t0_us: t0 }); // capture_us of frame k is t0 + 20,000 k: fixture labels map onto this clock
      for (let seq = 0; !stop; seq++) {
        if (fixtureStart !== null && seq >= fixtureStart + Math.ceil(pcm.length / 320) + tailMs / 20) break;
        if (seq > 3000) break; // 60 s safety stop, e.g. when playback never starts
        await sleep((t0 + (seq + 1) * 20_000 - nowUs()) / 1000); // a frame leaves when its last sample is captured
        micSeq = seq;
        onFrame({ sequence: seq, capture_us: BigInt(t0 + seq * 20_000), samples: micFrame(seq) });
      }
      done();
    })();
    return () => { stop = true; };
  },
});
const playout = new Playout({ rate: 24000, nowUs, emit: (e) => {
  log({ dir: "out", ...e });
  client.send(e);
  if (e.type === "playout.started" && fixtureStart === null && interruptAfter !== null) {
    fixtureStart = micSeq + Math.round(interruptAfter / 20);
    log({ type: "user.onset", onset_us: micT0 + (fixtureStart * 20 + Number(a["onset-ms"])) * 1000 });
  }
  if (e.type === "playout.stopped" && e.reason === "cancel" && a["exit-after-cancel-ms"] !== undefined) {
    setTimeout(done, Number(a["exit-after-cancel-ms"]));
  }
} });
client.playout = { push: (g, s, x, end) => playout.push(g, s, x, end), cancel: (g) => playout.cancel(g) };
client.onEvent = (e) => log({ dir: "in", ...e });
// Render like a sound card: by the wall clock, catching up when the timer fires late. A plain 20 ms interval runs
// slow in Node, and playback drifting behind real time misaligns the server's echo reference (seen live: false barge-ins).
const renderStart = nowUs();
let rendered = 0;
const render = setInterval(() => {
  while ((rendered + 1) * 20_000 <= nowUs() - renderStart) {
    rendered++;
    const block = renderMs(playout, 20); // 480 samples at 24 kHz
    if (!echoGain) continue;
    const down = new Float32Array(320); // 24 -> 16 kHz by linear interpolation
    for (let j = 0; j < 320; j++) { const x = j * 1.5, i = Math.floor(x), f = x - i; down[j] = block[i]! * (1 - f) + (block[i + 1] ?? block[i]!) * f; }
    echo.push(down);
  }
  while (echo.length > 4) echo.shift(); // mic and render timers are separate; keep the delay near 40 ms
}, 5);

log({ type: "client.start", fixture: a.fixture ?? null });
await client.connect();
if (a.fixture || echoGain) await client.startMic();
if (a.text) client.send({ type: "text.input", text: a.text });
await (a.fixture || echoGain ? finished : sleep(tailMs));
log({ type: "client.end", underrun_ms: playout.underrunMs });
clearInterval(render);
client.close();
setTimeout(() => process.exit(0), 200);
