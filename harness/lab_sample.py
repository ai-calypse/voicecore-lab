"""Sample timeline for the demo's ?lab=1 panel: uv run python harness/lab_sample.py

One mock-provider session through the real gateway and orchestrator: the client asks by text, hears its own
playback (-15 dB), and a user clip interrupts 1.2 s in, so the timeline has an interrupted and a completed
generation. Writes apps/demo/public/lab/sample-timeline.json (label: fake-provider).
"""
import json
import signal
import subprocess
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import MANIFEST, ROOT, load_manifest  # noqa: E402
from runner.wss import CLIENT, COUNTERS_URL, start_stack  # noqa: E402
from session_timeline import jsonl, session_timeline  # noqa: E402

OUT = ROOT / ".cache/lab_sample"


def main():
    (OUT / "traces").mkdir(parents=True, exist_ok=True)
    for f in [OUT / "gateway_trace.jsonl", *(OUT / "traces").glob("*.jsonl")]:
        f.unlink(missing_ok=True)
    clip = next(c for c in load_manifest()["clips"] if c["id"] == "dev_single_02")
    procs = start_stack("mock", OUT / "traces", OUT)
    try:
        subprocess.run(["node", str(CLIENT), "--text", "How do I install uv?", "--echo-db=-15", "--fixture", str(MANIFEST.parent / clip["file"]),
                        "--interrupt-after", "1200", "--onset-ms", str(clip["labels"]["speech"][0][0]), "--tail", "8",
                        "--out", str(OUT / "client.jsonl")], cwd=ROOT, check=True, timeout=120)
        counters = json.loads(urllib.request.urlopen(COUNTERS_URL).read())
    finally:
        for p in procs:
            p.send_signal(signal.SIGINT)
        for p in procs:
            p.wait(timeout=20)
    client = jsonl(OUT / "client.jsonl")
    sid = next(e["session_id"] for e in client if e["type"] == "welcome")
    t = session_timeline(client, jsonl(OUT / "gateway_trace.jsonl"), jsonl(OUT / "traces" / f"{sid}.jsonl"))
    t["label"] = "fake-provider (mock STT/LLM/TTS), real gateway, orchestrator, Silero VAD and SDK client"
    t["gateway_counters"] = counters
    path = ROOT / "apps/demo/public/lab/sample-timeline.json"
    path.write_text(json.dumps(t, indent=1) + "\n")
    print(path, len(t["events"]), "events")


if __name__ == "__main__":
    main()
