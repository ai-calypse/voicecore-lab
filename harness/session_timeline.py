"""One aligned timeline per session of a WSS run (S06-T01): uv run python harness/session_timeline.py RUN_DIR

Reference clock: the client's. Gateway offset from the client's ping/pong (NTP style, min round trip).
Agent-core offset from mic frames (min arrival - capture end), so it includes the smallest one-way uplink
delay (labelled derived). Writes RUN_DIR/timelines/<session>.json, the input of the demo's ?lab=1 panel.
"""
import json
import sys
from pathlib import Path

from timeline import merge, ntp_offset

CLIENT_SPAN = {"playout.started": "playout", "playout.stopped": "playout", "cancel.ack": "playout", "mic.start": "capture",
               "user.onset": "capture", "text.input": "turn"}


def jsonl(p):
    return [json.loads(line) for line in Path(p).read_text().splitlines() if line.strip()] if Path(p).exists() else []


def client_events(log):
    out = []
    for e in log:
        if e.get("type") in ("pong", "client.start", "client.end", "socket.closed"):
            continue
        attrs = {k: v for k, v in e.items() if k not in ("type", "t_us", "process", "gen", "dir")}
        ev = {"trace_id": None, "process": "client", "span": CLIENT_SPAN.get(e["type"], "client"), "event": e["type"],
              "t_mono_us": e["t_us"], "attrs": {**attrs, "dir": e.get("dir")}}
        if e.get("gen") is not None:
            ev["generation_id"] = e["gen"]
        out.append(ev)
    return out


def session_timeline(client_log, gateway_trace, agent_trace):
    sid = next(e["session_id"] for e in client_log if e.get("type") == "welcome")
    pongs = [(e["t_client_us"], e["t_server_us"], e["t_us"]) for e in client_log if e.get("type") == "pong"]
    gw = [e for e in gateway_trace if e["trace_id"] == sid]
    lags = [e["attrs"]["client_to_agent_us"] for e in agent_trace if e["span"] == "clock"]
    offsets = {"client": 0, "gateway": -ntp_offset(pongs) if pongs else 0, "agent-core": -min(lags) if lags else 0}
    events = merge({"client": client_events(client_log), "gateway": gw if pongs else [], "agent-core": agent_trace if lags else []}, offsets)
    return {"session_id": sid, "reference_clock": "client", "offsets_us": offsets,
            "offset_notes": {"gateway": "ntp from ping/pong", "agent-core": "derived: min(arrival - capture end) of mic frames, includes the smallest uplink delay"},
            "events": [{**e, "trace_id": sid} for e in events]}


def main(run: Path):
    gateway_trace = jsonl(run / "gateway_trace.jsonl")
    (run / "timelines").mkdir(exist_ok=True)
    for log in sorted((run / "clients").glob("*.jsonl")):
        client = jsonl(log)
        if not any(e.get("type") == "welcome" for e in client):
            continue
        sid = next(e["session_id"] for e in client if e.get("type") == "welcome")
        t = session_timeline(client, gateway_trace, jsonl(run / "traces" / f"{sid}.jsonl"))
        (run / "timelines" / f"{sid}.json").write_text(json.dumps(t, indent=1) + "\n")
        print(sid, len(t["events"]), "events", t["offsets_us"])


if __name__ == "__main__":
    main(Path(sys.argv[1]))
