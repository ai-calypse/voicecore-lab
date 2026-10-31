import { describe, expect, it } from "vitest";
import { agentStatus, buildLine, parseHash } from "./lib.ts";

describe("console helpers", () => {
  it("reads a hash route and its query", () => {
    expect(parseHash("#/agents/acme-docs/test")).toEqual({ path: ["agents", "acme-docs", "test"], query: {} });
    expect(parseHash("#/setup?token=abc")).toEqual({ path: ["setup"], query: { token: "abc" } });
    expect(parseHash("")).toEqual({ path: [], query: {} });
  });

  it("names an agent's state the way the list shows it", () => {
    expect(agentStatus({ enabled: true, live_version: null, build: null })).toBe("Draft");
    expect(agentStatus({ enabled: true, live_version: "e72764ddb031", build: "done" })).toBe("Live");
    expect(agentStatus({ enabled: true, live_version: null, build: "running" })).toBe("Building");
    expect(agentStatus({ enabled: true, live_version: null, build: "failed" })).toBe("Failed");
    expect(agentStatus({ enabled: false, live_version: null, build: "done" })).toBe("Off");
  });

  it("says what a build is doing", () => {
    expect(buildLine(null)).toBe("Not published yet.");
    expect(buildLine({ status: "queued", done: 0, total: 0, version: null, log: "" })).toBe("Waiting to build…");
    expect(buildLine({ status: "running", done: 120, total: 342, version: null, log: "" })).toBe("Embedding 120 of 342 sections");
    expect(buildLine({ status: "done", done: 3, total: 3, version: "e72764ddb031", log: "3 sections from 2 pages\npublished version e72764ddb031" }))
      .toBe("Live: version e72764ddb031. 3 sections from 2 pages.");
    expect(buildLine({ status: "failed", done: 0, total: 0, version: null, log: "no docs yet: add a file" })).toBe("Publish failed: no docs yet: add a file");
  });
});
