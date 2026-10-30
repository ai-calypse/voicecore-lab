import { afterEach, describe, expect, it, vi } from "vitest";
import { checkMockOnly } from "./check-mock-only";

const answer = (body: unknown) => vi.fn(async () => new Response(JSON.stringify(body), { status: 200 }));

describe("checkMockOnly (e2e must never reach a live orchestrator)", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("refuses an orchestrator running live providers", async () => {
    vi.stubGlobal("fetch", answer({ status: "ok", providers: "live" }));
    await expect(checkMockOnly("http://127.0.0.1:18766")).rejects.toThrow("refusing to run e2e against live providers");
  });

  it("accepts mock and mock-billed", async () => {
    vi.stubGlobal("fetch", answer({ status: "ok", providers: "mock" }));
    await expect(checkMockOnly("http://127.0.0.1:18766")).resolves.toBeUndefined();
    vi.stubGlobal("fetch", answer({ status: "ok", providers: "mock-billed" }));
    await expect(checkMockOnly("http://127.0.0.1:18766")).resolves.toBeUndefined();
  });

  it("says when nothing answers", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw new TypeError("fetch failed"); }));
    await expect(checkMockOnly("http://127.0.0.1:18766")).rejects.toThrow("no orchestrator at http://127.0.0.1:18766");
  });
});
