"""Orchestrator server for the gateway hop: ws://HOST:PORT/v1/session/{id}, one Session per connection.

    uv run python -m voicecore.server [--providers mock|live] [--port 8765] [--trace-dir DIR]

Mock providers by default. Live providers spend money: each session reserves its caps first
(STT 300 s, LLM up to $0.02, TTS 4,000 characters with Deepgram or 1,500 with Cartesia) and settles what it used.
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
from voicecore.answer.ingest import docusaurus, ingest
from voicecore.providers import cartesia_tts, deepgram_tts
from voicecore.providers.deepgram_stt import MAX_AUDIO_S, PRICE_PER_MIN
from voicecore.providers.base import ProviderError
from voicecore.providers.factory import make_live
from voicecore.providers.mock import LLMScript, MockLLM, MockSTT, MockTTS
from voicecore.runtime.session import Session
from voicecore.trace import JsonlSink, Tracer
from voicecore.turntaking.floor import Policy
from voicecore.turntaking.vad_silero import SileroVAD

log = logging.getLogger("voicecore.server")
MOCK_ANSWER = "Eager endpointing asks the speech recognizer for a final transcript after 200 ms of silence [1]. A punctuated final ends the turn [2]."
DOCS_DIR = Path(__file__).resolve().parents[3] / "apps/docs/docs"  # the Docusaurus site the assistant answers from
LLM_CAP_USD = 0.02  # gpt-oss-120b on Cerebras: about $0.0006 per grounded turn, so about 30 turns a session


def mock_providers():
    return {"stt": MockSTT(canned="how does eager endpointing work?"), "llm": MockLLM(LLMScript(tokens=[w + " " for w in MOCK_ANSWER.split()])),
            "tts": MockTTS(), "tts_factory": MockTTS}, []


MOCK_BILLED_USD = {"stt": 0.001, "llm": 0.0005, "tts": 0.0002}  # per session; lets tests check ledger maths for free


def mock_billed_providers(sid):
    """Mock providers that still reserve and settle fixed literal amounts, like a live session, at no cost."""
    providers, _ = mock_providers()
    res = budget.reserve_all([("usd", v, f"mock-billed {k} {sid}") for k, v in MOCK_BILLED_USD.items()])
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


def live_providers(sid, llm_opts=None, tts_name="deepgram"):
    stt_res, llm_res = budget.reserve_all([("usd", round(MAX_AUDIO_S / 60 * PRICE_PER_MIN, 6), f"server stt {sid}"),
                                           ("usd", LLM_CAP_USD, f"server llm {sid}")])
    kind, mod, pool, amount, cost = TTS[tts_name]
    tts = {"res": None, "streams": []}

    def new_tts(ws=None):  # a retry opens a second stream; both bill one reservation and share its character cap
        if tts["res"] is None:
            try:
                tts["res"] = budget.reserve(pool, amount, label=f"server tts {sid}")
            except budget.BudgetExceeded as e:
                raise ProviderError("fatal", f"TTS budget: {e}") from None
        used = sum(t.chars for t in tts["streams"])
        tts["streams"].append(make_live(kind, tts["res"], max_chars=mod.MAX_CHARS - used, ws=ws))
        return tts["streams"][-1]

    p = {"stt": make_live("stt", stt_res), "llm": make_live("llm", llm_res, **(llm_opts or {})),
         "tts": OnDemandTTS(new_tts, mod.open_socket), "tts_factory": lambda: OnDemandTTS(new_tts, mod.open_socket)}
    settle = [lambda: budget.settle(stt_res, p["stt"].cost_usd(), request_id=p["stt"].request_id),
              lambda: budget.settle(llm_res, round(p["llm"].cost_usd, 6), calls=p["llm"].calls),
              lambda: tts["res"] and budget.settle(tts["res"], cost(sum(t.chars for t in tts["streams"])),
                                                   chars=sum(t.chars for t in tts["streams"]), streams=len(tts["streams"]))]
    return p, settle


def handler_for(mode: str, trace_dir: Path | None, index: Index, policy: Policy = Policy(), llm_opts: dict | None = None,
                name: str = "VoiceCore", tts: str = "deepgram"):
    async def handler(ws):  # ponytail: VAD runs inline on the event loop (~0.3 ms per window); move to a thread if sessions x frames saturate one core
        sid = ws.request.path.rsplit("/", 1)[-1]
        try:
            providers, settle = (live_providers(sid, llm_opts, tts) if mode == "live"
                                 else mock_billed_providers(sid) if mode == "mock-billed" else mock_providers())
        except budget.BudgetExceeded as e:
            log.warning("session %s refused: %s", sid, e)
            await ws.send(protocol.event("session.ended", reason="budget"))
            await ws.close()
            return
        sink = JsonlSink(trace_dir / f"{sid}.jsonl") if trace_dir else None
        engine = AnswerEngine(index, providers["llm"], name=name)
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
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    SileroVAD()  # load the model now: loading it inside the first session stalls its mic frames
    index = Index(ingest(args.docs_dir, site=docusaurus(args.docs_url)))  # vectors are cached under .cache after the first build
    index.dense("warm up", 1)
    args.policy = args.policy or ("eager" if args.providers == "live" else "fixed")
    policy = Policy("eager", asr_silence_ms=200) if args.policy == "eager" else Policy(args.policy)
    llm_opts = {}
    if args.llm_model:
        llm_opts["model"] = args.llm_model
    if args.llm_provider:
        llm_opts["provider"] = None if args.llm_provider == "any" else args.llm_provider
    if args.llm_reasoning:
        llm_opts["reasoning"] = None if args.llm_reasoning == "none" else args.llm_reasoning
    async with serve(handler_for(args.providers, args.trace_dir, index, policy, llm_opts, tts=args.tts), args.host, args.port, max_size=1 << 20) as server:
        log.info("orchestrator listening on ws://%s:%d (%s providers)", args.host, args.port, args.providers)
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
