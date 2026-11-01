import { describe, expect, it } from "vitest";
import { agentStatus, agentSummary, ago, buildLine, greeting, parseHash } from "./lib.ts";

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
      .toBe("3 sections from 2 pages");
    expect(buildLine({ status: "failed", done: 0, total: 0, version: null, log: "no docs yet: add a file" })).toBe("Publish failed: no docs yet: add a file");
  });

  it("says what an agent has, for the list", () => {
    expect(agentSummary({ sources: 0, summary: null })).toBe("No docs yet");
    expect(agentSummary({ sources: 1, summary: null })).toBe("1 source, not published");
    expect(agentSummary({ sources: 3, summary: null })).toBe("3 sources, not published");
    expect(agentSummary({ sources: 1, summary: "3 sections from 2 pages" })).toBe("3 sections from 2 pages");
  });

  it("says how long ago, in words", () => {
    const now = Date.UTC(2026, 9, 31, 12) / 1000;
    expect(ago(now - 20, now)).toBe("just now");
    expect(ago(now - 60, now)).toBe("1 minute ago");
    expect(ago(now - 240, now)).toBe("4 minutes ago");
    expect(ago(now - 3 * 3600, now)).toBe("3 hours ago");
    expect(ago(now - 30 * 3600, now)).toBe("yesterday");
    expect(ago(now - 5 * 86400, now)).toBe("5 days ago");
    expect(ago(now - 40 * 86400, now)).toBe("on 21 Sep 2026");
  });

  it("greets by the time of day", () => {
    expect(greeting(4)).toBe("Good evening");
    expect(greeting(9)).toBe("Good morning");
    expect(greeting(13)).toBe("Good afternoon");
    expect(greeting(19)).toBe("Good evening");
  });
});
