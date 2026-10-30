"""Orchestrator server for the gateway hop: ws://HOST:PORT/v1/session/{id}, one Session per connection.

    uv run python -m voicecore.server [--providers mock|live] [--port 8765] [--trace-dir DIR]

Mock providers by default. Live providers spend money: each session reserves its caps first
(STT 300 s, LLM up to $0.02, TTS 4,000 characters with Deepgram or 1,500 with Cartesia) and settles what it used.
"""
import argparse
import asyncio
import contextlib
import json
import logging
import os
import signal
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from http import HTTPStatus
from pathlib import Path

from websockets.asyncio.server import serve
from websockets.exceptions import ConnectionClosed

from voicecore import budget, logs, metrics, protocol
from voicecore.answer.engine import AnswerEngine
from voicecore.answer.extractive import closest_section
from voicecore.answer.index import Index
from voicecore.answer.ingest import docusaurus, ingest
from voicecore.providers import cartesia_tts, deepgram_tts
from voicecore.providers.deepgram_stt import MAX_AUDIO_S, PRICE_PER_MIN
from voicecore.providers.base import ProviderError
from voicecore.providers.factory import make_live
from voicecore.providers.mock import LLMScript, MockLLM, MockSTT, MockTTS
from voicecore.resilience import Breaker
from voicecore.runtime.session import Session
from voicecore.trace import JsonlSink, Tracer
from voicecore.turntaking.floor import Policy
from voicecore.turntaking.vad_silero import SileroVAD

log = logging.getLogger("voicecore.server")
MOCK_ANSWER = "Eager endpointing asks the speech recognizer for a final transcript after 200 ms of silence [1]. A punctuated final ends the turn [2]."
DOCS_DIR = Path(__file__).resolve().parents[3] / "apps/docs/docs"  # the Docusaurus site the assistant answers from
LLM_CAP_USD = 0.02  # gpt-oss-120b on Cerebras: about $0.0006 per grounded turn, so about 30 turns a session


def mock_providers():
    stt = lambda: MockSTT(canned="how does eager endpointing work?")  # noqa: E731
    return {"stt": stt(), "stt_factory": stt, "llm": MockLLM(LLMScript(tokens=[w + " " for w in MOCK_ANSWER.split()])),
            "tts": MockTTS(), "tts_factory": MockTTS}, []


MOCK_BILLED_USD = {"stt": 0.001, "llm": 0.0005, "tts": 0.0002}  # per session; lets tests check ledger maths for free


def mock_billed_providers(sid, sub=None):
    """Mock providers that still reserve and settle fixed literal amounts, like a live session, at no cost."""
    providers, _ = mock_providers()
    res = budget.reserve_all([("usd", v, f"mock-billed {k} {sid}") for k, v in MOCK_BILLED_USD.items()], sub=sub)
    return providers, [lambda r=r, v=v: budget.settle(r, v) for r, v in zip(res, MOCK_BILLED_USD.values())]


class OnDemandTTS:
    """Builds the live TTS stream (and reserves its credits) when the session first speaks, so idle sockets do
    not hold the credit pool (security review 2026-10-30). A refused reservation becomes a fatal TTS error:
    the session then answers in text only."""

    def __init__(self, make, opener):
        self._make, self._open, self._tts, self._ready, self._ws = make, opener, None, asyncio.Event(), None

    async def warm(self):
        """Opens the TTS socket now (free): Cartesia's handshake took 250-330 ms at the first answer."""
        if self._tts is None and self._ws is None:
            self._ws = await self._open()

    async def synth(self, gen, text, last):
        if self._tts is None:
            ws, self._ws = self._ws, None
            self._tts = self._make(ws)
            self._ready.set()
        await self._tts.synth(gen, text, last)

    async def audio(self):
        await self._ready.wait()
        async for a in self._tts.audio():
            yield a

    async def cancel(self, gen):
        if self._tts:
            await self._tts.cancel(gen)

    async def close(self):
        if self._tts:
            await self._tts.close()
        elif self._ws is not None:
            await self._ws.close()


TTS = {  # factory kind, module, budget pool, reservation for MAX_CHARS characters, cost of n characters
    "deepgram": ("deepgram_tts", deepgram_tts, "usd", round(deepgram_tts.MAX_CHARS * deepgram_tts.PRICE_PER_CHAR, 6),
                 lambda n: round(n * deepgram_tts.PRICE_PER_CHAR, 6)),
    "cartesia": ("tts", cartesia_tts, "cartesia_credits", cartesia_tts.MAX_CHARS, lambda n: n),  # 1 credit per character
}


def live_providers(sid, llm_opts=None, tts_name="deepgram", sub=None):
    """sub: a budget sub-cap every reservation also counts against (\"public\" for a public deployment)."""
    kind, mod, pool, amount, cost = TTS[tts_name]  # before reserving: an unknown name must not leak reservations
    stt_res, llm_res = budget.reserve_all([("usd", round(MAX_AUDIO_S / 60 * PRICE_PER_MIN, 6), f"server stt {sid}"),
                                           ("usd", LLM_CAP_USD, f"server llm {sid}")], sub=sub)
    tts = {"res": None, "streams": []}
    stt_streams = []

    def new_stt():  # a reconnect opens a second stream; both bill one reservation and share its audio cap
        stt_streams.append(make_live("stt", stt_res, max_audio_s=MAX_AUDIO_S - sum(t.audio_s for t in stt_streams)))
        return stt_streams[-1]

    def new_tts(ws=None):  # a retry opens a second stream; both bill one reservation and share its character cap
        if tts["res"] is None:
            try:
                tts["res"] = budget.reserve(pool, amount, label=f"server tts {sid}", sub=sub)
            except budget.BudgetExceeded as e:
                raise ProviderError("fatal", f"TTS budget: {e}") from None
        used = sum(t.chars for t in tts["streams"])
        tts["streams"].append(make_live(kind, tts["res"], max_chars=mod.MAX_CHARS - used, ws=ws))
        return tts["streams"][-1]

    try:
        p = {"stt": new_stt(), "stt_factory": new_stt, "llm": make_live("llm", llm_res, **(llm_opts or {})),
             "tts": OnDemandTTS(new_tts, mod.open_socket), "tts_factory": lambda: OnDemandTTS(new_tts, mod.open_socket)}
    except Exception:  # nothing was used: release the reservations instead of leaving them counting
        for r in (stt_res, llm_res):
            budget.settle(r, 0)
        raise
    settle = [lambda: budget.settle(stt_res, round(sum(t.cost_usd() for t in stt_streams), 6),
                                    request_ids=[t.request_id for t in stt_streams], streams=len(stt_streams)),
              lambda: budget.settle(llm_res, round(p["llm"].cost_usd, 6), calls=p["llm"].calls),
              lambda: tts["res"] and budget.settle(tts["res"], cost(sum(t.chars for t in tts["streams"])),
                                                   chars=sum(t.chars for t in tts["streams"]), streams=len(tts["streams"]))]
    return p, settle


@dataclass
class AppState:
    """What /healthz and /readyz report, and what a drain needs: the open session sockets."""
    providers: str = "mock"
    version: str = field(default_factory=lambda: os.environ.get("VOICECORE_VERSION", "dev"))
    ready: bool = False  # VAD model and docs index loaded
    draining: bool = False
    index: Index | None = None
    sessions: set = field(default_factory=set)
    metrics: Callable[[dict], None] | None = None  # a trace sink that feeds the metrics (main sets it)
    breakers: dict[str, Breaker] = field(default_factory=lambda: {p: Breaker(p) for p in ("stt", "llm", "tts")})  # per process

    def drain(self):
        self.draining = True

    async def shutdown(self, drain_s: float = 25.0):
        """Stop taking sessions, let open ones finish for up to drain_s, then end the rest with session.ended{shutdown}.
        Each handler's finally block settles its budget, so this waits for those too."""
        self.drain()
        loop = asyncio.get_running_loop()
        deadline = loop.time() + drain_s
        while self.sessions and loop.time() < deadline:
            await asyncio.sleep(0.05)
        async def end(ws):  # in parallel and bounded: a slow peer must not push past the container's grace period
            with contextlib.suppress(ConnectionClosed, TimeoutError):
                await asyncio.wait_for(ws.send(protocol.event("session.ended", reason="shutdown")), 2)
                await asyncio.wait_for(ws.close(1001, "shutdown"), 2)

        await asyncio.gather(*(end(ws) for ws in list(self.sessions)))
        deadline = loop.time() + 5
        while self.sessions and loop.time() < deadline:
            await asyncio.sleep(0.05)


def _json(connection, status, body):
    r = connection.respond(status, json.dumps(body))
    r.headers["Content-Type"] = "application/json"
    return r


def http_routes(state: AppState):
    """websockets process_request hook: health and readiness on the session port, and no WebSocket handshake while
    starting or draining (HTTP 503 before the upgrade, so the gateway never tells a client 'welcome')."""
    def process_request(connection, request):
        if request.path == "/healthz":
            return _json(connection, HTTPStatus.OK, {"status": "ok", "providers": state.providers, "version": state.version})
        if request.path == "/readyz":
            ok = state.ready and not state.draining
            return _json(connection, HTTPStatus.OK if ok else HTTPStatus.SERVICE_UNAVAILABLE, {"ready": state.ready, "draining": state.draining})
        if not state.ready or state.draining:
            return connection.respond(HTTPStatus.SERVICE_UNAVAILABLE, "draining\n" if state.draining else "starting\n")
        return None
    return process_request


def handler_for(mode: str, trace_dir: Path | None, state: AppState, policy: Policy = Policy(), llm_opts: dict | None = None,
                name: str = "VoiceCore", tts: str = "deepgram", make_providers=None, pool: str = "usd"):
    """make_providers(sid) -> (providers, settle callables); defaults by mode. Tests inject their own.
    pool "public": reservations also count against the public sub-cap, and a session refused by the budget is
    served in text from the docs instead of ending."""
    sub = "public" if pool == "public" else None

    def default_providers(sid):
        return (live_providers(sid, llm_opts, tts, sub=sub) if mode == "live"
                else mock_billed_providers(sid, sub=sub) if mode == "mock-billed" else mock_providers())

    make_providers = make_providers or default_providers

    async def handler(ws):  # ponytail: VAD runs inline on the event loop (~0.3 ms per window); move to a thread if sessions x frames saturate one core
        sid = ws.request.path.rsplit("/", 1)[-1]
        state.sessions.add(ws)  # first, so a shutdown that starts while providers are being built still sees it
        try:
            await serve_session(ws, sid)
        finally:
            state.sessions.discard(ws)

    async def serve_session(ws, sid):
        try:
            providers, settle = make_providers(sid)
        except budget.BudgetExceeded as e:
            if sub:  # public deployment: no spend left today, but the docs can still point the way
                log.info("budget used up, text only: %s", e, extra={"session_id": sid, "reason": "budget"})
                providers, settle = {"llm": MockLLM(LLMScript(tokens=[])), "tts": MockTTS()}, []  # inert: text_only never calls them
                text_only = True
            else:
                log.warning("session refused: %s", e, extra={"session_id": sid, "reason": "budget"})
                if state.metrics:
                    Tracer(sid, state.metrics).emit("session", "ended", reason="budget")
                await ws.send(protocol.event("session.ended", reason="budget"))
                await ws.close()
                return
        else:
            text_only = False
        started, sink, session, reason = time.monotonic(), None, None, None
        sinks = [state.metrics] if state.metrics else []
        tracer = Tracer(sid, lambda e: [s(e) for s in sinks])
        try:  # everything after the reservation: whatever fails, the finally settles it
            if trace_dir:
                sinks.append(sink := JsonlSink(trace_dir / f"{sid}.jsonl"))
            engine = AnswerEngine(state.index, providers["llm"], name=name)
            extract = closest_section(engine.retrieve) if text_only else None
            session = Session(sid, send=ws.send, vad=SileroVAD(), policy=policy, tracer=tracer, answer=engine.stream,
                              breakers=state.breakers, text_only=extract, **providers)
            tracer.emit("session", "started")
            await session.start()
            log.info("session started", extra={"session_id": sid})
            async for m in ws:
                if isinstance(m, bytes):
                    f = protocol.decode_frame(m)
                    if f.kind == protocol.KIND_MIC:
                        await session.on_frame(f)
                else:
                    await session.on_event(protocol.decode_event(m))
        except ConnectionClosed as e:
            log.info("session connection closed: %s", e, extra={"session_id": sid})
        except ValueError as e:  # the message may echo client text, so log only its kind
            reason = "protocol_error"
            log.info("protocol error", extra={"session_id": sid, "kind": type(e).__name__})
        finally:
            if session:
                await session.close()
            tracer.emit("session", "ended", reason=reason or end_reason(ws.close_reason, state.draining))
            if sink:
                sink.close()
            for s in settle:  # in a thread: a slow ledger (Redis) must not stall the other sessions' audio
                with contextlib.suppress(Exception):
                    await asyncio.to_thread(s)
            log.info("session ended", extra={"session_id": sid, "duration_ms": round((time.monotonic() - started) * 1000)})

    return handler


END_REASONS = {"client", "expired", "shutdown", "error", "budget", "unavailable"}  # the gateway's close reasons


def end_reason(close_reason: str | None, draining: bool) -> str:
    """Why a session ended, from the gateway's close reason; a bounded set, since it becomes a metric label."""
    if close_reason in END_REASONS:
        return close_reason
    return "shutdown" if draining else "error"


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--providers", choices=["mock", "mock-billed", "live"], default="mock",
                    help="mock-billed: mock providers that reserve and settle small fixed amounts (ledger tests, no spend)")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--trace-dir", type=Path)
    ap.add_argument("--docs-dir", type=Path, default=DOCS_DIR, help="Docusaurus docs folder to answer from")
    ap.add_argument("--docs-url", default="http://localhost:3000/", help="base URL of that docs site (citations link there)")
    ap.add_argument("--policy", choices=["fixed", "adaptive", "asr_assisted", "eager"], default=None,
                    help="endpointing (ADR 0002); default eager with live providers, fixed with mocks (the mock STT "
                         "returns its canned final at every pause, which would end every turn early)")
    ap.add_argument("--llm-model", default=None, help="OpenRouter model id (default: openai_compat_llm.MODEL)")
    ap.add_argument("--llm-provider", default=None, help="OpenRouter provider to try first; 'any' lets OpenRouter route")
    ap.add_argument("--llm-reasoning", default=None, help="reasoning effort for reasoning models; 'none' to omit")
    ap.add_argument("--tts", choices=sorted(TTS), default="deepgram", help="speech synthesis provider (live mode)")
    ap.add_argument("--drain-s", type=float, default=25.0, help="on SIGTERM, seconds to let open sessions finish")
    ap.add_argument("--pool", choices=["usd", "public"], default="usd",
                    help="public: spend also counts against the public sub-cap (2 USD, 0.50 a day); over it, answer in text")
    ap.add_argument("--metrics-port", type=int, default=0, help="Prometheus /metrics port, e.g. 9464 (0 = off); keep it off the public internet")
    ap.add_argument("--metrics-host", default="0.0.0.0", help="listen address for /metrics (the scraper reaches it inside compose)")
    args = ap.parse_args()
    logs.setup()
    args.policy = args.policy or ("eager" if args.providers == "live" else "fixed")
    policy = Policy("eager", asr_silence_ms=200) if args.policy == "eager" else Policy(args.policy)
    llm_opts = {}
    if args.llm_model:
        llm_opts["model"] = args.llm_model
    if args.llm_provider:
        llm_opts["provider"] = None if args.llm_provider == "any" else args.llm_provider
    if args.llm_reasoning:
        llm_opts["reasoning"] = None if args.llm_reasoning == "none" else args.llm_reasoning
    state = AppState(providers=args.providers)
    if args.metrics_port:
        state.metrics = metrics.serve_metrics(args.metrics_port, args.metrics_host, state.breakers)
    handler = handler_for(args.providers, args.trace_dir, state, policy, llm_opts, tts=args.tts, pool=args.pool)
    async with serve(handler, args.host, args.port, max_size=1 << 20, process_request=http_routes(state)):
        log.info("orchestrator listening on ws://%s:%d (%s providers), loading models", args.host, args.port, args.providers)

        loop = asyncio.get_running_loop()
        stop = asyncio.Event()
        if state.metrics:
            lag = asyncio.ensure_future(state.metrics.sample_loop_lag())  # noqa: F841 (runs until the process exits)

        def on_signal():  # first signal: drain; then restore defaults so a second Ctrl-C quits at once
            stop.set()
            for sig in (signal.SIGTERM, signal.SIGINT):
                loop.remove_signal_handler(sig)

        for sig in (signal.SIGTERM, signal.SIGINT):  # before loading, so a stop during startup still exits 0
            loop.add_signal_handler(sig, on_signal)  # (PID 1 in a container ignores SIGTERM without a handler)

        def load():  # serving already: /healthz answers and /readyz says 503 until this finishes
            SileroVAD()  # load the model now: loading it inside the first session stalls its mic frames
            index = Index(ingest(args.docs_dir, site=docusaurus(args.docs_url)))  # vectors are cached under .cache
            index.dense("warm up", 1)
            return index

        loading = asyncio.ensure_future(asyncio.to_thread(load))
        await asyncio.wait([loading, asyncio.ensure_future(stop.wait())], return_when=asyncio.FIRST_COMPLETED)
        if loading.done():
            state.index = loading.result()
            state.ready = True
            log.info("orchestrator ready")
            await stop.wait()
        log.info("draining (up to %.0f s)", args.drain_s)
        await state.shutdown(args.drain_s)


if __name__ == "__main__":
    asyncio.run(main())
