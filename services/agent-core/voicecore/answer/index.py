"""Hybrid retrieval (S04-T02): SQLite FTS5 BM25 + fastembed dense vectors, fused with reciprocal rank fusion."""
import functools
import hashlib
import os
import re
import sqlite3
import threading
from pathlib import Path

import numpy as np

from .ingest import Passage

CACHE = Path(__file__).resolve().parents[4] / ".cache"
MODEL = "BAAI/bge-small-en-v1.5"


@functools.cache
def embedder():
    """One embedding model per process, shared by every index (each agent has its own index)."""
    from fastembed import TextEmbedding

    return TextEmbedding(MODEL, cache_dir=str(CACHE / "fastembed"))


def vectors_dir() -> Path:
    """Where computed vectors are cached; VOICECORE_VECTORS_DIR when the image's own cache is read-only."""
    return Path(os.environ.get("VOICECORE_VECTORS_DIR") or CACHE)


def rrf(rankings: list[list[str]], k: int = 60) -> list[str]:
    """Reciprocal rank fusion: score = sum over rankings of 1 / (k + rank), rank from 1."""
    score: dict[str, float] = {}
    for ranking in rankings:
        for r, key in enumerate(ranking, 1):
            score[key] = score.get(key, 0.0) + 1 / (k + r)
    return sorted(score, key=lambda key: -score[key])


STOPWORDS = set("""a an and are as at be but by can could do does for from had has have how i if in into is it its me my
of on or our should so that the their them then there these this to was we what when where which who why will with would
you your""".split())


def fts_query(q: str) -> str:
    """Each word quoted, so FTS5 operators and punctuation in user text (., --, *, :) are plain terms.
    Question words are dropped: in an OR query they only add noise to BM25 (dev R@5 0.53 with them)."""
    words = re.findall(r"\w+", q.lower())
    return " OR ".join(f'"{t}"' for t in ([w for w in words if w not in STOPWORDS] or words))


class Index:
    def __init__(self, passages: list[Passage], vectors: np.ndarray | None = None):
        """vectors: prebuilt, one row per passage (an agent bundle); otherwise embedded here, cached by corpus."""
        self.passages = passages
        self.by_id = {p.id: p for p in passages}
        self.db = sqlite3.connect(":memory:", check_same_thread=False)
        self._db_lock = threading.Lock()  # retrieval runs in worker threads; one sqlite connection is shared
        self.db.execute("CREATE VIRTUAL TABLE p USING fts5(id UNINDEXED, title, body, tokenize='porter unicode61')")
        self.db.executemany("INSERT INTO p VALUES (?, ?, ?)", [(p.id, p.title, p.text) for p in passages])
        self.vectors = self._embed_passages() if vectors is None else vectors

    def _embedder(self):
        return embedder()

    def _embed_passages(self) -> np.ndarray:
        """Vectors are cached per corpus hash: re-embedding ~1,000 passages takes about 20 s on CPU."""
        key = hashlib.sha256("".join(p.sha256 for p in self.passages).encode()).hexdigest()[:16]
        path = vectors_dir() / f"answer_vectors_{key}.npy"
        if path.exists():
            return np.load(path)
        texts = [p.text[:2000] for p in self.passages]  # small batches: the default (256) ran out of memory in a 2 GB container
        v = np.array(list(self._embedder().passage_embed(texts, batch_size=16)), np.float32)
        v /= np.linalg.norm(v, axis=1, keepdims=True)
        path.parent.mkdir(parents=True, exist_ok=True)
        np.save(path, v)
        return v

    def lexical(self, q: str, k: int = 10) -> list[Passage]:
        query = fts_query(q)
        if not query:
            return []
        with self._db_lock:
            rows = self.db.execute("SELECT id FROM p WHERE p MATCH ? ORDER BY bm25(p) LIMIT ?", (query, k)).fetchall()
        return [self.by_id[r[0]] for r in rows]

    def dense(self, q: str, k: int = 10) -> list[Passage]:
        qv = np.array(next(iter(self._embedder().query_embed(q))), np.float32)
        scores = self.vectors @ (qv / np.linalg.norm(qv))
        return [self.passages[i] for i in np.argsort(-scores)[:k]]

    def search(self, q: str, k: int = 5) -> list[Passage]:
        fused = rrf([[p.id for p in self.lexical(q, 20)], [p.id for p in self.dense(q, 20)]])
        return [self.by_id[i] for i in fused[:k]]
