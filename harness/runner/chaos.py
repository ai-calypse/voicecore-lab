"""Chaos scenarios (S05-T05): a JSON fault schedule plus a seed drive the mock providers of one in-process run.

Faults come only from mock configuration; network faults belong to the WSS/dummynet benchmarks.
"""
import json
import random
from pathlib import Path

from fixtures import load_manifest

from voicecore.providers.base import ProviderError
from voicecore.providers.mock import LLMScript, MockLLM, MockTTS

from .inprocess import DEFAULT_ANSWER, run_clip

SCENARIOS = Path(__file__).resolve().parents[1] / "scenarios"


def build(scenario: dict):
    rng = random.Random(scenario["seed"])
    plan = list(scenario.get("llm_calls", []))
    tokens = [w + " " for w in DEFAULT_ANSWER.split()]

    def script(_messages):
        fault = plan.pop(0) if plan else {}
        return LLMScript(tokens=tokens, first_token_ms=rng.randint(*scenario["llm_first_token_ms"]),
                         token_ms=rng.randint(*scenario["llm_token_ms"]), stall_after=fault.get("stall_after"),
                         error=ProviderError(fault["error"], "injected") if "error" in fault else None)

    return MockLLM(script), MockTTS(first_audio_ms=rng.randint(*scenario["tts_first_audio_ms"]))


async def run_scenario(path: Path) -> dict:
    scenario = json.loads(path.read_text())
    clip = next(c for c in load_manifest()["clips"] if c["id"] == scenario["clip"])
    llm, tts = build(scenario)
    return await run_clip(clip, llm=llm, tts=tts)


def normalized(run: dict) -> list:
    """Trace and client log with times relative to the run's first trace event (us). Compare runs that each had
    their own fresh fake-time loop: the same float times then give the same integers."""
    t0 = run["trace"][0]["t_mono_us"]
    stamps = {"t_mono_us", "t_us", "capture_end_us", "t_client_us", "t_server_us", "onset_us"}  # times, not durations
    def rel(d):
        return {k: v - t0 if k in stamps and isinstance(v, int) else v for k, v in d.items()}
    trace = [{**rel(e), "attrs": rel(e["attrs"])} for e in run["trace"]]
    return [trace, [rel(e) for e in run["client"]]]
