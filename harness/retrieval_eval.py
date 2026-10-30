"""Offline retrieval eval (S04-T02): uv run python harness/retrieval_eval.py [--split dev]

No LLM. For each answerable question, relevant passages are the answer key's must_cite (file + heading).
Writes reports/retrieval_<split>.json; prints Recall@1/5/10 and MRR for lexical, dense and fused rankings.
"""
import argparse
import json

from fixtures import ROOT
from timeline import mrr, recall_at_k

from voicecore.answer.index import Index, rrf
from voicecore.answer.ingest import ingest


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="dev")
    args = ap.parse_args()
    index = Index(ingest(ROOT / "fixtures/docs/uv"))
    key = json.loads((ROOT / "fixtures/docs/answer_key.json").read_text())["questions"]
    qs = [q for q in key if q["split"] == args.split and q["answerable"]]
    rel = [{p.id for p in index.passages for c in q["must_cite"] if (p.file, p.heading) == (c["file"], c["heading"])} for q in qs]
    assert all(rel), "every must_cite must map to a passage"
    runs = {}
    for name in ("lexical", "dense", "fused"):
        ranked = []
        for q in qs:
            lex = [p.id for p in index.lexical(q["question"], 20)]
            den = [p.id for p in index.dense(q["question"], 20)]
            ranked.append({"lexical": lex, "dense": den, "fused": rrf([lex, den])}[name])
        runs[name] = {"recall@1": recall_at_k(ranked, rel, 1), "recall@5": recall_at_k(ranked, rel, 5),
                      "recall@10": recall_at_k(ranked, rel, 10), "mrr": mrr(ranked, rel),
                      "misses@5": [q["id"] for q, r, g in zip(qs, ranked, rel) if not set(r[:5]) & g]}
    out = {"split": args.split, "n": len(qs), "passages": len(index.passages), "runs": runs}
    (ROOT / f"reports/retrieval_{args.split}.json").write_text(json.dumps(out, indent=2) + "\n")
    for name, r in runs.items():
        print(f"{name:8s} R@1 {r['recall@1']:.2f}  R@5 {r['recall@5']:.2f}  R@10 {r['recall@10']:.2f}  MRR {r['mrr']:.3f}  misses@5 {r['misses@5']}")


if __name__ == "__main__":
    main()
