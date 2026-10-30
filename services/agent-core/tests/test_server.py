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
import contextlib  # noqa: E402
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
from websockets.exceptions import ConnectionClosed, InvalidStatus  # noqa: E402

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


async def test_session_setup_failure_still_settles_the_reservations(small_index):
    from voicecore.server import AppState, mock_providers

    settled = []

    def make(sid):
        providers, _ = mock_providers()
        return {**providers, "no_such_option": 1}, [lambda: settled.append(sid)]  # Session(...) raises TypeError

    state = AppState(providers="mock", ready=True, index=small_index)
    async with running(state, make) as addr:
        async with connect(f"ws://{addr}/v1/session/s-x") as ws:
            with contextlib.suppress(ConnectionClosed):
                await ws.recv()
    assert settled == ["s-x"]


async def test_session_and_turn_events(small_index, tmp_path):
    from voicecore.server import AppState, handler_for, http_routes

    state = AppState(providers="mock", ready=True, index=small_index)
    async with serve(handler_for("mock", tmp_path, state), "127.0.0.1", 0, process_request=http_routes(state)) as server:
        async with connect(f"ws://127.0.0.1:{server.sockets[0].getsockname()[1]}/v1/session/s-t") as ws:
            await ask(ws)
            await asyncio.sleep(0.5)  # the answer finishes speaking
            await ws.close(reason="client")  # what the gateway sends when its client leaves
        await asyncio.sleep(0.2)
    events = [json.loads(line) for line in (tmp_path / "s-t.jsonl").read_text().splitlines()]
    assert (events[0]["span"], events[0]["event"]) == ("session", "started")
    assert (events[-1]["span"], events[-1]["event"], events[-1]["attrs"]) == ("session", "ended", {"reason": "client"})
    result = next(e for e in events if (e["span"], e["event"]) == ("turn", "result"))
    assert (result["generation_id"], result["attrs"]) == (1, {"turn_id": "t1", "kind": "text", "result": "answer"})
    calls = [(e["span"], e["event"]) for e in events if e["event"] in ("request", "connect")]
    assert ("llm", "request") in calls and ("tts", "request") in calls  # provider-call counters' denominators


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


@pytest.mark.timeout(180)
def test_sigterm_right_after_start_exits_0(tmp_path):
    """A stop that lands while models load (handlers are installed before loading) still exits 0."""
    (tmp_path / "endpointing.md").write_text(DOCS_PAGE)
    port = free_port()
    p = subprocess.Popen([sys.executable, "-m", "voicecore.server", "--providers", "mock", "--port", str(port),
                          "--docs-dir", str(tmp_path), "--drain-s", "1"], env=os.environ.copy(),
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        deadline = time.time() + 120
        while time.time() < deadline:  # serving, not necessarily ready
            try:
                if http_get(f"http://127.0.0.1:{port}/healthz")[0] == 200:
                    break
            except OSError:
                pass
            time.sleep(0.05)
        p.send_signal(signal.SIGTERM)
        assert p.wait(timeout=60) == 0
    finally:
        if p.poll() is None:
            p.kill()


@pytest.mark.timeout(180)
def test_metrics_endpoint_type_lines(tmp_path):
    """Pins the exported names (exporter suffixes included): the alert rules and dashboards query exactly these."""
    (tmp_path / "endpointing.md").write_text(DOCS_PAGE)
    port, mport = free_port(), free_port()
    p = subprocess.Popen([sys.executable, "-m", "voicecore.server", "--providers", "mock", "--port", str(port),
                          "--docs-dir", str(tmp_path), "--drain-s", "1", "--metrics-port", str(mport), "--metrics-host", "127.0.0.1"],
                         env=os.environ.copy(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
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

        async def one_turn():
            async with connect(f"ws://127.0.0.1:{port}/v1/session/s-m") as ws:
                await ask(ws)
                await asyncio.sleep(0.5)

        asyncio.run(one_turn())
        body = urllib.request.urlopen(f"http://127.0.0.1:{mport}/metrics", timeout=5).read().decode()
        for line in ("# TYPE voicecore_turns_total counter", "# TYPE voicecore_stage_ms histogram",
                     "# TYPE voicecore_spend_usd gauge", "# TYPE voicecore_provider_calls_total counter",
                     "# TYPE voicecore_breaker_state gauge"):
            assert line in body, line
    finally:
        p.send_signal(signal.SIGTERM)
        if p.wait(timeout=10) is None:
            p.kill()


async def test_settle_bills_all_stt_streams(monkeypatch):
    from voicecore.providers.deepgram_stt import MAX_AUDIO_S, PRICE_PER_MIN
    from voicecore.server import live_providers

    for k in ("DEEPGRAM_API_KEY", "OPENROUTER_API_KEY"):  # clients are only built, never called: no real key, no spend
        monkeypatch.setenv(k, "test-key")

    p, settle = live_providers("s-r")
    p["stt"].audio_s = 3.0  # the first stream dropped after 3 s of speech
    second = p["stt_factory"]()
    assert second.max_audio_s == MAX_AUDIO_S - 3.0  # one cap for the session, not one per stream
    second.audio_s = 2.0
    for s in settle:
        s()
    stt = next(e for e in json.loads(budget.ledger_file().read_text())["entries"] if e["label"] == "server stt s-r")
    assert stt["status"] == "settled" and stt["amount"] == round(5.0 / 60 * PRICE_PER_MIN, 6)


async def test_public_pool_over_its_cap_answers_in_text_from_the_docs(small_index):
    from voicecore.runtime.session import BUDGET_TEXT_ONLY
    from voicecore.server import AppState, handler_for, http_routes

    def broke(sid):
        raise budget.DailyCapReached("public: today's share is used up")

    state = AppState(providers="live", ready=True, index=small_index)
    async with serve(handler_for("live", None, state, make_providers=broke, pool="public"), "127.0.0.1", 0,
                     process_request=http_routes(state)) as server:
        async with connect(f"ws://127.0.0.1:{server.sockets[0].getsockname()[1]}/v1/session/s-p") as ws:
            first = await ask(ws, "anything")  # the notice comes first
            assert first == BUDGET_TEXT_ONLY
            answer = await ask(ws, "how does eager endpointing work?")
    assert answer.startswith("Closest section: ")


async def test_mock_billed_public_reservations_carry_the_sub_cap():
    from voicecore.server import mock_billed_providers

    _, settle = mock_billed_providers("s-1", sub="public")
    assert budget.total("public") == 0.0017
    for s in settle:
        s()
