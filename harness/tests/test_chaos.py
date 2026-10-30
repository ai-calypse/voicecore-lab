"""S05-T05 (seam 9a): a fault schedule with a seed gives the same trace twice, in fake time."""
import pytest
from runner.chaos import SCENARIOS, normalized, run_scenario

from voicecore.runtime.session import REPROMPT

pytestmark = pytest.mark.looptime


async def test_stall_and_429_with_seed_42_gives_an_identical_trace_twice():
    path = SCENARIOS / "chaos/stall_and_429.json"
    a, b = await run_scenario(path), await run_scenario(path)
    assert normalized(a) == normalized(b)
    events = [(e["span"], e["event"]) for e in a["trace"]]
    assert ("llm", "backoff") in events and ("llm", "stall") in events  # both injected faults happened
    texts = [e["text"] for e in a["client"] if e["type"] == "agent.text"]
    assert len(texts) == 1 and texts[0].endswith(REPROMPT)
