"""Every passage URL the assistant can cite must exist on the built docs site: uv run python harness/check_docs_anchors.py

Run after `pnpm --filter @voicecore/docs build`. Ingests apps/docs/docs exactly as the orchestrator does, then
checks each URL's page (build/<route>/index.html) and anchor (an element with that id). A heading whose anchor
Docusaurus renders differently from voicecore.answer.ingest.github_slug fails here, not in front of a user.
"""
import re
import sys
from urllib.parse import unquote, urlsplit

from fixtures import ROOT

from voicecore.answer.ingest import docusaurus, ingest

BASE = "http://localhost:3000/"


def main() -> int:
    build = ROOT / "apps/docs/build"
    if not build.exists():
        sys.exit("no apps/docs/build: run `pnpm --filter @voicecore/docs build` first")
    passages = ingest(ROOT / "apps/docs/docs", site=docusaurus(BASE))
    bad, ids = [], {}
    for p in passages:
        u = urlsplit(p.url)
        page = build / u.path.strip("/") / "index.html"
        if page not in ids:
            ids[page] = set(re.findall(r'\bid="([^"]+)"', page.read_text())) if page.exists() else None
        if ids[page] is None:
            bad.append(f"{p.url}: no page {page.relative_to(ROOT)}")
        elif u.fragment and unquote(u.fragment) not in ids[page]:
            bad.append(f"{p.url}: no element with id {u.fragment!r} ({p.file} > {p.heading})")
    print(f"{len(passages)} passages on {len(ids)} pages, {len(bad)} broken")
    print("\n".join(bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
