# /// script
# requires-python = ">=3.11"
# dependencies = ["websockets>=14,<16"]
# ///
"""S00-T02 hosted control baseline against the Deepgram Voice Agent API.

Comparison only: Deepgram runs STT, LLM and TTS end to end; none of this is our engine.

Per session it measures WebSocket open, Welcome and SettingsApplied times. Per turn it
measures fixture speech end (voice) or InjectUserMessage send (text) to the first agent
audio frame received by this client, and checks the answer against expected keywords.
"First audio" means the first binary frame received here, not acoustic playback.

    uv run harness/baseline_deepgram.py --self-test   # offline checks, no network
    uv run harness/baseline_deepgram.py               # live; spends money, budget-guarded
"""
import argparse
import asyncio
import hashlib
import json
import math
import os
import platform
import re
import statistics
import subprocess
import sys
import time
import uuid
import wave
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "harness/config/baseline.json"
LEDGER = ROOT / "benchmarks/spend_ledger.json"
RESULTS = ROOT / "benchmarks/baseline_results.json"
RAW_DIR = ROOT / "benchmarks/raw"
AUDIO_CACHE = ROOT / ".cache/baseline_audio"  # generated locally with macOS `say`; not committed
RATE = 16000


def now_ms():
    return time.perf_counter() * 1000


def load_key():
    if os.environ.get("DEEPGRAM_API_KEY"):
        return os.environ["DEEPGRAM_API_KEY"]
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            k, _, v = line.partition("=")
            if k.strip() == "DEEPGRAM_API_KEY":
                return v.strip()
    sys.exit("DEEPGRAM_API_KEY not set and not in .env")


# --- budget -----------------------------------------------------------------

def session_cost(seconds, cfg):
    minutes = math.ceil(seconds / 60) if cfg["bill_whole_minutes"] else seconds / 60
    return round(minutes * cfg["price_per_minute_usd"], 4)


def can_afford(spent, cfg):
    # Worst case: the session runs until the max_session_seconds hard stop.
    return round(spent + session_cost(cfg["max_session_seconds"], cfg), 6) <= cfg["budget_usd"]


def load_ledger(cfg):
    if LEDGER.exists():
        return json.loads(LEDGER.read_text())
    return {
        "budget_usd": cfg["budget_usd"],
        "note": "Local estimate: connection seconds rounded up to whole minutes x list price. "
                "Not read from Deepgram billing (key lacks billing:read).",
        "entries": [],
        "total_estimated_usd": 0.0,
    }


def record_spend(ledger, entry):
    ledger["entries"].append(entry)
    ledger["total_estimated_usd"] = round(sum(e["estimated_usd"] for e in ledger["entries"]), 4)
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    LEDGER.write_text(json.dumps(ledger, indent=2) + "\n")


# --- scoring and audio ------------------------------------------------------

def matches(text, expect):
    """Every group must match one of its alternatives, at a word-ish boundary."""
    t = text.lower().replace("’", "'")

    def hit(alt):
        right = r"(?![0-9])" if alt[-1].isdigit() else r"(?![a-z])"  # "16kHz" ok, "160" not
        return re.search(r"(?<![a-z0-9])" + re.escape(alt.lower()) + right, t)

    return all(any(hit(alt) for alt in group) for group in expect)


def fixture(text, voice):
    AUDIO_CACHE.mkdir(parents=True, exist_ok=True)
    path = AUDIO_CACHE / (hashlib.sha256(f"{voice}|{text}".encode()).hexdigest()[:16] + ".wav")
    if not path.exists():
        subprocess.run(["say", "-v", voice, "-o", str(path), "--file-format=WAVE",
                        f"--data-format=LEI16@{RATE}", text], check=True)
    with wave.open(str(path)) as w:
        if (w.getnchannels(), w.getsampwidth(), w.getframerate()) != (1, 2, RATE):
            raise ValueError(f"{path}: expected mono PCM16 at {RATE} Hz")
        pcm = w.readframes(w.getnframes())
    return path, pcm


def frames(pcm, frame_ms):
    n = RATE * frame_ms // 1000 * 2
    out = [pcm[i:i + n] for i in range(0, len(pcm), n)]
    if out and len(out[-1]) < n:
        out[-1] += b"\0" * (n - len(out[-1]))
    return out


def last_voiced(frames_, threshold):
    for i in range(len(frames_) - 1, -1, -1):
        if max(abs(s) for s in memoryview(frames_[i]).cast("h")) >= threshold:  # little-endian host
            return i
    return None


# --- live session -----------------------------------------------------------

async def run_session(cfg, key, s, trace, fx):
    import websockets

    frame_ms = cfg["frame_ms"]
    silence = b"\0" * (RATE * frame_ms // 1000 * 2)
    welcome, applied, done = asyncio.Event(), asyncio.Event(), asyncio.Event()
    turn = None
    t0 = now_ms()

    def log(kind, **kw):
        trace.append({"t_ms": round(now_ms() - t0, 2), "session": s["session"], "kind": kind, **kw})

    async with websockets.connect(cfg["endpoint"], max_size=None,
                                  additional_headers={"Authorization": f"Token {key}"}) as ws:
        s["connect_ms"]["ws_open"] = round(now_ms() - t0, 1)
        log("ws_open")

        async def receiver():
            async for msg in ws:
                if isinstance(msg, bytes):
                    if turn is not None and turn["t_first_audio"] is None:
                        turn["t_first_audio"] = now_ms()
                        log("first_audio", turn=turn["id"], bytes=len(msg))
                    continue
                ev = json.loads(msg)
                typ = ev.get("type")
                log("event", type=typ, data={k: v for k, v in ev.items() if k != "type"})
                if typ == "Error":
                    s["error"] = ev
                    for e in (welcome, applied, done):
                        e.set()
                elif typ == "Welcome":
                    s["request_id"] = ev.get("request_id")
                    s["connect_ms"]["welcome"] = round(now_ms() - t0, 1)
                    welcome.set()
                elif typ == "SettingsApplied":
                    s["connect_ms"]["settings_applied"] = round(now_ms() - t0, 1)
                    applied.set()
                elif turn is None:
                    continue
                elif typ == "ConversationText":
                    turn.setdefault(ev.get("role"), []).append(ev.get("content", ""))
                elif typ == "LatencyReport":
                    # Deepgram sends one field per LatencyReport; merge them per turn.
                    turn.setdefault("latency_report", {}).update({k: v for k, v in ev.items() if k != "type"})
                elif typ == "AgentAudioDone":
                    done.set()

        rx = asyncio.create_task(receiver())
        await asyncio.wait_for(welcome.wait(), 10)
        await ws.send(json.dumps(cfg["settings"]))
        await asyncio.wait_for(applied.wait(), 10)
        if s["error"]:
            raise RuntimeError(f"provider error during setup: {s['error']}")

        next_t = now_ms()

        async def send_frame(f):
            # Real-time pacing: a frame goes out once its 20 ms of "capture" has elapsed.
            nonlocal next_t
            next_t += frame_ms
            await asyncio.sleep(max(0.0, (next_t - now_ms()) / 1000))
            await ws.send(f)

        for spec in cfg["turns"]:
            turn = {"id": spec["id"], "t_first_audio": None, "t_speech_end": None}
            done.clear()
            if spec["mode"] == "voice":
                fr, lv = fx[spec["id"]]["frames"], fx[spec["id"]]["last_voiced"]
                log("turn_start", turn=spec["id"])
                for i, f in enumerate(fr):
                    await send_frame(f)
                    if i == lv:
                        turn["t_speech_end"] = now_ms()
                        log("speech_end", turn=spec["id"])
            else:
                await ws.send(json.dumps({"type": "InjectUserMessage", "content": spec["text"]}))
                turn["t_speech_end"] = now_ms()
                log("text_injected", turn=spec["id"])
            deadline = now_ms() + cfg["turn_timeout_seconds"] * 1000
            while not done.is_set() and now_ms() < deadline:
                await send_frame(silence)
            for _ in range(25):  # 500 ms grace so a trailing LatencyReport lands in this turn
                await send_frame(silence)

            answer = " ".join(turn.get("assistant", []))
            fa, se = turn["t_first_audio"], turn["t_speech_end"]
            failure = ("provider_error" if s["error"] else
                       "timeout" if not done.is_set() else
                       "no_audio" if fa is None else
                       "no_answer_text" if not answer else
                       None if matches(answer, spec["expect"]) else "answer_mismatch")
            s["turns"].append({
                "id": spec["id"],
                "mode": spec["mode"],
                "speech_end_to_first_audio_ms": round(fa - se, 1) if fa and se else None,
                "provider_latency_report_s": turn.get("latency_report"),
                "user_transcript": " ".join(turn.get("user", [])),
                "assistant_text": answer,
                "success": failure is None,
                "failure": failure,
            })
            if s["error"]:
                break
        rx.cancel()


# --- results ----------------------------------------------------------------

def stats(xs):
    xs = [x for x in xs if x is not None]
    if not xs:
        return {"n": 0}
    return {"n": len(xs), "min": min(xs), "median": round(statistics.median(xs), 1), "max": max(xs)}


def summarize(sessions, turns_per_session):
    turns = [t for s in sessions for t in s["turns"]]
    planned = len(sessions) * turns_per_session  # turns lost to a failed session count as failures
    lat = lambda mode: [t["speech_end_to_first_audio_ms"] for t in turns if t["mode"] == mode]
    return {
        "sessions": len(sessions),
        "sessions_with_error": sum(1 for s in sessions if s["error"]),
        "planned_turns": planned,
        "attempted_turns": len(turns),
        "successful_turns": sum(t["success"] for t in turns),
        "turn_success_rate": round(sum(t["success"] for t in turns) / planned, 3) if planned else None,
        "voice_speech_end_to_first_audio_ms": stats(lat("voice")),
        "text_inject_to_first_audio_ms": stats(lat("text")),
        "ws_open_ms": stats([s["connect_ms"].get("ws_open") for s in sessions]),
        "welcome_ms": stats([s["connect_ms"].get("welcome") for s in sessions]),
        "settings_applied_ms": stats([s["connect_ms"].get("settings_applied") for s in sessions]),
    }


def git_rev():
    try:
        rev = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True).stdout
        return rev + ("-dirty" if dirty.strip() else "")
    except OSError:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--sessions", type=int)
    a = ap.parse_args()
    if a.self_test:
        return self_test()

    import websockets
    cfg = json.loads(CONFIG.read_text())
    key = load_key()
    fx = {}
    for t in cfg["turns"]:
        if t["mode"] == "voice":
            path, pcm = fixture(t["text"], cfg["say_voice"])
            fr = frames(pcm, cfg["frame_ms"])
            lv = last_voiced(fr, cfg["voiced_peak_threshold"])
            if lv is None:
                sys.exit(f"{path}: no voiced frame")
            fx[t["id"]] = {"frames": fr, "last_voiced": lv, "meta": {
                "text": t["text"], "voice": cfg["say_voice"], "generator": "macOS say",
                "sha256": hashlib.sha256(pcm).hexdigest(), "duration_ms": len(fr) * cfg["frame_ms"],
                "speech_end_ms": (lv + 1) * cfg["frame_ms"]}}

    ledger = load_ledger(cfg)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:6]
    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    trace, sessions, budget_stop = [], [], False
    for i in range(a.sessions or cfg["sessions"]):
        if not can_afford(ledger["total_estimated_usd"], cfg):
            budget_stop = True
            print(f"budget stop: spent ${ledger['total_estimated_usd']} of ${cfg['budget_usd']}")
            break
        if i:
            # Back-to-back sessions hit FAILED_TO_START_LISTENING in run 20261029T180621Z.
            time.sleep(cfg["session_gap_seconds"])
        s = {"session": i, "request_id": None, "connect_ms": {}, "turns": [], "error": None}
        sessions.append(s)
        t = time.monotonic()
        try:
            asyncio.run(asyncio.wait_for(run_session(cfg, key, s, trace, fx), cfg["max_session_seconds"]))
        except Exception as e:  # recorded, never hidden
            s["error"] = s["error"] or repr(e)
        finally:
            secs = round(time.monotonic() - t, 2)
            s["connected_seconds"] = secs
            record_spend(ledger, {"run_id": run_id, "session": i, "request_id": s["request_id"],
                                  "connected_seconds": secs, "estimated_usd": session_cost(secs, cfg)})
        print(f"session {i}: {sum(x['success'] for x in s['turns'])}/{len(s['turns'])} turns ok, "
              f"{secs}s, error={s['error']}")

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    raw = RAW_DIR / f"baseline_{run_id}.jsonl"
    raw.write_text("".join(json.dumps(e) + "\n" for e in trace))
    results = {
        "run_id": run_id,
        "started_utc": started,
        "task": "S00-T02 hosted control baseline (comparison only)",
        "source_revision": git_rev(),
        "config": {"path": str(CONFIG.relative_to(ROOT)),
                   "sha256": hashlib.sha256(CONFIG.read_bytes()).hexdigest()},
        "provider": {"endpoint": cfg["endpoint"],
                     "listen": cfg["settings"]["agent"]["listen"]["provider"],
                     "think": cfg["settings"]["agent"]["think"]["provider"],
                     "speak": cfg["settings"]["agent"]["speak"]["provider"]},
        "environment": {"platform": platform.platform(), "python": platform.python_version(),
                        "websockets": websockets.__version__,
                        "network": "unshaped residential WAN; default (US) endpoint; no clock sync needed (single client clock)"},
        "measurement_notes": [
            "All times are from one client monotonic clock (time.perf_counter).",
            "speech_end = send time of the last fixture frame with |sample| >= voiced_peak_threshold, paced in real time at frame_ms.",
            "first_audio = first binary agent audio frame received by this client; not acoustic playback, no playout buffer.",
            "Includes uplink and downlink network time. provider_latency_report_s is Deepgram's own report, not our measurement.",
            "Small sample: min/median/max only; no percentiles claimed.",
        ],
        "fixtures": {k: v["meta"] for k, v in fx.items()},
        "summary": summarize(sessions, len(cfg["turns"])),
        "sessions": sessions,
        "budget": {"budget_usd": cfg["budget_usd"], "budget_stop": budget_stop,
                   "this_run_estimated_usd": round(sum(e["estimated_usd"] for e in ledger["entries"]
                                                       if e["run_id"] == run_id), 4),
                   "ledger_total_estimated_usd": ledger["total_estimated_usd"]},
        "raw_trace": str(raw.relative_to(ROOT)),
    }
    RESULTS.write_text(json.dumps(results, indent=2) + "\n")
    print(json.dumps(results["summary"], indent=2))
    print(f"results: {RESULTS.relative_to(ROOT)}  trace: {raw.relative_to(ROOT)}  "
          f"spent this run: ${results['budget']['this_run_estimated_usd']}  total: ${ledger['total_estimated_usd']}")


def self_test():
    cfg = {"price_per_minute_usd": 0.075, "bill_whole_minutes": True, "max_session_seconds": 120, "budget_usd": 2.0}
    assert session_cost(1, cfg) == 0.075 and session_cost(60, cfg) == 0.075 and session_cost(61, cfg) == 0.15
    assert can_afford(1.85, cfg) and not can_afford(1.851, cfg)  # worst case 2 min = $0.15
    assert matches("PCM16 mono at 16kHz.", [["pcm"], ["16"]])
    assert not matches("PCM at 160 Hz", [["pcm"], ["16"]])
    assert matches("It is written in Go.", [["go"]]) and not matches("It is going well", [["go"]])
    assert matches("I couldn’t find that in the docs.", [["couldn't find", "could not find"]])
    assert matches("within 250ms", [["250"]]) and not matches("about 2500 ms", [["250"]])
    fr = frames(b"\x01\x00" * 330, 20)  # 330 samples -> 2 frames of 320, last zero-padded
    assert len(fr) == 2 and all(len(f) == 640 for f in fr)
    loud = (2000).to_bytes(2, "little", signed=True) * 320
    assert last_voiced([loud, b"\0" * 640], 500) == 0 and last_voiced([b"\0" * 640], 500) is None
    print("self-test ok")


if __name__ == "__main__":
    main()
