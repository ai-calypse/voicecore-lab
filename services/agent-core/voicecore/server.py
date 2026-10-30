"""Orchestrator server for the gateway hop: ws://HOST:PORT/v1/session/{id}, one Session per connection.

    uv run python -m voicecore.server [--providers mock|live] [--port 8765] [--trace-dir DIR]

Mock providers by default. Live providers spend money: each session reserves its caps first
(STT 120 s, LLM up to $0.002, TTS 1,500 characters) and settles what it actually used.
"""
import argparse
import asyncio
import contextlib
import logging
from pathlib import Path

from websockets.asyncio.server import serve
from websockets.exceptions import ConnectionClosed

from voicecore import budget, protocol
from voicecore.answer.engine import AnswerEngine
from voicecore.answer.index import Index
from voicecore.answer.ingest import ingest
from voicecore.providers.cartesia_tts import MAX_CHARS
from voicecore.providers.deepgram_stt import MAX_AUDIO_S, PRICE_PER_MIN
from voicecore.providers.base import ProviderError
from voicecore.providers.factory import make_live
from voicecore.providers.mock import LLMScript, MockLLM, MockSTT, MockTTS
from voicecore.runtime.session import Session
from voicecore.trace import JsonlSink, Tracer
from voicecore.turntaking.floor import Policy
from voicecore.turntaking.vad_silero import SileroVAD

log = logging.getLogger("voicecore.server")
MOCK_ANSWER = "Install uv with the standalone installer script [1]. Then run uv init to start a project [2]."
DOCS = Path(__file__).resolve().parents[3] / "fixtures/docs/uv"
LLM_CAP_USD = 0.002


def mock_providers():
    return {"stt": MockSTT(canned="how do I install uv?"), "llm": MockLLM(LLMScript(tokens=[w + " " for w in MOCK_ANSWER.split()])),
            "tts": MockTTS(), "tts_factory": MockTTS}, []


class OnDemandTTS:
    """Builds the live TTS stream (and reserves its credits) when the session first speaks, so idle sockets do
    not hold the credit pool (security review 2026-10-30). A refused reservation becomes a fatal TTS error:
    the session then answers in text only."""

    def __init__(self, make):
        self._make, self._tts, self._ready = make, None, asyncio.Event()

    async def synth(self, gen, text, last):
        if self._tts is None:
            self._tts = self._make()
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


def live_providers(sid):
    stt_res = budget.reserve("usd", round(MAX_AUDIO_S / 60 * PRICE_PER_MIN, 6), label=f"server stt {sid}")
    llm_res = budget.reserve("usd", LLM_CAP_USD, label=f"server llm {sid}")
    tts = {"res": None, "streams": []}

    def new_tts():  # a retry opens a second stream; both bill one reservation and share its character cap
        if tts["res"] is None:
            try:
                tts["res"] = budget.reserve("cartesia_credits", MAX_CHARS, label=f"server tts {sid}")
            except budget.BudgetExceeded as e:
                raise ProviderError("fatal", f"TTS budget: {e}") from None
        used = sum(t.chars for t in tts["streams"])
        tts["streams"].append(make_live("tts", tts["res"], max_chars=MAX_CHARS - used))
        return tts["streams"][-1]

    p = {"stt": make_live("stt", stt_res), "llm": make_live("llm", llm_res), "tts": OnDemandTTS(new_tts),
         "tts_factory": lambda: OnDemandTTS(new_tts)}
    settle = [lambda: budget.settle(stt_res, p["stt"].cost_usd(), request_id=p["stt"].request_id),
              lambda: budget.settle(llm_res, round(p["llm"].cost_usd, 6), calls=p["llm"].calls),
              lambda: tts["res"] and budget.settle(tts["res"], sum(t.chars for t in tts["streams"]), streams=len(tts["streams"]))]
    return p, settle


def handler_for(mode: str, trace_dir: Path | None, index: Index, policy: Policy = Policy()):
    async def handler(ws):  # ponytail: VAD runs inline on the event loop (~0.3 ms per window); move to a thread if sessions x frames saturate one core
        sid = ws.request.path.rsplit("/", 1)[-1]
        try:
            providers, settle = live_providers(sid) if mode == "live" else mock_providers()
        except budget.BudgetExceeded as e:
            log.warning("session %s refused: %s", sid, e)
            await ws.send(protocol.event("session.ended", reason="budget"))
            await ws.close()
            return
        sink = JsonlSink(trace_dir / f"{sid}.jsonl") if trace_dir else None
        engine = AnswerEngine(index, providers["llm"])
        session = Session(sid, send=ws.send, vad=SileroVAD(), policy=policy, tracer=Tracer(sid, sink), answer=engine.stream, **providers)
        await session.start()
        try:
            async for m in ws:
                if isinstance(m, bytes):
                    f = protocol.decode_frame(m)
                    if f.kind == protocol.KIND_MIC:
                        await session.on_frame(f)
                else:
                    await session.on_event(protocol.decode_event(m))
        except (ConnectionClosed, ValueError) as e:
            log.info("session %s: %s", sid, e)
        finally:
            await session.close()
            if sink:
                sink.close()
            for s in settle:
                with contextlib.suppress(Exception):
                    s()

    return handler


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--providers", choices=["mock", "live"], default="mock")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--trace-dir", type=Path)
    ap.add_argument("--policy", choices=["fixed", "adaptive", "asr_assisted"], default="fixed", help="endpointing (ADR 0002)")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    SileroVAD()  # load the model now: loading it inside the first session stalls its mic frames
    index = Index(ingest(DOCS))  # docs snapshot; vectors are cached under .cache after the first build
    index.dense("warm up", 1)
    async with serve(handler_for(args.providers, args.trace_dir, index, Policy(args.policy)), args.host, args.port, max_size=1 << 20) as server:
        log.info("orchestrator listening on ws://%s:%d (%s providers)", args.host, args.port, args.providers)
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
