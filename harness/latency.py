"""Latency breakdown for a WSS run (S03-T06): uv run python harness/latency.py RUN_DIR

Joins each headless-client log with the orchestrator trace of the same session and prints one row per
turn plus nearest-rank p50/p95. Writes RUN_DIR/latency.json.
"""
import json
import sys
from pathlib import Path

from runner.wss import all_clips
from timeline import percentile, turn_breakdown

COLS = ["total_ms", "endpoint_delay_ms", "stt_settle_ms", "llm_first_token_ms", "tts_first_audio_ms", "residual_ms"]


def jsonl(p):
    return [json.loads(line) for line in p.read_text().splitlines() if line.strip()]


def main(run: Path):
    by_id = {c["id"]: c for c in all_clips()}
    rows = []
    for log in sorted((run / "clients").glob("*.jsonl")):
        client = jsonl(log)
        clip = by_id[log.stem.split("_", 1)[1]]
        sid = next((e["session_id"] for e in client if e["type"] == "welcome"), None)
        trace_file = run / "traces" / f"{sid}.jsonl"
        gens = sum(e["type"] == "agent.generation_started" for e in client)
        try:
            b = turn_breakdown(client, jsonl(trace_file), clip["labels"]["turn_end_ms"])
        except (StopIteration, FileNotFoundError) as e:
            rows.append({"clip": clip["id"], "generations": gens, "error": f"incomplete turn: {e!r}"})
            continue
        rows.append({"clip": clip["id"], "generations": gens, **{k: None if v is None else round(v, 1) for k, v in b.items()}})
    ok = [r for r in rows if "error" not in r]  # merged turns count, measured to the generation that played

    def pct(c, p):
        xs = [r[c] for r in ok if r[c] is not None]
        return percentile(xs, p) if xs else None

    summary = {c: {"p50": pct(c, 50), "p95": pct(c, 95)} for c in COLS} if ok else {}
    summary["turns_with_more_than_one_generation"] = [r["clip"] for r in rows if r.get("generations", 1) > 1]
    (run / "latency.json").write_text(json.dumps({"turns": rows, "summary": summary, "n": len(ok)}, indent=2) + "\n")
    print("| clip | " + " | ".join(COLS) + " |")
    print("|---|" + "---:|" * len(COLS))
    for r in rows:
        print(f"| {r['clip']} | " + (" | ".join(str(r[c]) for c in COLS) if "error" not in r else r["error"]) + (" | split" if r.get("generations", 1) > 1 else "") + " |")
    print("turns with >1 generation (merged or split):", summary.get("turns_with_more_than_one_generation"))
    for k in ("p50", "p95") if ok else ():
        print(f"| **{k}** (n={len(ok)}) | " + " | ".join(str(summary[c][k]) for c in COLS) + " |")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
