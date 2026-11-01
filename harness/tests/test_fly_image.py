"""The Fly image (deploy/fly), built and run locally (Step 09 Phase 11; marked docker: `make fly-image-test`).

Never deploys anything. Runs with mock providers in dev mode, plus one prod-mode start that must refuse.
"""
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

import pytest
from websockets.sync.client import connect

ROOT = Path(__file__).resolve().parents[2]
IMAGE = "voicecore-fly:test"
PORT = 18300
pytestmark = pytest.mark.docker


def docker(*args, check=True) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", *args], capture_output=True, text=True, check=check)


@pytest.fixture(scope="module")
def image():
    docker("build", "-t", IMAGE, "-f", "deploy/fly/Dockerfile", str(ROOT))
    return IMAGE


def start(image, *env, port=PORT) -> str:
    name = f"vc-fly-{uuid.uuid4().hex[:8]}"
    flags = [x for e in ("PROVIDERS=mock", "POOL=usd", *env) for x in ("-e", e)]
    # a root-owned mount, as Fly's volumes are (a Docker named volume would copy the image's ownership and hide it)
    docker("run", "-d", "--name", name, "-p", f"127.0.0.1:{port}:8080", "--mount", "type=tmpfs,destination=/data,tmpfs-mode=0755", *flags, image)
    return name


def remove(name):
    docker("rm", "-f", name, check=False)


def wait_ready(name, port=PORT, timeout=120):
    end = time.time() + timeout
    while time.time() < end:
        try:
            if urllib.request.urlopen(f"http://127.0.0.1:{port}/readyz", timeout=2).status == 200:
                return
        except OSError:
            pass
        time.sleep(1)
    pytest.fail(f"not ready in {timeout} s:\n{docker('logs', name, check=False).stdout[-2000:]}")


@pytest.mark.timeout(600)
def test_dev_run_answers_and_sigterm_drains_then_exits_0(image):
    name = start(image, "VOICECORE_ENV=dev")
    try:
        wait_ready(name)
        assert docker("exec", name, "stat", "-c", "%U", "/data").stdout.strip() == "app"  # the entrypoint took the volume
        uids = ("import os\n"
                "for p in filter(str.isdigit, os.listdir('/proc')):\n"
                "    argv = open(f'/proc/{p}/cmdline', 'rb').read().split(b'\\0')\n"
                "    if b'gateway' in argv[0] or argv[1:3] == [b'-m', b'voicecore.server']:\n"
                "        print([l.split()[1] for l in open(f'/proc/{p}/status') if l.startswith('Uid:')][0])")
        assert set(docker("exec", name, "/app/.venv/bin/python", "-c", uids).stdout.split()) == {"10001"}  # never root
        smoke = subprocess.run([sys.executable, str(ROOT / "harness/smoke.py"), "--gateway", f"http://127.0.0.1:{PORT}"],
                               capture_output=True, text=True, timeout=60)
        assert smoke.returncode == 0, smoke.stdout + smoke.stderr
        token = json.loads(urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{PORT}/v1/session", method="POST")).read())["token"]
        with connect(f"ws://127.0.0.1:{PORT}/v1/ws") as ws:
            ws.send(json.dumps({"type": "hello", "version": 1, "token": token, "mic": {"rate": 16000, "frame_ms": 20}, "playout": {"rate": 24000}}))
            assert json.loads(ws.recv())["type"] == "welcome"
            t0 = time.time()
            docker("kill", "-s", "TERM", name)  # what Fly sends (kill_signal)
            ended = None
            while ended is None and time.time() - t0 < 45:  # the gateway drains up to 25 s, then ends the session
                ws.send(json.dumps({"type": "ping", "t_client_us": 1}))  # a live client pings every 2 s (heartbeat 10 s)
                try:
                    m = ws.recv(timeout=2)
                except TimeoutError:
                    continue
                if isinstance(m, str) and json.loads(m)["type"] == "session.ended":
                    ended = json.loads(m)["reason"]
        assert ended == "shutdown"
        assert docker("wait", name).stdout.strip() == "0" and time.time() - t0 < 45  # inside fly.toml's kill_timeout
    finally:
        remove(name)


@pytest.mark.timeout(300)
def test_a_dead_orchestrator_makes_the_machine_restart(image):
    name = start(image, "VOICECORE_ENV=dev", port=PORT + 1)
    try:
        wait_ready(name, port=PORT + 1)
        kill = ("import os, signal\n"
                "for p in filter(str.isdigit, os.listdir('/proc')):\n"
                "    argv = open(f'/proc/{p}/cmdline', 'rb').read().split(b'\\0')\n"
                "    if int(p) != os.getpid() and argv[1:3] == [b'-m', b'voicecore.server']: os.kill(int(p), signal.SIGKILL)")
        docker("exec", name, "/app/.venv/bin/python", "-c", kill, check=False)
        assert docker("wait", name).stdout.strip() not in ("0", "")  # non-zero: Fly restarts the machine
    finally:
        remove(name)


@pytest.mark.timeout(300)
def test_prod_without_its_settings_refuses_to_start(image):
    name = start(image, port=PORT + 2)  # VOICECORE_ENV=prod from the image's defaults; no secrets, no proxies
    try:
        assert docker("wait", name).stdout.strip() not in ("0", "")
        assert "refusing to start" in docker("logs", name, check=False).stdout + docker("logs", name, check=False).stderr
    finally:
        remove(name)


@pytest.mark.timeout(600)
def test_serves_the_widget_and_agents_from_the_volume(image):
    """The portfolio embed: /widget.js from the gateway, and agents published into AGENTS_DIR on the volume."""
    name = start(image, "VOICECORE_ENV=dev", "AGENTS_DIR=/data/agents", port=PORT + 3)
    base = f"http://127.0.0.1:{PORT + 3}"
    try:
        wait_ready(name, port=PORT + 3)
        widget = urllib.request.urlopen(f"{base}/widget.js")
        assert widget.status == 200 and b"data-voicecore" in widget.read()
        bundle = subprocess.run(["tar", "-C", str(ROOT / "fixtures/agents"), "-c", "acme-docs"], capture_output=True, check=True).stdout
        subprocess.run(["docker", "exec", "-i", name, "tar", "-x", "-C", "/data/agents"], input=bundle, check=True)  # as an upload would
        session = lambda agent: urllib.request.Request(f"{base}/v1/session", data=f"agent={agent}".encode(), method="POST")
        token = json.loads(urllib.request.urlopen(session("acme-docs")).read())["token"]
        assert token.split(".")[2] == "acme-docs"
        with pytest.raises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(session("nobody"))
        assert e.value.code == 404
    finally:
        remove(name)


@pytest.mark.timeout(600)
def test_dashboard_on_the_same_host_publishes_live(image):
    """CONSOLE_ADMIN_PASSWORD: the console runs behind the gateway, and an agent published there answers at once."""
    name = start(image, "VOICECORE_ENV=dev", "AGENTS_DIR=/data/agents", "CONSOLE_ADMIN_PASSWORD=correct horse battery", port=PORT + 4)
    base = f"http://127.0.0.1:{PORT + 4}"
    web = urllib.request.build_opener(urllib.request.HTTPCookieProcessor())

    def api(method, path, body=None):
        req = urllib.request.Request(f"{base}{path}", method=method, data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Content-Type": "application/json"})
        return json.loads(web.open(req).read() or "null")

    try:
        wait_ready(name, port=PORT + 4)
        assert b"<title>" in urllib.request.urlopen(f"{base}/").read()  # the console's page, from the gateway's port
        api("POST", "/api/login", {"password": "correct horse battery"})
        agent = api("POST", "/api/agents", {"name": "Acme Docs"})["id"]
        api("POST", f"/api/agents/{agent}/sources/text", {"title": "Refunds", "text": "Refunds take 5 days."})
        api("POST", f"/api/agents/{agent}/publish")
        end = time.time() + 120
        while (b := api("GET", f"/api/agents/{agent}/builds/latest"))["status"] not in ("done", "failed") and time.time() < end:
            time.sleep(0.5)
        assert b["status"] == "done", b
        session = urllib.request.Request(f"{base}/v1/session", data=f"agent={agent}".encode(), method="POST")
        assert json.loads(urllib.request.urlopen(session).read())["token"].split(".")[2] == agent
    finally:
        remove(name)
