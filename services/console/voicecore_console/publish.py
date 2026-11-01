"""Build and publish one agent: its sources become one docs tree, then sections, vectors and a bundle (ADR 0005).

Runs in the console's single build thread. A failure ends the build with a message for the console; the live
version (if any) keeps serving, because a bundle only goes live when it is complete.
"""
import dataclasses
import json
import logging
import shutil
import tempfile
from pathlib import Path

from voicecore import agents
from voicecore.answer.index import embed, embedder
from voicecore.answer.ingest import docusaurus, ingest

log = logging.getLogger("voicecore_console.publish")
MAX_PASSAGES = 5000  # about 100 s of embedding on one CPU
UNPUBLISHED = "https://unpublished.invalid/"  # a base for ingest when the docs have no public URL; the URLs are dropped


class Failed(Exception):
    pass


def sections(sources_dir: Path, source_ids: list[str], docs_url: str, web_hosts: tuple[str, ...] = ()):
    """All of an agent's sources merged into one tree (a later source wins a clash), split into sections.
    web_hosts: the websites pages were read from; those pages link to their own addresses."""
    site = docusaurus(docs_url or UNPUBLISHED)
    site = dataclasses.replace(site, allowed_hosts=site.allowed_hosts | set(web_hosts))
    with tempfile.TemporaryDirectory() as tmp:
        for sid in source_ids:
            if (sources_dir / sid).is_dir():
                shutil.copytree(sources_dir / sid, tmp, dirs_exist_ok=True)
        passages = ingest(Path(tmp), site=site)
    return [dataclasses.replace(p, url="") if p.url.startswith(UNPUBLISHED) else p for p in passages]


def build(store, data_dir: Path, agents_dir: Path, agent_id: str, build_id: int, now, max_passages: int = MAX_PASSAGES) -> None:
    try:
        agent = store.agent(agent_id)
        if agent is None:
            raise Failed("the agent was deleted")
        config, all_sources = agent["config"], store.sources(agent_id)
        if not all_sources:
            raise Failed("no docs yet: add a website, a file, a Git repository or some text first")
        web_hosts = tuple(json.loads(s["ref"])["host"] for s in all_sources if s["kind"] == "web")
        passages = sections(data_dir / "sources" / agent_id, [s["id"] for s in all_sources], config.get("docs_url") or "", web_hosts)
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
    finally:
        embedder.cache_clear()  # back to ~60 MB: the hosted console shares a 1 GB machine with the voice side
