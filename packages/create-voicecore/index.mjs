#!/usr/bin/env node
// create-voicecore: install VoiceCore with Docker in one command (Step 10, ADR 0005). No dependencies.
//
//   npx create-voicecore                 install (one question: a public domain, auto, or this machine; --yes: this machine)
//   npx create-voicecore --domain auto   a server's own address, https://<its IP>, with no domain or DNS needed
//   npx create-voicecore info            the dashboard's address and password again
//   npx create-voicecore@latest upgrade  newer images, same settings and data
//   npx create-voicecore uninstall       stop it (--delete-data also removes agents, docs and the spend ledger)
// Provider keys, spending limits and allowed websites are set in the dashboard; voice turns on once both keys are there.
import { spawnSync } from "node:child_process";
import { randomBytes } from "node:crypto";
import { chmodSync, copyFileSync, existsSync, mkdirSync, readFileSync, realpathSync, writeFileSync } from "node:fs";
import { createServer } from "node:net";
import { resolve } from "node:path";
import { createInterface } from "node:readline/promises";
import { fileURLToPath } from "node:url";
import { parseArgs } from "node:util";

export const VERSION = "0.3.1"; // the image tag this installer writes; they are released together
const TEMPLATE = fileURLToPath(new URL("./template/", import.meta.url));
const LOCAL_ORIGINS = "localhost:*,127.0.0.1:*";
const IPV4 = /^\d{1,3}(\.\d{1,3}){3}$/;
const DOCKER_PROXY_RANGES = "172.16.0.0/12,192.168.0.0/16,10.0.0.0/8"; // Caddy reaches the gateway over the compose network

const OPTIONS = {
  yes: { type: "boolean", short: "y" }, dir: { type: "string" }, site: { type: "string" },
  domain: { type: "string" }, deepgram: { type: "string" }, openrouter: { type: "string" },
  "turnstile-sitekey": { type: "string" }, "turnstile-secret": { type: "string" }, "human-check": { type: "string" },
  "image-tag": { type: "string" }, "delete-data": { type: "boolean" }, help: { type: "boolean", short: "h" },
};

// --- pure helpers (exported for the tests) ------------------------------------------------------

export function parseEnv(text) {
  const env = {};
  for (const line of text.split("\n")) {
    const m = line.match(/^([A-Z0-9_]+)=(.*)$/);
    if (m) env[m[1]] = m[2];
  }
  return env;
}

const hex = (bytes) => randomBytes(bytes).toString("hex");
const password = () => randomBytes(15).toString("base64url"); // 20 characters: printed once, kept in .env

export function renderEnv(o, existing = {}) {
  const host = (o.domain ?? "").toLowerCase();
  const pub = Boolean(host);
  const voicePort = o.voicePort ?? 8080;
  const consolePort = o.consolePort ?? 8000;
  const site = (o.site ?? "").trim().toLowerCase().replace(/\/+$/, "");
  const env = {
    VOICECORE_VERSION: o.version ?? existing.VOICECORE_VERSION ?? VERSION,
    PROVIDERS: "auto", // voice once both keys are set, in the dashboard or below; text answers until then
    BIND: "127.0.0.1",
    VOICE_PORT: String(voicePort),
    CONSOLE_PORT: String(consolePort),
    DOMAIN: host,
    PUBLIC_VOICE_URL: pub ? `https://${host}` : `http://localhost:${voicePort}`,
    PUBLIC_CONSOLE_URL: pub ? `https://${host}` : `http://localhost:${consolePort}`,
    ORIGINS: [pub ? host : LOCAL_ORIGINS, site].filter(Boolean).join(","),
    HOSTS: pub ? host : "localhost,127.0.0.1,::1",
    ACME_PROFILE: IPV4.test(host) ? "shortlived" : "classic", // Let's Encrypt certifies an IP address for 6 days at a time
    GATEWAY_ENV: pub ? "prod" : "dev",
    TRUSTED_PROXIES: pub ? DOCKER_PROXY_RANGES : "",
    HUMAN_CHECK: o.humanCheck ?? "on",
    TURNSTILE_SITEKEY: o.turnstileSitekey ?? existing.TURNSTILE_SITEKEY ?? "",
    TURNSTILE_SECRET: o.turnstileSecret ?? existing.TURNSTILE_SECRET ?? "",
    DEEPGRAM_API_KEY: o.deepgram ?? existing.DEEPGRAM_API_KEY ?? "",
    OPENROUTER_API_KEY: o.openrouter ?? existing.OPENROUTER_API_KEY ?? "",
    VOICECORE_CAP_USD: existing.VOICECORE_CAP_USD ?? "10", // starting limits; the dashboard's Voice page changes them
    VOICECORE_PUBLIC_TOTAL: existing.VOICECORE_PUBLIC_TOTAL ?? "10",
    VOICECORE_PUBLIC_DAILY: existing.VOICECORE_PUBLIC_DAILY ?? "1",
    GATEWAY_SECRET: existing.GATEWAY_SECRET || hex(32), // a second run keeps the secrets
    CONSOLE_ADMIN_PASSWORD: existing.CONSOLE_ADMIN_PASSWORD || password(), // the console takes it at start: no setup link
  };
  return writeEnv(env);
}

function writeEnv(env) {
  return [
    `# VoiceCore settings, written by create-voicecore ${VERSION}. This file holds secrets: keep it private.`,
    "# Spend caps are in US dollars; voice stops (text keeps working) when one is reached. Limits set on the",
    "# dashboard's Voice page take their place.",
    ...Object.entries(env).map(([k, v]) => `${k}=${v}`), "",
  ].join("\n");
}

export function checkDocker(run) {
  const v = run("docker", ["--version"]);
  if (v.error?.code === "ENOENT" || v.status === null) return "Docker is not installed. Get it at https://docs.docker.com/get-docker/";
  if (run("docker", ["info"]).status !== 0) return "Docker is installed but not running. Start Docker Desktop and run this again.";
  const c = run("docker", ["compose", "version", "--short"]);
  const found = (c.stdout ?? "").trim().replace(/^v/, "");
  const [major, minor] = found.split(".").map(Number);
  if (c.status !== 0 || !found) return "Docker Compose is missing. Get it at https://docs.docker.com/compose/install/";
  if (major < 2 || (major === 2 && minor < 20)) return `Docker Compose 2.20 or newer is needed (found ${found}).`;
  return null;
}

// --- the real edges ----------------------------------------------------------------------------

const realDeps = {
  log: (s) => console.log(s),
  env: process.env,
  publicIp: async () => { // the address the internet sees this server at (behind a cloud's NAT too)
    try {
      return (await (await fetch("https://api.ipify.org", { signal: AbortSignal.timeout(5000) })).text()).trim();
    } catch {
      return "";
    }
  },
  reachable: async (url, seconds) => { // https answers once Caddy has its certificate, usually within a minute
    for (const end = Date.now() + seconds * 1000; Date.now() < end; await new Promise((r) => setTimeout(r, 3000))) {
      try {
        if ((await fetch(url, { signal: AbortSignal.timeout(5000) })).ok) return true;
      } catch { /* not yet */ }
    }
    return false;
  },
  voiceOn: async (consoleUrl) => { // the dashboard's public status: keys may have been added there, not in .env
    try {
      return (await (await fetch(`${consoleUrl}/api/status`, { signal: AbortSignal.timeout(3000) })).json()).providers === "live";
    } catch {
      return null;
    }
  },
  run: (cmd, args, opts = {}) => spawnSync(cmd, args, { encoding: "utf8", stdio: opts.inherit ? "inherit" : "pipe", cwd: opts.cwd }),
  isPortFree: (port) => new Promise((done) => {
    const s = createServer().once("error", () => done(false)).once("listening", () => s.close(() => done(true)));
    s.listen(port, "127.0.0.1");
  }),
  prompt: async (question, fallback = "") => {
    const rl = createInterface({ input: process.stdin, output: process.stdout });
    const answer = (await rl.question(`${question}${fallback ? ` (${fallback})` : ""} `)).trim();
    rl.close();
    return answer || fallback;
  },
};

async function freePort(start, isPortFree) {
  for (let p = start; p < start + 50; p++) if (await isPortFree(p)) return p;
  throw new Error(`no free port between ${start} and ${start + 49}`);
}

function compose(d, dir, args) {
  const r = d.run("docker", ["compose", ...args], { cwd: dir, inherit: true });
  if (r.status !== 0) throw new Error(`docker compose ${args.join(" ")} failed`);
}

function readSettings(dir) {
  const file = resolve(dir, ".env");
  if (!existsSync(file)) throw new Error(`no VoiceCore install in ${dir} (no .env): run create-voicecore there first`);
  return parseEnv(readFileSync(file, "utf8"));
}

function saveSettings(dir, text) {
  const file = resolve(dir, ".env");
  writeFileSync(file, text, { mode: 0o600 });
  chmodSync(file, 0o600); // also when the file already existed
}

function copyTemplate(dir) {
  for (const f of ["compose.yml", "Caddyfile"]) copyFileSync(resolve(TEMPLATE, f), resolve(dir, f));
  // installed inside a project's repository, the secrets in .env must never be committed
  if (!existsSync(resolve(dir, ".gitignore"))) writeFileSync(resolve(dir, ".gitignore"), ".env\n");
}

const profiles = (env) => (env.DOMAIN ? ["--profile", "public"] : []);

// --- commands ----------------------------------------------------------------------------------

async function install(o, d) {
  const dir = resolve(o.dir ?? "voicecore");
  const fresh = !existsSync(resolve(dir, ".env"));
  const existing = fresh ? {} : parseEnv(readFileSync(resolve(dir, ".env"), "utf8"));
  const ask = (q, fallback) => (o.yes ? Promise.resolve(fallback) : d.prompt(q, fallback));

  // Keys can also come in here (flags, or the environment) for a scripted install; they go to .env.
  const settings = { site: o.site, deepgram: o.deepgram || existing.DEEPGRAM_API_KEY || d.env.DEEPGRAM_API_KEY,
                     openrouter: o.openrouter || existing.OPENROUTER_API_KEY || d.env.OPENROUTER_API_KEY };
  settings.domain = o.domain ?? existing.DOMAIN ?? (await ask(
    "Public domain for VoiceCore, e.g. voice.example.com (auto: this server's own address; Enter: this machine only):", ""));
  if (settings.domain === "auto") {
    settings.domain = await d.publicIp();
    if (!IPV4.test(settings.domain)) throw new Error("couldn't find this server's public address: use --domain with your own domain");
  }
  const mode = settings.domain ? "public" : "local";
  if (mode === "public") {
    if (!/^[a-z0-9.-]+\.[a-z]{2,}$/i.test(settings.domain) && !IPV4.test(settings.domain)) throw new Error(`not a domain name: ${settings.domain}`);
    settings.turnstileSitekey = o["turnstile-sitekey"];
    settings.turnstileSecret = o["turnstile-secret"];
    settings.humanCheck = settings.turnstileSecret ? "on" : (o["human-check"] ?? "off");
  }
  settings.voicePort = existing.VOICE_PORT ? Number(existing.VOICE_PORT) : await freePort(8080, d.isPortFree);
  settings.consolePort = existing.CONSOLE_PORT ? Number(existing.CONSOLE_PORT) : await freePort(8000, d.isPortFree);
  settings.version = o["image-tag"];

  mkdirSync(dir, { recursive: true });
  const text = renderEnv(settings, existing);
  saveSettings(dir, text);
  copyTemplate(dir);
  const env = parseEnv(text);
  d.log(`Starting VoiceCore in ${dir} (first start downloads the images, a few hundred MB)…`);
  compose(d, dir, [...profiles(env), "up", "-d", "--wait"]);
  d.log("");
  d.log("VoiceCore is running.");
  if (mode === "public" && !(await d.reachable(`${env.PUBLIC_CONSOLE_URL}/api/status`, 120))) {
    d.log(`${env.PUBLIC_CONSOLE_URL} doesn't answer yet. Check that ports 80 and 443 are open in your server's firewall`
      + (IPV4.test(env.DOMAIN) ? "." : `, and that ${env.DOMAIN} points at this server.`) + " Then open it again in a minute.");
  }
  await summary(env, d);
  d.log("Next: in the dashboard, create an agent, add your docs and Publish. Its Embed tab has the one line for your site.");
  d.log("Show this again: npx create-voicecore info");
  if (mode === "public" && env.HUMAN_CHECK === "off") d.log("Note: no Turnstile human check. The rate limits and spend caps in .env still apply.");
  return 0;
}

async function summary(env, d) {
  const on = (await d.voiceOn(env.PUBLIC_CONSOLE_URL)) ?? Boolean(env.DEEPGRAM_API_KEY && env.OPENROUTER_API_KEY);
  d.log("");
  d.log(`  Dashboard  ${env.PUBLIC_CONSOLE_URL}`);
  d.log(`  Password   ${env.CONSOLE_ADMIN_PASSWORD ?? "(set in the console at first run)"}`);
  d.log(`  Voice      ${on ? "on" : "off: add your Deepgram and OpenRouter keys on the dashboard's Voice page"}`);
  d.log("");
}

async function info(o, d) {
  await summary(readSettings(resolve(o.dir ?? "voicecore")), d);
  return 0;
}

async function upgrade(o, d) {
  const dir = resolve(o.dir ?? "voicecore");
  const env = readSettings(dir);
  env.VOICECORE_VERSION = o["image-tag"] ?? VERSION;
  env.PROVIDERS = "auto"; // from 0.2.0 voice follows the keys, so the dashboard can set them
  saveSettings(dir, writeEnv(env));
  copyTemplate(dir);
  compose(d, dir, [...profiles(env), "pull"]);
  compose(d, dir, [...profiles(env), "up", "-d", "--wait"]); // the console migrates its database on start
  d.log(`VoiceCore is on ${env.VOICECORE_VERSION}. Your agents, docs and settings are unchanged.`);
  return 0;
}

async function uninstall(o, d) {
  const dir = resolve(o.dir ?? "voicecore");
  readSettings(dir);
  compose(d, dir, ["down", ...(o["delete-data"] ? ["-v"] : [])]);
  d.log(o["delete-data"] ? `Stopped, and the data is deleted. Remove ${dir} to finish.`
                         : `Stopped. Agents, docs and the spend ledger are kept; start again with: docker compose up -d (in ${dir})`);
  return 0;
}

const HELP = `Usage: npx create-voicecore [install|info|upgrade|uninstall] [options]
  --yes              ask nothing: this machine only, folder ./voicecore
  --dir <folder>     where the install lives (default ./voicecore)
  --domain <host>    public: VoiceCore on its own domain, with HTTPS by Caddy (its DNS must point at this machine)
  --domain auto      public, on this server's own address (https://<its IP>): no domain or DNS needed
  --site <host>      a website allowed to embed it (more in the dashboard)
  --deepgram <key>, --openrouter <key>   provider keys for a scripted install (default: DEEPGRAM_API_KEY and
                     OPENROUTER_API_KEY from the environment; otherwise add them in the dashboard)
  --turnstile-sitekey <k>, --turnstile-secret <s>   the human check (public)
  --image-tag <t>    a specific release (default ${VERSION})
  --delete-data      uninstall: also delete agents, docs and the spend ledger`;

export async function main(argv = process.argv.slice(2), d = realDeps) {
  let parsed;
  try {
    parsed = parseArgs({ args: argv, options: OPTIONS, allowPositionals: true });
  } catch (e) {
    d.log(e.message);
    return 2;
  }
  const { values: o, positionals } = parsed;
  if (o.help) return d.log(HELP), 0;
  const command = positionals[0] ?? "install";
  try {
    if (command === "info") return await info(o, d); // .env and the dashboard's status: no Docker needed
  } catch (e) {
    d.log(`create-voicecore: ${e.message}`);
    return 1;
  }
  const problem = checkDocker(d.run);
  if (problem) return d.log(problem), 1;
  try {
    if (command === "install") return await install(o, d);
    if (command === "upgrade") return await upgrade(o, d);
    if (command === "uninstall") return await uninstall(o, d);
    d.log(`Unknown command: ${command}\n\n${HELP}`);
    return 2;
  } catch (e) {
    d.log(`create-voicecore: ${e.message}`);
    return 1;
  }
}

// npx starts it through a node_modules/.bin link, so compare real paths, not names
if (process.argv[1] && realpathSync(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main().then((code) => process.exit(code));
}
