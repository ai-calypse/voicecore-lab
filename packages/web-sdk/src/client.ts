import { decodeEvent, encodeEvent, type Event } from "@voicecore/protocol/events";
import { decodeFrame, encodeFrame, KIND_MIC, type Frame, type FrameInit } from "@voicecore/protocol/frame";
import { startCapture } from "./capture/index.ts";

export type ClientOptions = {
  url: string;
  token: string;
  sessionId?: string; // resume this session
  nowUs?: () => number;
  startMic?: typeof startCapture; // injectable for headless clients
};

/** One WebSocket session: hello/welcome, mic frames out, events and agent frames in, clock pings. */
export class VoiceClient {
  onEvent: (e: Event) => void = () => {};
  onAgentFrame: (f: Frame) => void = () => {};
  sessionId?: string;
  /** server clock minus client clock in us, from the last pong (NaN until the first one) */
  offsetUs = NaN;
  private ws?: WebSocket;
  private streamId = 0;
  private stopCapture?: () => void;
  private pinger?: ReturnType<typeof setInterval>;
  private readonly opts: ClientOptions;
  private readonly nowUs: () => number;

  constructor(opts: ClientOptions) {
    this.opts = opts;
    this.nowUs = opts.nowUs ?? (() => performance.now() * 1000);
  }

  connect(): Promise<Event> {
    return new Promise((resolve, reject) => {
      const ws = new WebSocket(this.opts.url);
      ws.binaryType = "arraybuffer";
      this.ws = ws;
      ws.onopen = () => this.send({
        type: "hello", version: 1, token: this.opts.token, mic: { rate: 16000, frame_ms: 20 }, playout: { rate: 24000 },
        ...(this.opts.sessionId ? { session_id: this.opts.sessionId } : {}),
      });
      ws.onerror = () => reject(new Error("websocket error"));
      ws.onclose = (c) => { this.stop(); reject(new Error(`closed ${c.code} ${c.reason}`)); this.onEvent({ type: "socket.closed", code: c.code }); };
      ws.onmessage = (m: MessageEvent<string | ArrayBuffer>) => {
        if (typeof m.data !== "string") return this.onAgentFrame(decodeFrame(new Uint8Array(m.data)));
        const e = decodeEvent(m.data);
        if (e.type === "welcome") {
          this.sessionId = e.session_id as string;
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
    const stream_id = ++this.streamId;
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
    this.stop();
    this.ws?.close(1000);
  }

  private stop(): void {
    clearInterval(this.pinger);
    this.stopCapture?.();
    this.stopCapture = undefined;
  }
}
