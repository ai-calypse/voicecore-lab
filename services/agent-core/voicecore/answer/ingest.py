"""Docs ingestion (S04-T01): Markdown snapshot -> passages with canonical URLs, hashes and safety flags.

Two site styles: the pinned uv snapshot (MkDocs URLs and anchors, the eval corpus) and a Docusaurus docs
folder (apps/docs, the voice assistant's corpus). A passage URL must be the page route plus the anchor the
site really renders, because the widget opens it (harness/check_docs_anchors.py checks against a build).

Passages are untrusted text. Instruction-like text is kept (it is evidence) but flagged, and the answer
prompt tells the model that passages never carry instructions.
"""
import hashlib
import ipaddress
import re
import socket
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

BASE_URL = "https://docs.astral.sh/uv/"
ALLOWED_HOSTS = {"docs.astral.sh"}
SNAPSHOT_VERSION = "0.13.6"  # fixtures/docs/uv/SOURCE.md
# Instructions aimed at the assistant, not mentions: docs may say "API key" or "system prompt" (2026-10-30: the
# bare words hid the docs site's own setup pages from every answer).
SUSPICIOUS = re.compile(r"ignore (all |any )?(previous|prior|above) instructions|disregard (the |all )?(previous|above|system)|"
                        r"you are now|(reveal|repeat|print|show|output)\b.{0,30}\b(prompt|instructions|keys?)\b|"
                        r"(paste|send|share|give|tell)\b.{0,40}\b(api keys?|passwords?|secrets?|tokens?)\b", re.I)


class UnsafeURL(ValueError):
    pass


@dataclass(frozen=True)
class Site:
    base_url: str
    style: str = "mkdocs"  # mkdocs | docusaurus
    allowed_hosts: frozenset = field(default_factory=lambda: frozenset(ALLOWED_HOSTS))
    version: str | None = SNAPSHOT_VERSION  # pages declaring another version are stale


UV = Site(BASE_URL)


def docusaurus(base_url: str) -> Site:
    base = base_url.rstrip("/") + "/"
    return Site(base, "docusaurus", frozenset({urlsplit(base).hostname}), None)


@dataclass(frozen=True)
class Passage:
    id: str
    file: str
    heading: str
    title: str  # page title > heading, for citations
    url: str
    text: str
    sha256: str
    suspicious: bool
    official: bool = True  # from the pinned docs snapshot; extra (crawled) pages are not


def slugify(heading: str) -> str:
    """Python-Markdown toc slug, as MkDocs builds the uv docs anchors."""
    s = unicodedata.normalize("NFKD", heading).encode("ascii", "ignore").decode()
    s = re.sub(r"[^\w\s-]", "", s).strip().lower()
    return re.sub(r"[-\s]+", "-", s)


def github_slug(heading: str) -> str:
    """github-slugger, as Docusaurus makes heading ids: lowercase, drop punctuation and symbols, spaces -> '-'
    (no collapsing: "STT → LLM" becomes "stt--llm")."""
    keep = (c for c in heading.lower() if c in "-_ " or unicodedata.category(c)[0] in "LNM")
    return "".join(keep).replace(" ", "-")


def page_url(rel: str, site: Site = UV, slug: str | None = None) -> str:
    path = rel[: -len(".md")]
    if site.style == "docusaurus":
        if slug:  # front matter slug: absolute from the site root, or relative to the page's folder
            path = slug.strip("/") if slug.startswith("/") else (rel.rpartition("/")[0] + "/" + slug).strip("/")
        elif path == "index" or path.endswith("/index"):
            path = path[: -len("index")].rstrip("/")
        return site.base_url + path
    path = path[: -len("index")] if path == "index" or path.endswith("/index") else path + "/"
    return site.base_url + path


_HEADING = re.compile(r"^(#{1,4})\s+(.*?)\s*(?:\{#([\w-]+)\})?\s*$")


def _clean(heading: str) -> str:
    return re.sub(r"[`*]", "", re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", heading)).strip()


def front_matter(text: str) -> tuple[dict, str]:
    """`---` key: value block at the top of a page (crawled pages carry source_url and version)."""
    if not text.startswith("---\n"):
        return {}, text
    head, _, body = text[4:].partition("\n---\n")
    return {k.strip(): v.strip().strip("'\"") for k, _, v in (line.partition(":") for line in head.splitlines()) if k.strip()}, body


def allowed_source(url: str, site: Site = UV) -> bool:
    u = urlsplit(url)
    return u.scheme == "https" and u.hostname in site.allowed_hosts


def ingest(root: Path, extra: list[Path] = (), skipped: list | None = None, site: Site = UV) -> list[Passage]:
    """Split every Markdown file under root (the snapshot) and any extra pages at their headings.

    A page that declares a source_url outside the allowlist, or a version other than the snapshot's,
    is not indexed (reason appended to `skipped`).
    """
    out = []
    pages = [(f, f.relative_to(root).as_posix(), True) for f in sorted(root.rglob("*.md"))] + [(f, f.name, False) for f in extra]
    for f, rel, official in pages:
        if rel == "SOURCE.md" or rel.rpartition("/")[2].startswith("_"):  # snapshot notes; Docusaurus partials
            continue
        meta, text = front_matter(f.read_text())
        if "source_url" in meta and not allowed_source(meta["source_url"], site):
            skipped is not None and skipped.append((rel, "unauthorized source"))
            continue
        if site.version and meta.get("version", site.version) != site.version:
            skipped is not None and skipped.append((rel, f"stale version {meta['version']}"))
            continue
        base = meta.get("source_url") or page_url(rel, site, meta.get("slug"))
        doc = site.style == "docusaurus"
        page, sections, current, fence = meta.get("title") if doc else None, [], ("", None, []), False
        seen: dict[str, int] = {}  # Docusaurus suffixes a repeated slug on one page: x, x-1, x-2
        for line in text.splitlines():
            if line.lstrip().startswith(("```", "~~~")):
                fence = not fence
            m = None if fence else _HEADING.match(line)
            if m:
                sections.append(current)
                heading, anchor = _clean(m.group(2)), m.group(3)
                if doc and len(m.group(1)) == 1:  # an H1 is the page title, not a section
                    page, heading = page or heading, ""
                elif doc and not anchor:
                    anchor = base_slug = github_slug(heading)
                    while anchor in seen:
                        seen[base_slug] += 1
                        anchor = f"{base_slug}-{seen[base_slug]}"
                    seen[anchor] = 0
                current = (heading, anchor, [])
                page = page or current[0]
            else:
                current[2].append(line)
        sections.append(current)
        for heading, anchor, lines in sections:
            text = "\n".join(lines).strip()
            if not text:
                continue
            url = base + (f"#{anchor or slugify(heading)}" if heading and heading != page else "")
            body = f"{heading}\n\n{text}" if heading else text
            out.append(Passage(id=hashlib.sha256(url.encode()).hexdigest()[:12], file=rel, heading=heading,
                               title=f"{page} > {heading}" if heading and heading != page else (page or rel), url=url,
                               text=body, sha256=hashlib.sha256(body.encode()).hexdigest(), suspicious=bool(SUSPICIOUS.search(body)),
                               official=official))
    seen, unique = set(), []
    for p in out:  # two sections with the same slug on one page: keep the first, like the browser does
        if p.id not in seen:
            seen.add(p.id)
            unique.append(p)
    return unique


def check_url(url: str, allowed: set[str] | None = ALLOWED_HOSTS) -> str:
    """Refuse anything but https to an allowlisted host that resolves to public addresses (SSRF guard).
    allowed=None: any host name (never an address literal) that resolves only to public addresses."""
    if "\\" in url or any(ord(ch) < 33 for ch in url):  # parsers disagree on these (WHATWG reads \ as /)
        raise UnsafeURL(f"backslash or control character in URL: {url!r}")
    u = urlsplit(url)
    if u.scheme != "https" or not u.hostname:
        raise UnsafeURL(f"only https URLs: {url}")
    if u.username or u.password or u.port not in (None, 443):
        raise UnsafeURL(f"no userinfo and no port other than 443: {url}")
    host = u.hostname
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None or (allowed is not None and host not in allowed):
        raise UnsafeURL(f"host not allowed: {host}")
    for *_, addr in socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP):
        ip = ipaddress.ip_address(addr[0])
        if not ip.is_global:
            raise UnsafeURL(f"{host} resolves to a non-public address {ip}")
    return url
