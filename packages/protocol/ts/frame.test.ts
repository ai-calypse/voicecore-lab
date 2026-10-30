import { expect, test } from "vitest";
import vectors from "../vectors/frames.json" with { type: "json" };
import { decodeFrame, encodeFrame, FrameError } from "./frame.ts";

const bytes = (hex: string) => Uint8Array.from(hex.match(/../g) ?? [], (b) => parseInt(b, 16));

test("decodes every golden frame vector", () => {
  for (const v of vectors.valid) {
    const f = decodeFrame(bytes(v.hex));
    expect({ ...f, capture_us: String(f.capture_us), payload: Array.from(f.payload) }, v.name).toEqual(v.fields);
  }
});

test("encode(decode(bytes)) === bytes", () => {
  for (const v of vectors.valid) expect(encodeFrame(decodeFrame(bytes(v.hex))), v.name).toEqual(bytes(v.hex));
});

test("rejects short header, version 2, unknown kind and samples != payload/2", () => {
  for (const v of vectors.invalid) {
    expect(() => decodeFrame(bytes(v.hex)), v.name).toThrow(new FrameError(v.error as FrameError["reason"]));
  }
});
