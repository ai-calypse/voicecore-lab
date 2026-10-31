"""Agent bundles (Step 10, seam 21): the index can take prebuilt vectors and shares one embedding model."""
from pathlib import Path

import numpy as np

from voicecore.answer.index import Index
from voicecore.answer.ingest import docusaurus, ingest

ACME = Path(__file__).resolve().parents[3] / "fixtures/docs/acme"


def acme_passages():
    return ingest(ACME, site=docusaurus("https://docs.acme.test/"))


def test_index_accepts_vectors(tmp_path, monkeypatch):
    monkeypatch.setenv("VOICECORE_VECTORS_DIR", str(tmp_path))
    p2 = acme_passages()[:2]
    index = Index(p2, vectors=np.ones((2, 384), np.float32))
    assert index.vectors.shape == (2, 384)
    assert list(tmp_path.iterdir()) == []  # prebuilt vectors are not embedded or cached again


def test_indexes_share_one_embedder():
    p = acme_passages()
    a = Index(p[:1], vectors=np.ones((1, 384), np.float32))
    b = Index(p[1:2], vectors=np.ones((1, 384), np.float32))
    assert a._embedder() is b._embedder()


FIXTURE = Path(__file__).resolve().parents[3] / "fixtures/agents"
CONFIG = {"name": "Acme Docs", "docs_url": "https://docs.acme.test/", "instructions": "", "first_message": None,
          "voice": "aura-2-thalia-en", "llm": "openai/gpt-oss-120b", "keyterms": []}


def test_bundle_golden_read():
    from voicecore import agents

    version = agents.current(FIXTURE, "acme-docs")
    b = agents.read(FIXTURE, "acme-docs", version)
    assert b.config["name"] == "Acme Docs"
    assert len(b.passages) == 3
    assert b.vectors.shape == (3, 384)


def test_publish_same_content_same_version(tmp_path):
    from voicecore import agents

    p = acme_passages()
    v = np.ones((3, 384), np.float32)
    first = agents.publish(tmp_path, "acme-docs", CONFIG, p, v)
    second = agents.publish(tmp_path, "acme-docs", CONFIG, p, v)
    assert first == second
    assert agents.current(tmp_path, "acme-docs") == first


def test_prune_keeps_five(tmp_path):
    from voicecore import agents

    p = acme_passages()
    v = np.ones((3, 384), np.float32)
    for i in range(7):
        last = agents.publish(tmp_path, "acme-docs", {**CONFIG, "name": f"Acme {i}"}, p, v)
    versions = [d.name for d in (tmp_path / "acme-docs").iterdir() if d.is_dir()]
    assert len(versions) == 5
    assert last in versions


def test_disable_removes_pointer(tmp_path):
    from voicecore import agents

    agents.publish(tmp_path, "acme-docs", CONFIG, acme_passages(), np.ones((3, 384), np.float32))
    agents.disable(tmp_path, "acme-docs")
    assert agents.current(tmp_path, "acme-docs") is None
