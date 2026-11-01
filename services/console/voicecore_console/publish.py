"""Build and publish one agent: its sources become one docs tree, then sections, vectors and a bundle (ADR 0005).

Runs in the console's single build thread. A failure ends the build with a message for the console; the live
version (if any) keeps serving, because a bundle only goes live when it is complete.
"""
import dataclasses
import logging
import shutil
import tempfile
from pathlib import Path

from voicecore import agents
from voicecore.answer.index import embed
from voicecore.answer.ingest import docusaurus, ingest

log = logging.getLogger("voicecore_console.publish")
MAX_PASSAGES = 5000  # about 100 s of embedding on one CPU
UNPUBLISHED = "https://unpublished.invalid/"  # a base for ingest when the docs have no public URL; the URLs are dropped


class Failed(Exception):
    pass


def sections(sources_dir: Path, source_ids: list[str], docs_url: str):
    """All of an agent's sources merged into one tree (a later source wins a clash), split into sections."""
    with tempfile.TemporaryDirectory() as tmp:
        for sid in source_ids:
            if (sources_dir / sid).is_dir():
                shutil.copytree(sources_dir / sid, tmp, dirs_exist_ok=True)
        passages = ingest(Path(tmp), site=docusaurus(docs_url or UNPUBLISHED))
    return passages if docs_url else [dataclasses.replace(p, url="") for p in passages]


def build(store, data_dir: Path, agents_dir: Path, agent_id: str, build_id: int, now, max_passages: int = MAX_PASSAGES) -> None:
    try:
        agent = store.agent(agent_id)
        if agent is None:
            raise Failed("the agent was deleted")
        config, source_ids = agent["config"], [s["id"] for s in store.sources(agent_id)]
        if not source_ids:
            raise Failed("no docs yet: add a file, a Git repository or some text first")
        passages = sections(data_dir / "sources" / agent_id, source_ids, config.get("docs_url") or "")
        if not passages:
            raise Failed("no sections found: the pages have no text under their headings")
        if len(passages) > max_passages:
            raise Failed(f"too many sections: {len(passages):,} (the limit is {max_passages:,})")
        pages = len({p.file for p in passages})
        lines = [f"{len(passages)} section{'s' * (len(passages) != 1)} from {pages} page{'s' * (pages != 1)}"]
        if flagged := sum(p.suspicious for p in passages):
            lines.append(f"{flagged} section skipped: it reads like instructions to the assistant" if flagged == 1
                         else f"{flagged} sections skipped: they read like instructions to the assistant")
        store.build_progress(build_id, 0, len(passages))
        vectors = embed(passages, data_dir / "vectors", lambda done, total: store.build_progress(build_id, done, total))
        version = agents.publish(agents_dir, agent_id, config, passages, vectors)
        store.set_enabled(agent_id, True)
        lines.append(f"published version {version}")
        store.finish_build(build_id, "done", version, "\n".join(lines), now())
    except Failed as e:
        store.finish_build(build_id, "failed", None, str(e), now())
    except Exception:
        log.exception("build failed", extra={"agent": agent_id})
        store.finish_build(build_id, "failed", None, "build failed: see the console's log", now())
