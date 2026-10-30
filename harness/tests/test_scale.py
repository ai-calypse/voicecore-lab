"""Scale profile, end to end (marked docker: `make scale-test`, or the CI scale job).

Needs `docker compose --profile scale up -d --wait redis seed orch-1 orch-2 gw-1 gw-2 lb` first: two gateways and two
orchestrators behind nginx on 127.0.0.1:8090, one Redis ledger, mock providers that reserve and settle $0.0017 per
session. Metrics and Redis are read through `docker compose exec`. The tests run in file order: the last one stops orch-1.
"""
import asyncio
import json
import re
import subprocess
import urllib.request
from pathlib import Path

import pytest
from websockets.asyncio.client import connect

ROOT = Path(__file__).resolve().parents[2]
LB = "127.0.0.1:8090"
HELLO = {"type": "hello", "version": 1, "mic": {"rate": 16000, "frame_ms": 20}, "playout": {"rate": 24000}}
pytestmark = pytest.mark.docker


def compose(*args) -> str:
    return subprocess.run(["docker", "compose", "--profile", "scale", *args], cwd=ROOT, check=True, capture_output=True, text=True).stdout


def sessions_on(orch: str) -> float:
    py = "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:9464/metrics').read().decode())"
    body = compose("exec", "-T", orch, "/app/.venv/bin/python", "-c", py)
    return sum(float(v) for v in re.findall(r"^voicecore_sessions_total\{[^}]*\} ([0-9.e+]+)$", body, re.M))


def ledger_micro() -> int:
    return int(compose("exec", "-T", "redis", "redis-cli", "GET", "vc:budget:total:usd").strip() or 0)


def token() -> str:
    req = urllib.request.Request(f"http://{LB}/v1/session", method="POST")
    return json.loads(urllib.request.urlopen(req, timeout=5).read())["token"]


async def ask(question="how does eager endpointing work?") -> str:
    """One whole session: hello, a typed question, the answer, a normal close. Returns the answer, or the end reason."""
    async with connect(f"ws://{LB}/v1/ws") as ws:
        await ws.send(json.dumps({**HELLO, "token": token()}))
        await ws.send(json.dumps({"type": "text.input", "text": question}))
        async for m in ws:
            if isinstance(m, str):
                e = json.loads(m)
                if e["type"] == "agent.text":
                    return e["text"]
                if e["type"] == "session.ended":
                    return f"ended:{e['reason']}"
    return "closed"


@pytest.mark.timeout(300)
def test_sessions_spread_over_both_orchestrators_and_the_ledger_is_exact():
    before = {o: sessions_on(o) for o in ("orch-1", "orch-2")}
    spent = ledger_micro()

    async def forty():
        return await asyncio.gather(*(ask() for _ in range(40)))

    answers = asyncio.run(forty())
    assert all(a and not a.startswith(("ended:", "closed")) for a in answers), answers
    asyncio.run(asyncio.sleep(2))  # the last sessions settle as their sockets close
    split = {o: sessions_on(o) - before[o] for o in before}
    assert sum(split.values()) == 40 and all(12 <= n <= 28 for n in split.values()), split
    assert ledger_micro() - spent == 40 * 1700  # 40 sessions x (0.001 + 0.0005 + 0.0002) USD, in micro-dollars


@pytest.mark.timeout(120)
def test_a_dropped_client_resumes_on_the_gateway_that_owns_its_session():
    async def run():
        ws = await connect(f"ws://{LB}/v1/ws")
        await ws.send(json.dumps({**HELLO, "token": token()}))
        welcome = json.loads(await ws.recv())
        ws.transport.abort()  # the network dropped: no close frame
        await asyncio.sleep(1)
        async with connect(f"ws://{LB}/v1/ws?resume={welcome['session_id']}") as again:
            await again.send(json.dumps({**HELLO, "token": token(), "session_id": welcome["session_id"],
                                         "resume_key": welcome["resume_key"]}))
            return welcome, json.loads(await again.recv())

    first, second = asyncio.run(run())
    assert re.fullmatch(r"s-gw[12]-[0-9a-f]{16}", first["session_id"])
    assert (second["session_id"], second["resumed"]) == (first["session_id"], True)


@pytest.mark.timeout(300)
def test_stopping_one_orchestrator_loses_no_new_session():
    async def during_stop():
        stop = asyncio.create_task(asyncio.to_thread(compose, "stop", "-t", "30", "orch-1"))
        await asyncio.sleep(1)  # orch-1 is draining: it refuses new sessions with 503
        answers = await asyncio.gather(*(ask() for _ in range(10)))
        await stop
        return answers

    try:
        answers = asyncio.run(during_stop())
        assert all(not a.startswith(("ended:", "closed")) for a in answers), answers
    finally:
        compose("up", "-d", "--wait", "orch-1")
