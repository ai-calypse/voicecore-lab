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


def test_mock_billed_refused_leaves_nothing_reserved(tmp_path, monkeypatch):
    import pytest

    from voicecore.server import mock_billed_providers

    path = tmp_path / "near_cap.json"
    path.write_text(json.dumps({"entries": [{"pool": "usd", "amount": 4.9988}]}))  # stt fits, llm does not
    monkeypatch.setenv("VOICECORE_LEDGER", str(path))
    with pytest.raises(budget.BudgetExceeded):
        mock_billed_providers("s-2")
    assert [e for e in json.loads(path.read_text())["entries"] if "label" in e] == []
