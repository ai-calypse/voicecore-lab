"""Agent bundles (ADR 0005): what the console publishes and the voice side reads.

agents/<id>/<version>/{config.json, passages.jsonl, vectors.npy} plus agents/<id>/current, a file naming the live
version. A version is a hash of config and corpus, so the same content always gets the same version. Publishing
writes a temporary folder, renames it, then replaces the pointer, so a reader never sees half a bundle. This
module is the only owner of the format.
"""
import functools
import hashlib
import json
import os
import re
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

from voicecore.answer.index import Index
from voicecore.answer.ingest import Passage
from voicecore.providers import deepgram_tts, openai_compat_llm

FORMAT = 1
KEEP = 5  # versions kept per agent, the live one always among them
POINTER = "current"
ID = re.compile(r"[a-z0-9][a-z0-9-]{0,39}")  # also checked by the gateway; never a path separator or a dot
LIMITS = {"name": 80, "instructions": 2000, "first_message": 300}


def validate(config: dict) -> dict:
    """The settings a bundle may carry. Voice and model come from fixed catalogs, so cost estimates stay right."""
    if config.get("llm") not in openai_compat_llm.PRICES:
        raise ValueError(f"llm not in catalog: {config.get('llm')}")
    if config.get("voice") not in deepgram_tts.VOICES:
        raise ValueError(f"voice not in catalog: {config.get('voice')}")
    if not str(config.get("name") or "").strip():
        raise ValueError("name is required")
    for field, limit in LIMITS.items():
        if len(config.get(field) or "") > limit:
            raise ValueError(f"{field} is longer than {limit} characters")
    url = config.get("docs_url") or ""
    if url and not re.match(r"https?://[^\s/]+", url):
        raise ValueError(f"docs_url must be an http(s) URL: {url}")
    terms = config.get("keyterms") or []
    if len(terms) > 50 or any(not isinstance(t, str) or len(t) > 40 for t in terms):
        raise ValueError("keyterms: at most 50 words of up to 40 characters")
    return config


@dataclass(frozen=True)
class Bundle:
    agent: str
    version: str
    config: dict
    passages: list[Passage]
    vectors: np.ndarray


@dataclass(frozen=True)
class Agent:
    """What a session needs from an agent. The default agent (the --docs-dir corpus) has the same shape."""
    id: str | None
    version: str
    name: str
    instructions: str
    first_message: str | None
    voice: str
    llm: str
    keyterms: tuple[str, ...] | None  # None: the recognizer's default key terms
    index: Index


def default_agent(index: Index, name: str) -> Agent:
    return Agent(None, "default", name, "", None, deepgram_tts.MODEL, openai_compat_llm.MODEL, None, index)


@functools.lru_cache(maxsize=16)
def load(root: Path, agent: str, version: str) -> Agent:
    b = read(root, agent, version)
    c = b.config
    return Agent(agent, version, c["name"], c.get("instructions") or "", c.get("first_message") or None, c["voice"],
                 c["llm"], tuple(c.get("keyterms") or ()) or None, Index(b.passages, vectors=b.vectors))


def resolve(root: Path, agent: str) -> Agent | None:
    """The agent's live version, or None (unknown, disabled, or pruned between reading the pointer and loading)."""
    if not ID.fullmatch(agent or ""):
        return None
    version = current(root, agent)
    try:
        return load(Path(root), agent, version) if version else None
    except FileNotFoundError:
        return None


def version_of(config: dict, passages: list[Passage]) -> str:
    h = hashlib.sha256(json.dumps(config, sort_keys=True).encode())
    for p in passages:
        h.update(p.sha256.encode())
    return h.hexdigest()[:12]


def publish(root: Path, agent: str, config: dict, passages: list[Passage], vectors: np.ndarray) -> str:
    """Write the bundle (if new), point `current` at it, prune old versions. Returns the version."""
    config = {**validate(config), "format": FORMAT}
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
    activate(root, agent, version)
    prune(root, agent)
    return version


def activate(root: Path, agent: str, version: str) -> None:
    """Point `current` at an existing version (publishing, re-enabling, or rolling back)."""
    home = Path(root) / agent
    if not (home / version / "config.json").exists():
        raise FileNotFoundError(f"no version {version} of {agent}")
    pointer = home / f".{POINTER}.tmp"
    pointer.write_text(version + "\n")
    os.replace(pointer, home / POINTER)


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
