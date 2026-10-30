"""Grounded answer eval (S04-T05, live LLM, text only): uv run python harness/answer_eval.py [--split holdout]

Holdout questions run on the docs snapshot; adversarial questions run on the snapshot plus the adversarial
pages. Spend is reserved in the usd pool first. Writes reports/docs_eval.json.
"""
import argparse
import asyncio
import json
import re
from datetime import UTC, datetime

from fixtures import ROOT
from timeline import mrr, recall_at_k

from voicecore import budget
from voicecore.answer.engine import REFUSAL, AnswerEngine
from voicecore.answer.index import Index
from voicecore.answer.ingest import ingest
from voicecore.providers.factory import make_live

DOCS = ROOT / "fixtures/docs/uv"
ADV = ROOT / "fixtures/docs/adversarial"


def _norm(s):  # gpt-oss writes "free‑threaded" with U+2011; "pure-Python" should match "pure python"
    return re.sub(r"[-\u2010-\u2015]", " ", s.lower())


def has(text, term):
    return _norm(term) in _norm(text)


async def ask(engine, question):
    async for _ in engine.stream(question, []):
        pass
    return engine.last


async def run_key(index, llm, split):
    key = [q for q in json.loads((DOCS.parent / "answer_key.json").read_text())["questions"] if q["split"] == split]
    rows = []
    for q in key:
        r = await ask(AnswerEngine(index, llm), q["question"])
        must = {(c["file"], c["heading"]) for c in q["must_cite"]}
        support = [(p.file, p.heading) in must or any(has(p.text, t) for t in q["must_contain"]) for p in r.citations]
        rows.append({"id": q["id"], "answerable_key": q["answerable"], "answered": r.answerable, "text": r.text,
                     "cited": [(p.file, p.heading) for p in r.citations], "retrieved": [p.id for p in r.passages],
                     "relevant": [p.id for p in index.passages if (p.file, p.heading) in must],
                     "refusal_ok": q["answerable"] == r.answerable,
                     "contains_ok": (all(has(r.text, t) for t in q["must_contain"]) if q["answerable"] and r.answerable else None),
                     "citations_supported": (sum(support), len(support))})
    answerable = [x for x in rows if x["answerable_key"]]
    ranked, rel = [x["retrieved"] for x in answerable], [set(x["relevant"]) for x in answerable]
    answered = [x for x in rows if x["answered"]]
    return {"n": len(rows), "recall@5": recall_at_k(ranked, rel, 5), "mrr": mrr(ranked, rel),
            "refusal_accuracy": sum(x["refusal_ok"] for x in rows) / len(rows),
            "false_refusals": [x["id"] for x in rows if x["answerable_key"] and not x["answered"]],
            "false_answers": [x["id"] for x in rows if not x["answerable_key"] and x["answered"]],
            "must_contain_ok": f"{sum(bool(x['contains_ok']) for x in answered if x['answerable_key'])}/{sum(1 for x in answered if x['answerable_key'])}",
            "citations_supported": f"{sum(x['citations_supported'][0] for x in rows)}/{sum(x['citations_supported'][1] for x in rows)}",
            "rows": rows}


async def run_adversarial(index, llm, folder=ADV):
    qs = json.loads((folder / "questions.json").read_text())["questions"]
    rows = []
    for q in qs:
        r = await ask(AnswerEngine(index, llm), q["question"])
        refused = not r.answerable
        disagree = bool(re.search(r"disagree|conflict|contradict", r.text, re.I))
        leaked = [t for t in q["must_not_contain"] if has(r.text, t)]
        expect_ok = {"answer": not refused and any(has(r.text, t) for t in q["must_contain_any"]), "refuse": refused, "either": True}[q["expect"]]
        ok = expect_ok and (not leaked or (q["kind"] == "contradiction" and disagree))
        rows.append({"id": q["id"], "kind": q["kind"], "pass": ok, "refused": refused, "leaked": leaked, "text": r.text,
                     "cited": [p.file + " > " + p.heading for p in r.citations]})
    kinds = sorted({x["kind"] for x in rows})
    return {"n": len(rows), "pass": sum(x["pass"] for x in rows),
            "by_kind": {k: f"{sum(x['pass'] for x in rows if x['kind'] == k)}/{sum(x['kind'] == k for x in rows)}" for k in kinds},
            "rows": rows}


async def main(split):
    run = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    res = budget.reserve("usd", 0.05, label=f"answer_eval {run}")
    llm = make_live("llm", res)
    try:
        snapshot = Index(ingest(DOCS))
        held = await run_key(snapshot, llm, split)
        skipped = []
        mixed = Index(ingest(DOCS, extra=sorted((ADV / "pages").glob("*.md")), skipped=skipped))
        adv = await run_adversarial(mixed, llm)
        fresh_dir = DOCS.parent / "adversarial_fresh"
        fresh_skipped = []
        fresh = await run_adversarial(Index(ingest(DOCS, extra=sorted((fresh_dir / "pages").glob("*.md")), skipped=fresh_skipped)), llm, fresh_dir)
    finally:
        budget.settle(res, round(llm.cost_usd, 6), run_id=run, calls=llm.calls)
    out = {"run_id": run, "model": llm.model, "refusal_text": REFUSAL, split: held, "adversarial": {**adv, "skipped_at_ingest": skipped},
           "adversarial_fresh": {**fresh, "skipped_at_ingest": fresh_skipped},
           "llm_calls": llm.calls, "cost_usd": round(llm.cost_usd, 6)}
    (ROOT / "reports/docs_eval.json").write_text(json.dumps(out, indent=2) + "\n")
    print(json.dumps({split: {k: v for k, v in held.items() if k != "rows"},
                      "adversarial": {k: v for k, v in adv.items() if k != "rows"},
                      "adversarial_fresh": {k: v for k, v in fresh.items() if k != "rows"}, "cost_usd": out["cost_usd"]}, indent=2))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="holdout")
    asyncio.run(main(ap.parse_args().split))
