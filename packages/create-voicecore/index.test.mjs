import { mkdtempSync, readFileSync, statSync, writeFileSync, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { spawnSync } from "node:child_process";
import { describe, expect, it } from "vitest";
import { checkDocker, main, parseEnv, renderEnv, VERSION } from "./index.mjs";

// A fake Docker: records every call, answers like a healthy Docker 28 with Compose 2.40 unless told otherwise.
function fakeDocker({ missing = false, down = false, compose = "2.40.0" } = {}) {
  const calls = [];
  const run = (cmd, args, opts = {}) => {
    calls.push([cmd, ...args].join(" ") + (opts.cwd ? `  (in ${opts.cwd.split("/").pop()})` : ""));
    if (missing) return { status: null, error: Object.assign(new Error("spawn docker ENOENT"), { code: "ENOENT" }), stdout: "", stderr: "" };
    if (args[0] === "info") return { status: down ? 1 : 0, stdout: "", stderr: down ? "Cannot connect to the Docker daemon" : "" };
    if (args[0] === "compose" && args[1] === "version") return { status: 0, stdout: `${compose}\n`, stderr: "" };
    return { status: 0, stdout: "", stderr: "" };
  };
  return { run, calls };
}

function deps(over = {}) {
  const out = [];
  return { out, log: (s) => out.push(s), prompt: async () => "", isPortFree: async () => true, env: {}, voiceOn: async () => null, ...fakeDocker(), ...over };
}

const dir = () => mkdtempSync(join(tmpdir(), "voicecore-"));
const composeCall = (c) => c.startsWith("docker compose") && !c.startsWith("docker compose version");

describe("checkDocker", () => {
  it("names what is missing and where to get it", () => {
    expect(checkDocker(fakeDocker({ missing: true }).run)).toBe("Docker is not installed. Get it at https://docs.docker.com/get-docker/");
    expect(checkDocker(fakeDocker({ down: true }).run)).toBe("Docker is installed but not running. Start Docker Desktop and run this again.");
    expect(checkDocker(fakeDocker({ compose: "2.19.0" }).run)).toBe("Docker Compose 2.20 or newer is needed (found 2.19.0).");
    expect(checkDocker(fakeDocker().run)).toBeNull();
  });
});

describe("renderEnv", () => {
  it("writes fresh secrets, and voice follows the keys", () => {
    const env = parseEnv(renderEnv({}));
    expect(env.PROVIDERS).toBe("auto");
    expect(env.GATEWAY_SECRET).toMatch(/^[0-9a-f]{64}$/);
    expect(env.CONSOLE_ADMIN_PASSWORD).toMatch(/^[A-Za-z0-9_-]{20}$/);
    expect(env.VOICECORE_VERSION).toBe(VERSION);
    expect(env.PUBLIC_VOICE_URL).toBe("http://localhost:8080");
  });

  it("public mode serves one https host and needs no open voice port", () => {
    const env = parseEnv(renderEnv({ domain: "voice.acme.com", site: "docs.acme.com", humanCheck: "off" }));
    expect([env.PUBLIC_VOICE_URL, env.PUBLIC_CONSOLE_URL, env.HOSTS, env.GATEWAY_ENV, env.HUMAN_CHECK])
      .toEqual(["https://voice.acme.com", "https://voice.acme.com", "voice.acme.com", "prod", "off"]);
    expect(env.ORIGINS).toBe("voice.acme.com,docs.acme.com");
  });
});

describe("install", () => {
  it("--yes writes a private .env and starts the stack", async () => {
    const d = deps();
    const target = join(dir(), "voicecore");
    expect(await main(["--yes", "--dir", target], d)).toBe(0);
    expect(statSync(join(target, ".env")).mode & 0o777).toBe(0o600);
    expect(existsSync(join(target, "compose.yml"))).toBe(true);
    expect(readFileSync(join(target, ".gitignore"), "utf8")).toContain(".env\n"); // installed inside a repo, the secrets stay out of it
    expect(d.calls).toContain("docker compose up -d --wait  (in voicecore)");
    const env = parseEnv(readFileSync(join(target, ".env"), "utf8"));
    const said = d.out.join("\n");
    expect(said).toContain("Dashboard  http://localhost:8000");
    expect(said).toContain(`Password   ${env.CONSOLE_ADMIN_PASSWORD}`);
    expect(said).toContain("Voice      off: add your Deepgram and OpenRouter keys on the dashboard's Voice page");
  });

  it("is live by default, with the keys from the environment", async () => {
    const d = deps({ env: { DEEPGRAM_API_KEY: "dg-env", OPENROUTER_API_KEY: "or-env" } });
    const target = join(dir(), "v");
    expect(await main(["--yes", "--dir", target], d)).toBe(0);
    const env = parseEnv(readFileSync(join(target, ".env"), "utf8"));
    expect([env.PROVIDERS, env.DEEPGRAM_API_KEY, env.OPENROUTER_API_KEY]).toEqual(["auto", "dg-env", "or-env"]);
    expect(d.out.join("\n")).toContain("Voice      on");
  });

  it("asks one question: where it runs (keys and websites are set in the dashboard)", async () => {
    const asked = [];
    const d = deps({ prompt: async (q, fallback = "") => (asked.push(q), fallback) });
    const target = join(dir(), "v");
    expect(await main(["--dir", target], d)).toBe(0);
    expect(asked).toEqual(["Public domain for VoiceCore, e.g. voice.example.com (Enter: this machine only):"]);
    expect(parseEnv(readFileSync(join(target, ".env"), "utf8")).HOSTS).toBe("localhost,127.0.0.1,::1");
  });

  it("info shows the dashboard and password again, without Docker", async () => {
    const target = join(dir(), "v");
    await main(["--yes", "--dir", target], deps());
    const env = parseEnv(readFileSync(join(target, ".env"), "utf8"));
    const d = deps(fakeDocker({ missing: true }));
    d.out = []; d.log = (s) => d.out.push(s);
    expect(await main(["info", "--dir", target], d)).toBe(0);
    expect(d.out.join("\n")).toContain(`Password   ${env.CONSOLE_ADMIN_PASSWORD}`);
  });

  it("stops with Docker's problem and exit code 1", async () => {
    const d = deps(fakeDocker({ missing: true }));
    d.out = []; d.log = (s) => d.out.push(s);
    expect(await main(["--yes", "--dir", join(dir(), "v")], d)).toBe(1);
    expect(d.out.join("\n")).toContain("Docker is not installed. Get it at https://docs.docker.com/get-docker/");
  });

  it("takes the next free port when 8080 is busy", async () => {
    const d = deps({ isPortFree: async (p) => p !== 8080 });
    const target = join(dir(), "v");
    await main(["--yes", "--dir", target], d);
    expect(parseEnv(readFileSync(join(target, ".env"), "utf8")).VOICE_PORT).toBe("8081");
  });

  it("a second run in the same folder keeps the secrets", async () => {
    const target = join(dir(), "v");
    await main(["--yes", "--dir", target], deps());
    const first = parseEnv(readFileSync(join(target, ".env"), "utf8"));
    await main(["--yes", "--dir", target], deps());
    const second = parseEnv(readFileSync(join(target, ".env"), "utf8"));
    expect([second.GATEWAY_SECRET, second.CONSOLE_ADMIN_PASSWORD]).toEqual([first.GATEWAY_SECRET, first.CONSOLE_ADMIN_PASSWORD]);
  });
});

describe("upgrade, keys, uninstall", () => {
  it("upgrade changes only the version and pulls before starting", async () => {
    const target = join(dir(), "v");
    await main(["--yes", "--dir", target], deps());
    const before = parseEnv(readFileSync(join(target, ".env"), "utf8"));
    const d = deps();
    expect(await main(["upgrade", "--dir", target, "--image-tag", "0.2.0"], d)).toBe(0);
    const after = parseEnv(readFileSync(join(target, ".env"), "utf8"));
    expect(after).toEqual({ ...before, VOICECORE_VERSION: "0.2.0" });
    expect(d.calls.filter(composeCall)).toEqual(["docker compose pull  (in v)", "docker compose up -d --wait  (in v)"]);
  });

  it("upgrade moves an older install to voice that follows the dashboard's keys", async () => {
    const target = join(dir(), "v");
    await main(["--yes", "--dir", target], deps());
    const file = join(target, ".env");
    writeFileSync(file, readFileSync(file, "utf8").replace("PROVIDERS=auto", "PROVIDERS=free"));
    await main(["upgrade", "--dir", target], deps());
    expect(parseEnv(readFileSync(file, "utf8")).PROVIDERS).toBe("auto");
  });

  it("uninstall keeps the data unless asked", async () => {
    const target = join(dir(), "v");
    await main(["--yes", "--dir", target], deps());
    const keep = deps();
    await main(["uninstall", "--dir", target], keep);
    expect(keep.calls.filter(composeCall)).toEqual(["docker compose down  (in v)"]);
    const wipe = deps();
    await main(["uninstall", "--dir", target, "--delete-data"], wipe);
    expect(wipe.calls.filter(composeCall)).toEqual(["docker compose down -v  (in v)"]);
  });
});

const hasDocker = spawnSync("docker", ["compose", "version"]).status === 0;
describe.skipIf(!hasDocker)("the compose template (needs Docker)", () => {
  it("is valid with and without the public profile", () => {
    const d = dir();
    writeFileSync(join(d, ".env"), renderEnv({ domain: "voice.acme.com", humanCheck: "off" }));
    const base = ["compose", "-f", new URL("./template/compose.yml", import.meta.url).pathname, "--env-file", join(d, ".env")];
    expect(spawnSync("docker", [...base, "config", "--quiet"]).status).toBe(0);
    expect(spawnSync("docker", [...base, "--profile", "public", "config", "--quiet"]).status).toBe(0);
  });
});
