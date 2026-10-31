"""The ten-minute promise, measured (Step 10, seam 25): install with create-voicecore, set up the admin, create an
agent, upload the Acme docs, publish, ask a question through the gateway, then stop the console and ask again.

    uv run python harness/install_smoke.py --dir /tmp/vc-install [--image-tag 0.1.0] [--keep]

Free mode: no keys, no spend. Prints a JSON report; exit 1 if any step fails or the total passes --deadline.
"""
import argparse
import asyncio
import json
import subprocess
import sys
import time
import urllib.request
from http.cookiejar import CookieJar
from pathlib import Path

from websockets.asyncio.client import connect

ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "packages/create-voicecore/index.mjs"
ACME_ZIP = ROOT / "fixtures/docs/acme.zip"
ANSWER = "Closest section: Refunds > How refunds work."


def env_of(folder: Path) -> dict:
    return dict(line.split("=", 1) for line in (folder / ".env").read_text().splitlines() if "=" in line and not line.startswith("#"))


class Console:
    def __init__(self, base: str):
        self.base = base
        self.http = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))

    def call(self, method: str, path: str, body=None, raw: bytes | None = None, ctype="application/json"):
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        req = urllib.request.Request(self.base + path, data=data, method=method, headers={"Content-Type": ctype} if data else {})
        with self.http.open(req, timeout=30) as r:
            text = r.read()
            return json.loads(text) if text else None


async def ask(voice: str, agent: str, question: str) -> str:
    form = f"agent={agent}".encode()
    req = urllib.request.Request(voice + "/v1/session", data=form, method="POST", headers={"Content-Type": "application/x-www-form-urlencoded"})
    token = json.loads(urllib.request.urlopen(req, timeout=10).read())["token"]
    async with connect(voice.replace("http", "ws", 1) + "/v1/ws") as ws:
        await ws.send(json.dumps({"type": "hello", "version": 1, "token": token, "mic": {"rate": 16000, "frame_ms": 20}, "playout": {"rate": 24000}}))
        texts, asked = [], False
        async with asyncio.timeout(30):
            async for m in ws:
                if isinstance(m, bytes):
                    continue
                e = json.loads(m)
                if e["type"] == "welcome":
                    await ws.send(json.dumps({"type": "ping", "t_client_us": 0}))
                if e["type"] == "agent.text":
                    texts.append(e["text"])
                    if not asked:  # the free-mode greeting first, then the question
                        asked = True
                        await ws.send(json.dumps({"type": "text.input", "text": question}))
                    else:
                        return e["text"]
                if e["type"] == "session.ended":
                    return f"session ended: {e.get('reason')}"
    return ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", type=Path, required=True)
    ap.add_argument("--image-tag", default=None)
    ap.add_argument("--deadline", type=float, default=600)
    ap.add_argument("--keep", action="store_true", help="leave the install running")
    args = ap.parse_args()
    report, t0 = {"steps": {}}, time.monotonic()

    def step(name, since):
        report["steps"][name] = round(time.monotonic() - since, 1)
        return time.monotonic()

    t = time.monotonic()
    cmd = ["node", str(INSTALLER), "--yes", "--mode", "free", "--dir", str(args.dir)] + (["--image-tag", args.image_tag] if args.image_tag else [])
    out = subprocess.run(cmd, capture_output=True, text=True)
    if out.returncode != 0:
        print(out.stdout[-2000:], out.stderr[-2000:], file=sys.stderr)
        return 1
    t = step("install", t)
    env = env_of(args.dir)
    console = Console(env["PUBLIC_CONSOLE_URL"])
    try:
        console.call("POST", "/api/setup", {"token": env["CONSOLE_SETUP_TOKEN"], "password": "correct horse battery"})
        agent = console.call("POST", "/api/agents", {"name": "Acme Docs"})["id"]
        console.call("PUT", f"/api/agents/{agent}/sources/upload?name=acme.zip", raw=ACME_ZIP.read_bytes(), ctype="application/octet-stream")
        console.call("POST", f"/api/agents/{agent}/publish")
        while (b := console.call("GET", f"/api/agents/{agent}/builds/latest"))["status"] not in ("done", "failed"):
            time.sleep(0.5)
        report["build"] = {k: b[k] for k in ("status", "done", "total", "version")}
        t = step("setup_upload_publish", t)
        report["answer"] = asyncio.run(ask(env["PUBLIC_VOICE_URL"], agent, "how do refunds work"))
        t = step("first_answer", t)
        report["elapsed_s"] = round(time.monotonic() - t0, 1)
        subprocess.run(["docker", "compose", "stop", "console"], cwd=args.dir, capture_output=True, check=True)
        report["answer_with_console_stopped"] = asyncio.run(ask(env["PUBLIC_VOICE_URL"], agent, "how do refunds work"))
    finally:
        if not args.keep:
            subprocess.run(["node", str(INSTALLER), "uninstall", "--dir", str(args.dir), "--delete-data"], capture_output=True)
    print(json.dumps(report, indent=2))
    ok = (report.get("answer") == ANSWER and report.get("answer_with_console_stopped") == ANSWER
          and report.get("elapsed_s", 1e9) < args.deadline)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
