"""Chaos scenarios (S05-T05): a JSON fault schedule plus a seed drive the mock providers of one in-process run.

Faults come only from mock configuration; network faults belong to the WSS/dummynet benchmarks.
"""
import json
import random
from collections import Counter
from pathlib import Path

from fixtures import load_manifest

from voicecore.providers.base import ProviderError
from voicecore.providers.mock import LLMScript, MockLLM, MockSTT, MockTTS
from voicecore.resilience import Breaker
from voicecore.runtime.session import BUSY, REPROMPT, TROUBLE, VOICE_INPUT_DOWN

from .inprocess import DEFAULT_ANSWER, run_clip, scripted_stt

SCENARIOS = Path(__file__).resolve().parents[1] / "scenarios"


def build(scenario: dict, clip: dict):
    """The mock LLM and TTS for a scenario, plus Session options: an STT that drops (stt_error_after_ms) with its
    reconnect factory, and breakers with the scenario's settings."""
    rng = random.Random(scenario["seed"])
    plan = list(scenario.get("llm_calls", []))
    tokens = [w + " " for w in DEFAULT_ANSWER.split()]

    def script(_messages):
        fault = plan.pop(0) if plan else {}
        return LLMScript(tokens=tokens, first_token_ms=rng.randint(*scenario["llm_first_token_ms"]),
                         token_ms=rng.randint(*scenario["llm_token_ms"]), stall_after=fault.get("stall_after"),
                         error=ProviderError(fault["error"], "injected") if "error" in fault else None)

    kw = {}
    if "stt_error_after_ms" in scenario:
        kw["stt"] = MockSTT(canned=clip.get("transcript"), error_after_ms=scenario["stt_error_after_ms"])
        kw["stt_factory"] = lambda: scripted_stt(clip)
    if "breakers" in scenario:
        kw["breakers"] = {p: Breaker(p, **cfg) for p, cfg in scenario["breakers"].items()}
    return MockLLM(script), MockTTS(first_audio_ms=rng.randint(*scenario["tts_first_audio_ms"])), kw


async def run_scenario(path: Path) -> dict:
    scenario = json.loads(path.read_text())
    clip = next(c for c in load_manifest()["clips"] if c["id"] == scenario["clip"])
    llm, tts, kw = build(scenario, clip)
    return await run_clip(clip, llm=llm, tts=tts, **kw)


def verify(scenario: dict, run: dict) -> list[str]:
    """A scenario's literal expectations ("expect"): trace event counts and what the user was told."""
    exp, name = scenario.get("expect", {}), scenario["name"]
    counts = Counter(f'{e["span"]}/{e["event"]}' for e in run["trace"])
    fails = [f"{name}: {k} x{counts[k]}, want {n}" for k, n in exp.get("trace_counts", {}).items() if counts[k] != n]
    texts = [e["text"] for e in run["client"] if e["type"] == "agent.text"]
    notices = {"busy": BUSY, "reprompt": REPROMPT}
    want = exp.get("reply")
    if want == "answer":  # a real answer: not a notice, and not an answer that ended in a failure notice
        if not texts or any(texts[0].endswith(n) for n in (BUSY, REPROMPT, TROUBLE, VOICE_INPUT_DOWN)):
            fails.append(f"{name}: replies {texts}, want an answer")
    elif want in notices:
        if texts != [notices[want]]:
            fails.append(f"{name}: replies {texts}, want {want}")
    elif want is not None:
        fails.append(f"{name}: unknown expected reply {want!r}")
    return fails


def normalized(run: dict) -> list:
    """Trace and client log with times relative to the run's first trace event (us). Compare runs that each had
    their own fresh fake-time loop: the same float times then give the same integers."""
    t0 = run["trace"][0]["t_mono_us"]
    stamps = {"t_mono_us", "t_us", "capture_end_us", "t_client_us", "t_server_us", "onset_us"}  # times, not durations
    def rel(d):
        return {k: v - t0 if k in stamps and isinstance(v, int) else v for k, v in d.items()}
    trace = [{**rel(e), "attrs": rel(e["attrs"])} for e in run["trace"]]
    return [trace, [rel(e) for e in run["client"]]]
