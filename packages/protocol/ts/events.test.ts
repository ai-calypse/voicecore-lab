import { expect, test } from "vitest";
import vectors from "../vectors/events.json" with { type: "json" };
import { decodeEvent, encodeEvent, REQUIRED } from "./events.ts";

test("every golden event vector round-trips", () => {
  for (const v of vectors.valid) expect(JSON.parse(encodeEvent(decodeEvent(JSON.stringify(v)))), v.type).toEqual(v);
});

test("rejects bad JSON, non-objects, missing or unknown type, missing fields", () => {
  for (const v of vectors.invalid) expect(() => decodeEvent(v.text), v.name).toThrow();
});

test("required-field table matches the spec vectors", () => {
  expect(REQUIRED).toEqual(vectors.required);
});
