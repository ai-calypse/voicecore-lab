// Audio frame codec. Layout and rules: ../SPEC.md section 1.
export const HEADER_BYTES = 28;
export const KIND_MIC = 1;
export const KIND_AGENT = 2;
export const FLAG_END_OF_STREAM = 1;

export type Frame = {
  version: number; kind: number; flags: number; stream_id: number; sequence: number;
  capture_us: bigint; generation_id: number; samples: number; payload: Int16Array;
};

export class FrameError extends Error {
  readonly reason: "short" | "version" | "kind" | "length";
  constructor(reason: FrameError["reason"]) {
    super(`invalid frame: ${reason}`);
    this.reason = reason;
  }
}

export function decodeFrame(buf: Uint8Array): Frame {
  if (buf.length < HEADER_BYTES) throw new FrameError("short");
  const v = new DataView(buf.buffer, buf.byteOffset, buf.byteLength);
  const version = v.getUint8(0);
  if (version !== 1) throw new FrameError("version");
  const kind = v.getUint8(1);
  if (kind !== KIND_MIC && kind !== KIND_AGENT) throw new FrameError("kind");
  const samples = v.getUint16(24);
  if (buf.length - HEADER_BYTES !== samples * 2) throw new FrameError("length");
  const payload = new Int16Array(samples);
  for (let i = 0; i < samples; i++) payload[i] = v.getInt16(HEADER_BYTES + 2 * i, true);
  return {
    version, kind, flags: v.getUint16(2), stream_id: v.getUint32(4), sequence: v.getUint32(8),
    capture_us: v.getBigUint64(12), generation_id: v.getUint32(20), samples, payload,
  };
}

export function encodeFrame(f: Omit<Frame, "version" | "samples">): Uint8Array {
  const buf = new Uint8Array(HEADER_BYTES + f.payload.length * 2);
  const v = new DataView(buf.buffer);
  v.setUint8(0, 1);
  v.setUint8(1, f.kind);
  v.setUint16(2, f.flags);
  v.setUint32(4, f.stream_id);
  v.setUint32(8, f.sequence);
  v.setBigUint64(12, f.capture_us);
  v.setUint32(20, f.generation_id);
  v.setUint16(24, f.payload.length);
  for (let i = 0; i < f.payload.length; i++) v.setInt16(HEADER_BYTES + 2 * i, f.payload[i]!, true);
  return buf;
}
