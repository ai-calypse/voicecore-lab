"""Orchestrator server wiring (Step 09). Process lifecycle tests (seam 14) join this file in Phase 2."""
import json

from voicecore import budget


def test_mock_billed_settles_literal_amounts():
    from voicecore.server import mock_billed_providers

    providers, settle = mock_billed_providers("s-1")
    assert {"stt", "llm", "tts", "tts_factory"} <= set(providers)
    assert budget.total("usd") == 0.0017  # reserved up front, like a live session
    for s in settle:
        s()
    entries = json.loads(budget.ledger_file().read_text())["entries"]
    assert sorted(e["amount"] for e in entries) == [0.0002, 0.0005, 0.001]
    assert {e["status"] for e in entries} == {"settled"}
    assert {e["label"] for e in entries} == {"mock-billed stt s-1", "mock-billed llm s-1", "mock-billed tts s-1"}


def test_mock_billed_refused_leaves_nothing_reserved(tmp_path, monkeypatch):
    import pytest

    from voicecore.server import mock_billed_providers

    path = tmp_path / "near_cap.json"
    path.write_text(json.dumps({"entries": [{"pool": "usd", "amount": 4.9988}]}))  # stt fits, llm does not
    monkeypatch.setenv("VOICECORE_LEDGER", str(path))
    with pytest.raises(budget.BudgetExceeded):
        mock_billed_providers("s-2")
    assert [e for e in json.loads(path.read_text())["entries"] if "label" in e] == []


# Phase 2 (seam 14): health, readiness, drain and shutdown on a real websockets server, mock providers

import asyncio  # noqa: E402
import os  # noqa: E402
import signal  # noqa: E402
import socket  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402
import urllib.error  # noqa: E402
import urllib.request  # noqa: E402
from contextlib import asynccontextmanager  # noqa: E402
from pathlib import Path  # noqa: E402

import pytest  # noqa: E402
from websockets.asyncio.client import connect  # noqa: E402
from websockets.asyncio.server import serve  # noqa: E402
from websockets.exceptions import InvalidStatus  # noqa: E402

from voicecore import protocol  # noqa: E402

DOCS_PAGE = "---\ntitle: Endpointing\n---\nDeciding when the user finished.\n\n## Eager endpointing\n\nIt ends a turn on a punctuated final.\n"


@pytest.fixture(scope="module")
def small_index(tmp_path_factory):
    from voicecore.answer.index import Index
    from voicecore.answer.ingest import docusaurus, ingest

    d = tmp_path_factory.mktemp("docs")
    (d / "endpointing.md").write_text(DOCS_PAGE)
    return Index(ingest(d, site=docusaurus("http://localhost:3000/")))


def http_get(url):
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


@asynccontextmanager
async def running(state, make_providers=None):
    from voicecore.server import handler_for, http_routes

    handler = handler_for("mock", None, state, make_providers=make_providers)
    async with serve(handler, "127.0.0.1", 0, process_request=http_routes(state)) as server:
        yield f"127.0.0.1:{server.sockets[0].getsockname()[1]}"


async def ask(ws, text="how does eager endpointing work?"):
    await ws.send(protocol.event("text.input", text=text))
    async for m in ws:
        if isinstance(m, str) and json.loads(m)["type"] == "agent.text":
            return json.loads(m)["text"]


async def test_healthz_returns_ok_and_mode():
    from voicecore.server import AppState

    state = AppState(providers="mock")  # not ready yet: liveness still answers
    async with running(state) as addr:
        assert await asyncio.to_thread(http_get, f"http://{addr}/healthz") == (200, {"status": "ok", "providers": "mock", "version": "dev"})


async def test_readyz_503_while_loading_then_200(small_index):
    from voicecore.server import AppState

    state = AppState(providers="mock")
    async with running(state) as addr:
        assert await asyncio.to_thread(http_get, f"http://{addr}/readyz") == (503, {"ready": False, "draining": False})
        with pytest.raises(InvalidStatus) as e:  # refused before the handshake, so the gateway never says welcome
            async with connect(f"ws://{addr}/v1/session/s-0"):
                pass
        assert e.value.response.status_code == 503
        state.index, state.ready = small_index, True
        assert await asyncio.to_thread(http_get, f"http://{addr}/readyz") == (200, {"ready": True, "draining": False})


async def test_drain_refuses_new_sessions_but_keeps_open_one(small_index):
    from voicecore.server import AppState

    state = AppState(providers="mock", ready=True, index=small_index)
    async with running(state) as addr, connect(f"ws://{addr}/v1/session/s-1") as ws:
        assert await ask(ws)
        state.drain()
        assert await asyncio.to_thread(http_get, f"http://{addr}/readyz") == (503, {"ready": True, "draining": True})
        with pytest.raises(InvalidStatus) as e:
            async with connect(f"ws://{addr}/v1/session/s-2"):
                pass
        assert e.value.response.status_code == 503
        assert await ask(ws)  # the open session keeps working while draining


async def test_shutdown_ends_open_sessions_and_settles_each_once(small_index):
    from voicecore.server import AppState, mock_providers

    settled = []

    def make(sid):
        providers, _ = mock_providers()
        return providers, [lambda: settled.append(sid)]

    state = AppState(providers="mock", ready=True, index=small_index)
    async with running(state, make) as addr:
        async with connect(f"ws://{addr}/v1/session/s-a") as a, connect(f"ws://{addr}/v1/session/s-b") as b:
            await ask(a)
            await ask(b)
            await state.shutdown(drain_s=0.5)
            for ws in (a, b):
                events = [json.loads(m) async for m in ws if isinstance(m, str)]
                assert {"type": "session.ended", "reason": "shutdown"} in events
    assert sorted(settled) == ["s-a", "s-b"]


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.mark.timeout(180)
def test_sigterm_exits_0_within_5s(tmp_path):
    (tmp_path / "endpointing.md").write_text(DOCS_PAGE)
    port = free_port()
    p = subprocess.Popen([sys.executable, "-m", "voicecore.server", "--providers", "mock", "--port", str(port),
                          "--docs-dir", str(tmp_path), "--drain-s", "1"], env=os.environ.copy(),
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        deadline = time.time() + 150
        while time.time() < deadline:
            try:
                if http_get(f"http://127.0.0.1:{port}/readyz")[0] == 200:
                    break
            except OSError:
                pass
            time.sleep(0.5)
        else:
            pytest.fail("never ready")
        t0 = time.time()
        p.send_signal(signal.SIGTERM)
        assert p.wait(timeout=5) == 0
        assert time.time() - t0 < 5
    finally:
        if p.poll() is None:
            p.kill()
