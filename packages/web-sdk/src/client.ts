import { decodeEvent, encodeEvent, type Event } from "@voicecore/protocol/events";
import { decodeFrame, encodeFrame, FLAG_END_OF_STREAM, KIND_MIC, type Frame, type FrameInit } from "@voicecore/protocol/frame";
import { startCapture } from "./capture/index.ts";
import type { PlayoutHandle } from "./playout/worklet-adapter.ts";

export type ClientOptions = {
  url: string;
  token: string;
  sessionId?: string; // resume this session (with its resumeKey)
  resumeKey?: string; // from welcome: the proof that the session is ours
  nowUs?: () => number;
  startMic?: typeof startCapture; // injectable for headless clients
  getToken?: () => Promise<string>; // a fresh token when a resume is refused (the window passed, the token is spent)
  retryDelaysMs?: number[]; // reconnect attempts after an unexpected close; the default outlasts the 10 s resume window
};

const RETRY_DELAYS_MS = [500, 1000, 2000, 4000, 4000];
const NO_RETRY = new Set([1000, 1007, 1008, 4002]); // normal end, or a policy close a retry would only repeat

/** One WebSocket session: hello/welcome, mic frames out, events and agent frames in, clock pings.
 *  An unexpected close after welcome reconnects (resuming the session) before onEvent sees socket.closed. */
export class VoiceClient {
  onEvent: (e: Event) => void = () => {};
  onAgentFrame: (f: Frame) => void = () => {};
  /** where agent audio goes; agent.cancel is applied to it before onEvent sees the event */
  playout?: Pick<PlayoutHandle, "push" | "cancel">;
  sessionId?: string;
  resumeKey?: string;
  /** server clock minus client clock in us, from the last pong (NaN until the first one) */
  offsetUs = NaN;
  private ws?: WebSocket;
  // random start so a new client resuming a session never reuses a stream id the gateway already saw
  private streamId = crypto.getRandomValues(new Uint32Array(1))[0]!;
  private stopCapture?: () => void;
  private pinger?: ReturnType<typeof setInterval>;
  private readonly opts: ClientOptions;
  private readonly nowUs: () => number;
  private token: string;
  private closing = false;
  private reconnecting = false;
  private run = 0; // bumped by close(): a reconnect loop from before it stops for good

  constructor(opts: ClientOptions) {
    this.opts = opts;
    this.token = opts.token;
    this.nowUs = opts.nowUs ?? (() => performance.now() * 1000);
  }

  connect(): Promise<Event> {
    this.closing = false;
    return this.open();
  }

  private open(): Promise<Event> {
    return new Promise((resolve, reject) => {
      // ?resume= lets a load balancer route the reconnect to the gateway copy that owns the session
      const url = new URL(this.opts.url);
      const resume = this.sessionId ?? this.opts.sessionId;
      if (resume) url.searchParams.set("resume", resume);
      const ws = new WebSocket(url.toString());
      ws.binaryType = "arraybuffer";
      this.ws = ws;
      let welcomed = false;
      ws.onopen = () => this.send({
        type: "hello", version: 1, token: this.token, mic: { rate: 16000, frame_ms: 20 }, playout: { rate: 24000 },
        ...(this.sessionId ?? this.opts.sessionId
          ? { session_id: this.sessionId ?? this.opts.sessionId, resume_key: this.resumeKey ?? this.opts.resumeKey }
          : {}),
      });
      ws.onerror = () => reject(new Error("websocket error"));
      ws.onclose = (c) => {
        clearInterval(this.pinger);
        if (!welcomed) {
          reject(Object.assign(new Error(`closed ${c.code} ${c.reason}`), { code: c.code }));
          if (!this.reconnecting) this.ended(c.code);
        } else if (this.closing || NO_RETRY.has(c.code)) {
          this.ended(c.code);
        } else {
          void this.reconnect(c.code);
        }
      };
      ws.onmessage = (m: MessageEvent<string | ArrayBuffer>) => {
        if (typeof m.data !== "string") {
          const f = decodeFrame(new Uint8Array(m.data));
          this.playout?.push(f.generation_id, f.sequence, f.payload, (f.flags & FLAG_END_OF_STREAM) !== 0);
          return this.onAgentFrame(f);
        }
        const e = decodeEvent(m.data);
        if (e.type === "agent.cancel") this.playout?.cancel(e.gen as number);
        if (e.type === "welcome") {
          welcomed = true;
          this.sessionId = e.session_id as string;
          this.resumeKey = e.resume_key as string;
          this.pinger = setInterval(() => this.send({ type: "ping", t_client_us: Math.round(this.nowUs()) }), 2000);
          resolve(e);
        } else if (e.type === "pong") {
          const t = this.nowUs();
          this.offsetUs = (e.t_server_us as number) - ((e.t_client_us as number) + t) / 2;
        }
        this.onEvent(e);
      };
    });
  }

  send(e: Event): void {
    if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(encodeEvent(e));
  }

  sendFrame(f: FrameInit): void {
    if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(encodeFrame(f));
  }

  /** Starts the microphone (asks for consent). Frames flow only after this resolves. */
  async startMic(): Promise<void> {
    const stream_id = (this.streamId = (this.streamId + 1) >>> 0);
    this.stopCapture = await (this.opts.startMic ?? startCapture)((f) =>
      this.sendFrame({ kind: KIND_MIC, flags: 0, stream_id, sequence: f.sequence, capture_us: f.capture_us, generation_id: 0, payload: f.samples }),
    this.nowUs);
  }

  stopMic(): void {
    this.stopCapture?.();
    this.stopCapture = undefined;
    this.send({ type: "mic.revoked" });
  }

  close(): void {
    this.closing = true;
    this.run++;
    this.stop();
    this.ws?.close(1000);
  }

  /** The mic keeps capturing across the gap; frames sent while the socket is down are dropped. */
  private async reconnect(code: number): Promise<void> {
    const run = this.run;
    const gone = () => this.closing || run !== this.run;
    this.reconnecting = true;
    this.onEvent({ type: "socket.reconnecting", code });
    try {
      const delays = this.opts.retryDelaysMs ?? RETRY_DELAYS_MS;
      for (const [i, ms] of delays.entries()) {
        await new Promise((r) => setTimeout(r, ms));
        if (gone()) return;
        try {
          await this.open();
          return;
        } catch (e) {
          const last = i === delays.length - 1; // a fresh token nobody would use costs a token and maybe a human check
          if ((e as { code?: number }).code === 4001 && this.opts.getToken && !last) {
            this.token = await this.opts.getToken().catch(() => this.token);
            if (gone()) return;
          }
        }
      }
      this.ended(code);
    } finally {
      this.reconnecting = false;
    }
  }

  private ended(code: number): void {
    this.stop();
    this.onEvent({ type: "socket.closed", code });
  }

  private stop(): void {
    clearInterval(this.pinger);
    this.stopCapture?.();
    this.stopCapture = undefined;
  }
}
