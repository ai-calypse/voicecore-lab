"""Agent bundles (ADR 0005): what the console publishes and the voice side reads.

agents/<id>/<version>/{config.json, passages.jsonl, vectors.npy} plus agents/<id>/current, a file naming the live
version. A version is a hash of config and corpus, so the same content always gets the same version. Publishing
writes a temporary folder, renames it, then replaces the pointer, so a reader never sees half a bundle. This
module is the only owner of the format.
"""
import hashlib
import json
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

from voicecore.answer.ingest import Passage

FORMAT = 1
KEEP = 5  # versions kept per agent, the live one always among them
POINTER = "current"


@dataclass(frozen=True)
class Bundle:
    agent: str
    version: str
    config: dict
    passages: list[Passage]
    vectors: np.ndarray


def version_of(config: dict, passages: list[Passage]) -> str:
    h = hashlib.sha256(json.dumps(config, sort_keys=True).encode())
    for p in passages:
        h.update(p.sha256.encode())
    return h.hexdigest()[:12]


def publish(root: Path, agent: str, config: dict, passages: list[Passage], vectors: np.ndarray) -> str:
    """Write the bundle (if new), point `current` at it, prune old versions. Returns the version."""
    config = {**config, "format": FORMAT}
    version = version_of(config, passages)
    home = Path(root) / agent
    target = home / version
    home.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        tmp = Path(tempfile.mkdtemp(prefix=".tmp-", dir=home))
        (tmp / "config.json").write_text(json.dumps(config, indent=2, sort_keys=True) + "\n")
        (tmp / "passages.jsonl").write_text("".join(json.dumps(asdict(p)) + "\n" for p in passages))
        np.save(tmp / "vectors.npy", np.asarray(vectors, np.float32))
        os.rename(tmp, target)
    else:
        os.utime(target)  # republishing an old version makes it the newest again for pruning
    pointer = home / f".{POINTER}.tmp"
    pointer.write_text(version + "\n")
    os.replace(pointer, home / POINTER)
    prune(root, agent)
    return version


def current(root: Path, agent: str) -> str | None:
    try:
        return (Path(root) / agent / POINTER).read_text().strip() or None
    except FileNotFoundError:
        return None


def read(root: Path, agent: str, version: str) -> Bundle:
    d = Path(root) / agent / version
    config = json.loads((d / "config.json").read_text())
    passages = [Passage(**json.loads(line)) for line in (d / "passages.jsonl").read_text().splitlines() if line]
    return Bundle(agent, version, config, passages, np.load(d / "vectors.npy"))


def prune(root: Path, agent: str, keep: int = KEEP) -> None:
    home = Path(root) / agent
    live = current(root, agent)
    versions = sorted((d for d in home.iterdir() if d.is_dir() and not d.name.startswith(".")),
                      key=lambda d: (d.stat().st_mtime_ns, d.name), reverse=True)
    for d in versions[keep:]:
        if d.name != live:
            for f in d.iterdir():
                f.unlink()
            d.rmdir()


def disable(root: Path, agent: str) -> None:
    """New sessions for this agent are refused; open sessions keep the bundle they loaded."""
    (Path(root) / agent / POINTER).unlink(missing_ok=True)
