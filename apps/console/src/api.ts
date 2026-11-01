// The console API (services/console). In the read-only demo build (VITE_DEMO=1) every read comes from the committed
// snapshots in demo/, generated through the real API by services/console/tests/test_demo_snapshot.py, and every
// change is refused with the same message the UI shows on its banner.
import type { Build } from "./lib.ts";

export type Status = { setup_needed: boolean; providers: string; voice_url: string };
export type Config = { name: string; docs_url: string; instructions: string; first_message: string | null; voice: string; llm: string; keyterms: string[] };
export type Source = { id: string; kind: string; label: string; ref: string | null; files: number; created: number };
export type Published = { version: string; log: string; finished: number };
export type Agent = { id: string; config: Config; enabled: boolean; live_version: string | null; sources: Source[]; build: (Build & { id: number }) | null;
  published: Published | null; snippet: string };
export type AgentRow = { id: string; name: string; enabled: boolean; live_version: string | null; build: string | null; sources: number;
  summary: string | null; published: number | null };
export type Catalog = { voices: Record<string, string>; llms: string[] };
export type Usage = { spent_usd: number | null; cap_usd: number | null; today_usd: number | null; daily_cap_usd: number | null };
export type Key = { id: string; label: string; created: number };

export const DEMO = import.meta.env.VITE_DEMO === "1";
export const DEMO_REFUSAL = "Read-only demo. Install it to try: npx create-voicecore";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

const snapshots = import.meta.glob<{ default: unknown }>("../demo/*.json", { eager: true });

function fromSnapshot<T>(path: string): T {
  const file = `../demo/${path.replace(/^\/api\//, "").replaceAll("/", "__") || "index"}.json`;
  if (!snapshots[file]) throw new ApiError(404, "not in the demo");
  return snapshots[file].default as T;
}

function detail(data: unknown, status: number): string {
  const d = (data as { detail?: unknown })?.detail;
  if (typeof d === "string") return d;
  if (Array.isArray(d)) return d.map((e: { loc?: string[]; msg?: string }) => `${e.loc?.at(-1) ?? "value"}: ${e.msg}`).join("; ");
  return `Request failed (${status})`;
}

async function call<T>(method: string, path: string, init: { json?: unknown; raw?: Blob } = {}): Promise<T> {
  if (DEMO) {
    if (method !== "GET") throw new ApiError(403, DEMO_REFUSAL);
    return fromSnapshot<T>(path);
  }
  const headers: Record<string, string> = {};
  if (init.json !== undefined) headers["Content-Type"] = "application/json";
  if (init.raw) headers["Content-Type"] = "application/octet-stream";
  const res = await fetch(path, { method, headers, credentials: "same-origin",
    body: init.json !== undefined ? JSON.stringify(init.json) : init.raw });
  if (res.status === 204) return undefined as T;
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new ApiError(res.status, detail(data, res.status));
  return data as T;
}

export const api = {
  status: () => call<Status>("GET", "/api/status"),
  me: () => call<{ admin: true }>("GET", "/api/me"),
  setup: (token: string, password: string) => call("POST", "/api/setup", { json: { token, password } }),
  login: (password: string) => call("POST", "/api/login", { json: { password } }),
  logout: () => call("POST", "/api/logout"),
  usage: () => call<Usage>("GET", "/api/usage"),
  catalog: () => call<Catalog>("GET", "/api/catalog"),
  agents: () => call<AgentRow[]>("GET", "/api/agents"),
  createAgent: (name: string) => call<{ id: string }>("POST", "/api/agents", { json: { name } }),
  agent: (id: string) => call<Agent>("GET", `/api/agents/${id}`),
  saveSettings: (id: string, config: Config) => call<{ config: Config }>("PUT", `/api/agents/${id}/settings`, { json: config }),
  upload: (id: string, file: File) => call<{ files: number; skipped: string[] }>("PUT", `/api/agents/${id}/sources/upload?name=${encodeURIComponent(file.name)}`, { raw: file }),
  paste: (id: string, title: string, text: string) => call("POST", `/api/agents/${id}/sources/text`, { json: { title, text } }),
  git: (id: string, url: string, folder: string, ref: string) => call<{ files: number; skipped: string[] }>("POST", `/api/agents/${id}/sources/git`, { json: { url, folder, ref } }),
  sync: (id: string, source: string) => call<{ files: number; skipped: string[] }>("POST", `/api/agents/${id}/sources/${source}/sync`),
  removeSource: (id: string, source: string) => call("DELETE", `/api/agents/${id}/sources/${source}`),
  publish: (id: string) => call<{ build: number }>("POST", `/api/agents/${id}/publish`),
  latestBuild: (id: string) => call<Build | { status: "none" }>("GET", `/api/agents/${id}/builds/latest`),
  setEnabled: (id: string, on: boolean) => call("POST", `/api/agents/${id}/${on ? "enable" : "disable"}`),
  site: () => call<{ origins: string[] }>("GET", "/api/site"),
  saveSite: (origins: string[]) => call<{ origins: string[] }>("PUT", "/api/site", { json: { origins } }),
  keys: () => call<Key[]>("GET", "/api/keys"),
  createKey: (label: string) => call<Key & { key: string }>("POST", "/api/keys", { json: { label } }),
  revokeKey: (id: string) => call("DELETE", `/api/keys/${id}`),
};
