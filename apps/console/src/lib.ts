// Pure helpers the pages share (unit-tested in lib.test.ts).

export type Build = { status: "queued" | "running" | "done" | "failed"; done: number; total: number; version: string | null; log: string };

export function parseHash(hash: string): { path: string[]; query: Record<string, string> } {
  const [path = "", q = ""] = hash.replace(/^#\/?/, "").split("?");
  return { path: path.split("/").filter(Boolean), query: Object.fromEntries(new URLSearchParams(q)) };
}

export function agentStatus(a: { enabled: boolean; live_version: string | null; build: string | null }): string {
  if (!a.enabled) return "Off";
  if (a.build === "queued" || a.build === "running") return "Building";
  if (a.live_version) return "Live";
  return a.build === "failed" ? "Failed" : "Draft";
}

export function buildLine(b: Build | null): string {
  if (!b) return "Not published yet.";
  if (b.status === "queued") return "Waiting to build…";
  if (b.status === "running") return b.total ? `Embedding ${b.done} of ${b.total} sections` : "Reading your docs…";
  if (b.status === "failed") return `Publish failed: ${b.log}`;
  const summary = b.log.split("\n")[0];
  return `Live: version ${b.version}. ${summary.charAt(0).toUpperCase()}${summary.slice(1)}.`;
}
