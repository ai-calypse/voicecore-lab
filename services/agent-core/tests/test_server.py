"""Orchestrator server wiring (Step 09). Process lifecycle tests (seam 14) join this file in Phase 2."""
import json

from voicecore import budget


def test_mock_billed_settles_literal_amounts():
    from voicecore.server import mock_billed_providers

    providers, settle = mock_billed_providers("s-1")
    assert {"stt", "llm", "tts", "tts_factory"} <= set(providers)
    assert budget.total("usd") == 0.0017  # reserved up front, like a live session
    for s in settle:
        s()
    entries = json.loads(budget.ledger_file().read_text())["entries"]
    assert sorted(e["amount"] for e in entries) == [0.0002, 0.0005, 0.001]
    assert {e["status"] for e in entries} == {"settled"}
    assert {e["label"] for e in entries} == {"mock-billed stt s-1", "mock-billed llm s-1", "mock-billed tts s-1"}
