"""The Fly image (deploy/fly), built and run locally (Step 09 Phase 11; marked docker: `make fly-image-test`).

Never deploys anything. Runs with mock providers in dev mode, plus one prod-mode start that must refuse.
"""
import json
import subprocess
import sys
import time
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
    name, volume = f"vc-fly-{uuid.uuid4().hex[:8]}", f"vc-fly-data-{uuid.uuid4().hex[:8]}"
    flags = [x for e in ("PROVIDERS=mock", "POOL=usd", *env) for x in ("-e", e)]
    docker("run", "-d", "--name", name, "-p", f"127.0.0.1:{port}:8080", "-v", f"{volume}:/data", *flags, image)
    return name


def remove(name):
    volume = json.loads(docker("inspect", name).stdout)[0]["Mounts"][0]["Name"]
    docker("rm", "-f", name, check=False)
    docker("volume", "rm", volume, check=False)


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
                "    if b'voicecore.server' in open(f'/proc/{p}/cmdline', 'rb').read(): os.kill(int(p), signal.SIGKILL)")
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
