"""Docs assistant eval (live LLM, text only): uv run python harness/assistant_eval.py

Runs fixtures/docs/voicecore_key.json against the docs site corpus (apps/docs/docs) with the same AnswerEngine
the orchestrator uses. Each case is one or more user turns; the last turn is scored:

- chat: a friendly reply, no citations, not the bare refusal, at most two sentences;
- answer: cited, and the first citation (the section the widget opens) is on the expected page;
- not_covered: no citations, and the reply says the docs do not cover it.

Spend is reserved in the usd pool first. Writes reports/assistant_eval.json.
"""
import asyncio
import json
import re
from datetime import UTC, datetime

from fixtures import ROOT

from voicecore import budget
from voicecore.answer.engine import REFUSAL, AnswerEngine
from voicecore.answer.index import Index
from voicecore.answer.ingest import docusaurus, ingest
from voicecore.providers.factory import make_live

KEY = ROOT / "fixtures/docs/voicecore_key.json"
NOT_COVERED = re.compile(r"couldn.t find|could not find|don.t see|do not see|not (in|covered|mentioned)|doesn.t (cover|mention)|no information", re.I)


async def run_case(engine, case):
    history = []
    for turn in case["turns"]:
        out = [x async for x in engine.stream(turn, history)]
        text = "".join(x for x in out if isinstance(x, str)).strip()
        sources = next(x["sources"] for x in out if isinstance(x, dict))
        history += [{"role": "user", "content": turn}, {"role": "assistant", "content": text}]
    r = engine.last
    first = r.citations[0].file if r.citations else None
    ok = {
        "chat": not sources and text != REFUSAL and 0 < len(re.findall(r"[.!?](\s|$)", text + " ")) <= 2,
        "answer": bool(sources) and first in case.get("pages", []),
        "not_covered": not sources and bool(NOT_COVERED.search(text)),
    }[case["expect"]]
    return {"id": case["id"], "expect": case["expect"], "pass": ok, "turns": case["turns"], "reply": text,
            "opened": sources[0]["url"] if sources else None, "expected_pages": case.get("pages")}


async def main():
    run = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    cases = json.loads(KEY.read_text())["cases"]
    res = budget.reserve("usd", 0.05, label=f"assistant_eval {run}")
    llm = make_live("llm", res)
    try:
        engine = AnswerEngine(Index(ingest(ROOT / "apps/docs/docs", site=docusaurus("http://localhost:3000/"))), llm, name="VoiceCore")
        rows = [await run_case(engine, c) for c in cases]
    finally:
        budget.settle(res, round(llm.cost_usd, 6), run_id=run, calls=llm.calls)
    by = {k: f"{sum(r['pass'] for r in rows if r['expect'] == k)}/{sum(r['expect'] == k for r in rows)}" for k in ("chat", "answer", "not_covered")}
    out = {"run_id": run, "model": llm.model, "pass": f"{sum(r['pass'] for r in rows)}/{len(rows)}", "by_kind": by,
           "cost_usd": round(llm.cost_usd, 6), "rows": rows}
    (ROOT / "reports/assistant_eval.json").write_text(json.dumps(out, indent=2) + "\n")
    for r in rows:
        print(("PASS" if r["pass"] else "FAIL"), r["id"], "|", r["turns"][-1], "|", r["reply"][:140], "|", r["opened"])
    print(json.dumps({k: v for k, v in out.items() if k != "rows"}))


if __name__ == "__main__":
    asyncio.run(main())
