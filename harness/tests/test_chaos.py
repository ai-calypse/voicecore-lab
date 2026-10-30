"""S05-T05 (seam 9a): a fault schedule with a seed gives the same trace twice, in fake time."""
import looptime
from runner.chaos import SCENARIOS, normalized, run_scenario

from voicecore.runtime.session import REPROMPT


def fresh_loop(coro):
    """Each run gets its own fake-time loop starting at 0, so traces compare exactly (to the microsecond)."""
    loop = looptime.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def test_stall_and_429_with_seed_42_gives_an_identical_trace_twice():
    path = SCENARIOS / "chaos/stall_and_429.json"
    a, b = fresh_loop(run_scenario(path)), fresh_loop(run_scenario(path))
    assert normalized(a) == normalized(b)
    events = [(e["span"], e["event"]) for e in a["trace"]]
    assert ("llm", "backoff") in events and ("llm", "stall") in events  # both injected faults happened
    texts = [e["text"] for e in a["client"] if e["type"] == "agent.text"]
    assert len(texts) == 1 and texts[0].endswith(REPROMPT)


def test_stt_drop_and_llm_breaker_scenarios_meet_their_expectations():
    import json

    from runner.chaos import verify

    for name in ("stt_drop", "llm_breaker"):
        path = SCENARIOS / f"chaos/{name}.json"
        assert verify(json.loads(path.read_text()), fresh_loop(run_scenario(path))) == []
