"""Do plain Deepgram listen sockets fail back to back like the Voice Agent did (FAILED_TO_START_LISTENING)?

    uv run python harness/listen_repro.py [-n 10]

Opens n live STT sessions one after another, streams 3 s of a fixture each, and records whether a
final transcript came back. Spend is reserved in the usd pool first.
"""
import argparse
import asyncio
import json
import time
from datetime import UTC, datetime

from fixtures import ROOT, load_manifest, read_pcm

from voicecore import budget
from voicecore.providers.base import Final, ProviderError
from voicecore.providers.deepgram_stt import PRICE_PER_MIN
from voicecore.providers.factory import make_live

SECONDS = 3


async def one(res, pcm):
    stt = make_live("stt", res)
    t0 = time.monotonic()
    finals, error = [], None
    try:
        for i in range(0, len(pcm), 320):
            await stt.send(pcm[i : i + 320].tobytes())
        await stt.close()
        finals = [e.text async for e in stt.events() if isinstance(e, Final)]
    except ProviderError as e:
        error = str(e)
    return {"request_id": stt.request_id, "ok": bool(finals) and error is None, "error": error, "finals": finals,
            "seconds": round(time.monotonic() - t0, 3), "audio_s": stt.audio_s, "cost_usd": stt.cost_usd()}


async def main(n):
    clip = next(c for c in load_manifest()["clips"] if c["id"] == "dev_single_01")
    pcm = read_pcm(clip)[16000 * 1 : 16000 * (1 + SECONDS)]  # skip the 1 s lead-in
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    res = budget.reserve("usd", round(n * SECONDS / 60 * PRICE_PER_MIN * 1.5, 6), label=f"listen_repro {run_id}")
    rows = []
    try:
        for _ in range(n):
            rows.append(await one(res, pcm))
    finally:
        budget.settle(res, round(sum(r["cost_usd"] for r in rows), 6), run_id=run_id, request_ids=[r["request_id"] for r in rows])
    out = ROOT / f"benchmarks/raw/listen_repro_{run_id}.json"
    out.write_text(json.dumps({"run_id": run_id, "sessions": rows}, indent=2) + "\n")
    print(f"{sum(r['ok'] for r in rows)}/{n} ok -> {out.relative_to(ROOT)}")
    for r in rows:
        print(r["ok"], r["request_id"], r["seconds"], r["error"] or r["finals"][:1])


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", type=int, default=10)
    asyncio.run(main(ap.parse_args().n))
