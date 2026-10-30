"""Interruption benchmark, fake providers (S05-T04): uv run python harness/barge_bench.py

Every interrupt clip at 0/20/50/100 ms one-way network delay, plus every echo-only clip at 50 ms, in-process
on fake time (Silero VAD and the echo gate are real). interrupt-to-silence = labelled user onset -> the client's
playout.stopped(cancel); interrupt-to-listening = onset -> the client receives user.speech_started.
Writes reports/barge_in_fake.json.
"""
import json

import looptime
from fixtures import ROOT, load_manifest
from runner.inprocess import run_barge_in
from timeline import percentile

DELAYS = (0, 20, 50, 100)


async def main():
    clips = load_manifest()["clips"]
    rows = []
    for c in [c for c in clips if c["category"] == "interrupt"]:
        for net in DELAYS:
            r = await run_barge_in(c, clips=clips, net_ms=net)
            rows.append({"clip": c["id"], "net_ms": net, "interrupt_to_silence_ms": r["interrupt_to_silence_ms"],
                         "interrupt_to_listening_ms": r["interrupt_to_listening_ms"], "stopped": r["stopped"]})
    for c in [c for c in clips if c["category"] == "echo_only"]:
        r = await run_barge_in(c, clips=clips, net_ms=50)
        rows.append({"clip": c["id"], "net_ms": 50, "false_barge_in": r["barge_in_ms"] is not None, "stopped": r["stopped"]})
    hits = [r for r in rows if "interrupt_to_silence_ms" in r]
    summary = {"scripts": len(rows), "interrupts": len(hits), "silenced": sum(r["interrupt_to_silence_ms"] is not None for r in hits),
               "false_barge_ins": f"{sum(r.get('false_barge_in', False) for r in rows)}/{len(rows) - len(hits)}"}
    for net in DELAYS:
        xs = [r["interrupt_to_silence_ms"] for r in hits if r["net_ms"] == net and r["interrupt_to_silence_ms"] is not None]
        ls = [r["interrupt_to_listening_ms"] for r in hits if r["net_ms"] == net and r["interrupt_to_listening_ms"] is not None]
        summary[f"net_{net}ms"] = {"silence_p50": percentile(xs, 50), "silence_max": max(xs), "listening_p50": percentile(ls, 50), "n": len(xs)}
    (ROOT / "reports/barge_in_fake.json").write_text(json.dumps({"summary": summary, "rows": rows}, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    loop = looptime.new_event_loop()
    loop.run_until_complete(main())
