"""Repo-wide pytest fixtures."""
import pytest


@pytest.fixture(autouse=True)
def _temporary_spend_ledger(request, tmp_path, monkeypatch):
    """Only live tests (which really spend) may write benchmarks/spend_ledger.json; everything else gets a tmp ledger."""
    if request.node.get_closest_marker("live") is None:
        monkeypatch.setenv("VOICECORE_LEDGER", str(tmp_path / "spend_ledger.json"))
