"""Smoke test for a running stack: uv run python harness/smoke.py [--gateway http://localhost:8080]

Gets a token, opens the browser-facing WebSocket, asks one question by text and waits for a cited answer.
Exit 0 on success. Used by the README and the CI compose job.
"""
import argparse
import asyncio
import json
import sys
import urllib.request

from websockets.asyncio.client import connect


async def main(gateway: str, timeout: float) -> int:
    with urllib.request.urlopen(urllib.request.Request(f"{gateway}/v1/session", method="POST"), timeout=10) as r:
        token = json.load(r)["token"]
    async with connect(gateway.replace("http", "ws", 1) + "/v1/ws") as ws:  # no Origin: not a browser
        await ws.send(json.dumps({"type": "hello", "version": 1, "token": token, "mic": {"rate": 16000, "frame_ms": 20}, "playout": {"rate": 24000}}))
        await ws.send(json.dumps({"type": "text.input", "text": "How do I install uv?"}))
        sources = []
        async with asyncio.timeout(timeout):
            async for m in ws:
                if isinstance(m, bytes):
                    continue
                e = json.loads(m)
                if e["type"] == "answer.sources":
                    sources = e["sources"]
                if e["type"] == "agent.text":
                    print("answer:", e["text"])
                    print("sources:", [s["url"] for s in sources])
                    return 0 if sources else 1
    return 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--gateway", default="http://localhost:8080")
    ap.add_argument("--timeout", type=float, default=60)
    a = ap.parse_args()
    sys.exit(asyncio.run(main(a.gateway, a.timeout)))
