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
  return summary.charAt(0).toUpperCase() + summary.slice(1);
}

export function agentSummary(a: { sources: number; summary: string | null }): string {
  if (a.summary) return a.summary;
  if (!a.sources) return "No docs yet";
  return `${a.sources} ${a.sources === 1 ? "source" : "sources"}, not published`;
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

export function ago(ts: number, now = Date.now() / 1000): string {
  const s = now - ts;
  const n = (v: number, unit: string) => `${v} ${unit}${v === 1 ? "" : "s"} ago`;
  if (s < 60) return "just now";
  if (s < 3600) return n(Math.floor(s / 60), "minute");
  if (s < 86400) return n(Math.floor(s / 3600), "hour");
  if (s < 2 * 86400) return "yesterday";
  if (s < 8 * 86400) return n(Math.floor(s / 86400), "day");
  const d = new Date(ts * 1000);
  return `on ${d.getDate()} ${MONTHS[d.getMonth()]} ${d.getFullYear()}`;
}

export function greeting(hour: number): string {
  if (hour >= 5 && hour < 12) return "Good morning";
  if (hour >= 12 && hour < 18) return "Good afternoon";
  return "Good evening";
}
