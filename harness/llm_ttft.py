"""LLM time-to-first-answer-token benchmark (latency work, live): uv run python harness/llm_ttft.py [--n 6]

Same grounded prompt the answer engine builds (5 uv docs passages + a dev question), streamed through
OpenRouter with the provider pinned. Measures first answer token (content, not reasoning), first sentence
end (when TTS could start), and completion. Spend is reserved first. Writes reports/llm_ttft.json.
"""
import argparse
import asyncio
import json
import re
import time
from datetime import UTC, datetime

from fixtures import ROOT
from openai import AsyncOpenAI
from timeline import percentile

from voicecore import budget, keys
from voicecore.answer.engine import AnswerEngine
from voicecore.answer.index import Index
from voicecore.answer.ingest import ingest

CONFIGS = [  # (label, model, provider order, reasoning effort or None)
    ("gpt-4.1-nano (current)", "openai/gpt-4.1-nano", None, None),
    ("gpt-oss-120b Cerebras low", "openai/gpt-oss-120b", ["Cerebras"], "low"),
    ("gpt-oss-120b Groq low", "openai/gpt-oss-120b", ["Groq"], "low"),
    ("gpt-oss-120b BaseTen low", "openai/gpt-oss-120b", ["BaseTen"], "low"),
    ("gpt-oss-20b Groq low", "openai/gpt-oss-20b", ["Groq"], "low"),
]
QUESTIONS = ["How do I install uv on a Mac or Linux machine?", "How can I check that my lock file is up to date without changing it?",
             "How do I add an extra package for just one uv run command?", "Will uv sync remove packages that are not part of my project?",
             "How do I declare dependencies inside a single Python script?", "How do I make uv install every dependency group by default?"]


async def one(client, model, provider, effort, messages):
    extra = {"usage": {"include": True}}
    if provider:
        extra["provider"] = {"order": provider, "allow_fallbacks": False}
    if effort:
        extra["reasoning"] = {"effort": effort}
    t0 = time.perf_counter()
    first = sentence = None
    text, usage = "", {}
    stream = await client.chat.completions.create(model=model, messages=messages, stream=True, max_tokens=300, temperature=0,
                                                  stream_options={"include_usage": True}, extra_body=extra)
    async for ch in stream:
        if ch.choices and ch.choices[0].delta.content:
            if first is None:
                first = time.perf_counter() - t0
            text += ch.choices[0].delta.content
            if sentence is None and re.search(r"[.!?](\s|$)", text):
                sentence = time.perf_counter() - t0
        if ch.usage:
            u = ch.usage
            usage = {"in": u.prompt_tokens, "out": u.completion_tokens, "cost": (u.model_extra or {}).get("cost"),
                     "reasoning": getattr(getattr(u, "completion_tokens_details", None), "reasoning_tokens", None)}
    return {"first_token_ms": None if first is None else round(first * 1000), "first_sentence_ms": None if sentence is None else round(sentence * 1000),
            "total_ms": round((time.perf_counter() - t0) * 1000), "text": text, **usage}


async def main(n):
    index = Index(ingest(ROOT / "fixtures/docs/uv"))
    engine = AnswerEngine(index, llm=None)
    prompts = [engine.messages(q, [], engine.retrieve(q)) for q in QUESTIONS[:n]]
    client = AsyncOpenAI(api_key=keys.key("OPENROUTER_API_KEY"), base_url="https://openrouter.ai/api/v1", max_retries=0, timeout=30)
    run = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    res = budget.reserve("usd", 0.05, label=f"llm_ttft {run}")
    out, spent = {}, 0.0
    try:
        for label, model, provider, effort in CONFIGS:
            rows = []
            for m in prompts:
                try:
                    r = await one(client, model, provider, effort, m)
                except Exception as e:  # a provider being down is a result too
                    r = {"error": f"{type(e).__name__}: {e}"[:200]}
                rows.append(r)
                spent += r.get("cost") or 0.0
            ok = [r for r in rows if r.get("first_token_ms") is not None]
            pct = lambda k: {"p50": percentile([r[k] for r in ok if r.get(k)], 50), "max": max((r[k] for r in ok if r.get(k)), default=None)} if ok else None  # noqa: E731
            out[label] = {"ok": len(ok), "n": len(rows), "first_token_ms": pct("first_token_ms"), "first_sentence_ms": pct("first_sentence_ms"),
                          "total_ms": pct("total_ms"), "reasoning_tokens": [r.get("reasoning") for r in rows], "rows": rows}
            print(f"{label:28s} ok {len(ok)}/{len(rows)} first token {out[label]['first_token_ms']} first sentence {out[label]['first_sentence_ms']} reasoning {out[label]['reasoning_tokens']}", flush=True)
    finally:
        budget.settle(res, round(spent, 6), run_id=run)
    (ROOT / "reports/llm_ttft.json").write_text(json.dumps({"run_id": run, "configs": out}, indent=2) + "\n")
    print("spent", round(spent, 5))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=6)
    asyncio.run(main(ap.parse_args().n))
