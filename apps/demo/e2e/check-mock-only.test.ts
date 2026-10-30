import { afterEach, describe, expect, it, vi } from "vitest";
import { checkMockOnly } from "./check-mock-only.ts";

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

  it("treats a non-JSON or error answer as no orchestrator, and never waits forever", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("Upgrade Required", { status: 426 })));
    await expect(checkMockOnly("http://127.0.0.1:18766")).rejects.toThrow("no orchestrator at http://127.0.0.1:18766 (HTTP 426)");
    const seen: (AbortSignal | undefined)[] = [];
    vi.stubGlobal("fetch", vi.fn(async (_u: string, init?: RequestInit) => { seen.push(init?.signal ?? undefined); return new Response("{}"); }));
    await checkMockOnly("http://127.0.0.1:18766").catch(() => {});
    expect(seen[0]).toBeInstanceOf(AbortSignal);
  });

  it("says when nothing answers", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw new TypeError("fetch failed"); }));
    await expect(checkMockOnly("http://127.0.0.1:18766")).rejects.toThrow("no orchestrator at http://127.0.0.1:18766");
  });
});
