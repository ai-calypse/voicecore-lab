"""Untrusted input: uploads and pasted text become Markdown pages under one folder per source, or are refused
with a reason the console can show. A new kind of source is one more function in FETCHERS."""
import io
import ipaddress
import re
import shutil
import stat
import subprocess
import tempfile
import time
import zipfile
from collections import deque
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from urllib.parse import urljoin, urlsplit

import httpx

from voicecore.answer.ingest import UnsafeURL, check_url

MAX_BODY = 20 << 20  # one upload
MAX_EXPANDED = 50 << 20  # what an archive may unpack to
MAX_FILES = 2000
PAGES, TEXT = {".md", ".markdown"}, {".txt"}


class Rejected(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


def slug(text: str, limit: int = 40) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:limit].strip("-")


def _page(rel: PurePosixPath, data: bytes) -> tuple[PurePosixPath, str] | None:
    """A Markdown page from a file's bytes (a .txt file gets its name as the title); None if it is not UTF-8."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return None
    if rel.suffix.lower() in TEXT:
        return rel.with_suffix(".md"), f"# {rel.stem}\n\n{text.strip()}\n"
    return rel, text


def _write(dest: Path, rel: PurePosixPath, text: str) -> None:
    out = dest.joinpath(*rel.parts)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text)


def save_upload(body: bytes, name: str, dest: Path) -> dict:
    """A zip of docs, or one .md, .markdown or .txt file."""
    if body[:4] == b"PK\x03\x04":
        return _save_zip(body, dest)
    rel = PurePosixPath(slug(PurePosixPath(name).stem) or "page").with_suffix(PurePosixPath(name).suffix.lower())
    if rel.suffix not in PAGES | TEXT:
        raise Rejected(415, f"not a Markdown, text or zip file: {name}")
    page = _page(rel, body)
    if page is None:
        raise Rejected(400, f"not UTF-8 text: {name}")
    _write(dest, *page)
    return {"files": 1, "skipped": []}


def _save_zip(body: bytes, dest: Path) -> dict:
    try:
        z = zipfile.ZipFile(io.BytesIO(body))
    except zipfile.BadZipFile:
        raise Rejected(400, "not a valid zip file") from None
    for info in z.infolist():
        p = PurePosixPath(info.filename)
        if p.is_absolute() or ".." in p.parts or "\\" in info.filename:
            raise Rejected(400, f"unsafe path in archive: {info.filename}")
    files = [i for i in z.infolist() if not i.is_dir()]
    if len(files) > MAX_FILES:
        raise Rejected(413, f"archive has more than {MAX_FILES:,} files")
    if sum(i.file_size for i in files) > MAX_EXPANDED:  # the declared sizes; the reads below are capped as well
        raise Rejected(413, "archive expands past 50 MB")
    tops = {PurePosixPath(i.filename).parts[0] for i in files}
    strip = 1 if len(tops) == 1 and all(len(PurePosixPath(i.filename).parts) > 1 for i in files) else 0  # repo-main/
    saved, skipped, total = 0, [], 0
    for info in files:
        rel = PurePosixPath(*PurePosixPath(info.filename).parts[strip:])
        if stat.S_ISLNK(info.external_attr >> 16):
            skipped.append(f"{rel} (a link)")
            continue
        if rel.suffix.lower() not in PAGES | TEXT or rel.name.startswith("."):
            skipped.append(str(rel))
            continue
        with z.open(info) as f:
            data = f.read(MAX_EXPANDED - total + 1)
        total += len(data)
        if total > MAX_EXPANDED:
            raise Rejected(413, "archive expands past 50 MB")
        page = _page(rel, data)
        if page is None:
            skipped.append(f"{rel} (not UTF-8)")
            continue
        _write(dest, *page)
        saved += 1
    if not saved:
        raise Rejected(400, "no Markdown or text files in the archive")
    return {"files": saved, "skipped": skipped}


def save_text(title: str, text: str, dest: Path) -> dict:
    _write(dest, PurePosixPath(f"{slug(title) or 'note'}.md"), f"# {title.strip()}\n\n{text.strip()}\n")
    return {"files": 1, "skipped": []}


GIT_TIMEOUT_S = 60


def git_command(url: str, ref: str, workdir, protocols=("https",)) -> list[str]:
    """A shallow, sparse, single-branch clone that refuses every other protocol, redirects and symlinks."""
    allow = [arg for p in protocols for arg in ("-c", f"protocol.{p}.allow=always")]
    return ["git", "-c", "protocol.allow=never", *allow, "-c", "http.followRedirects=false", "-c", "core.symlinks=false",
            "clone", "--depth", "1", "--filter=blob:none", "--sparse", "--single-branch", "--no-tags",
            *(["--branch", ref] if ref else []), url, str(workdir)]


def git_env(home) -> dict:
    """No prompts, no LFS downloads, no system or user git config (a hook or credential helper there must not run)."""
    return {"PATH": "/usr/local/bin:/usr/bin:/bin:/opt/homebrew/bin", "HOME": str(home), "GIT_TERMINAL_PROMPT": "0",
            "GIT_LFS_SKIP_SMUDGE": "1", "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null"}


def public_url(url: str) -> str:
    return check_url(url, allowed=None)


def fetch_git(url: str, folder: str, dest: Path, ref: str = "", run_git=subprocess.run, check=public_url,
              protocols=("https",), max_bytes: int = MAX_BODY) -> dict:
    """Clone one folder of a public repository and keep its Markdown and text files. A re-sync replaces dest."""
    try:
        check(url)
    except UnsafeURL as e:
        raise Rejected(400, str(e)) from None
    sub = PurePosixPath(folder.strip().strip("/"))
    if sub.is_absolute() or ".." in sub.parts:
        raise Rejected(400, "the folder must be a path inside the repository")
    if ref and not re.fullmatch(r"[\w./-]{1,100}", ref) or ref.startswith("-"):
        raise Rejected(400, f"not a branch or tag name: {ref}")
    with tempfile.TemporaryDirectory() as tmp:
        home, wd = Path(tmp) / "home", Path(tmp) / "repo"
        home.mkdir()
        env = git_env(home)

        def git(cmd):
            try:
                return run_git(cmd, env=env, capture_output=True, text=True, check=True, timeout=GIT_TIMEOUT_S)
            except subprocess.TimeoutExpired:
                raise Rejected(504, f"the clone took longer than {GIT_TIMEOUT_S} s") from None
            except subprocess.CalledProcessError as e:
                reason = (e.stderr or "").strip().splitlines()[-1:] or ["git failed"]
                raise Rejected(400, f"could not clone {url}: {reason[0]}") from None

        git(git_command(url, ref, wd, protocols))
        git(["git", "-C", str(wd), "sparse-checkout", "set", "--no-cone", f"/{sub}/" if str(sub) != "." else "/*"])
        listing = git(["git", "-C", str(wd), "ls-files", "-s", "--", str(sub)]).stdout
        new = dest.with_name(dest.name + ".new")
        shutil.rmtree(new, ignore_errors=True)
        paths, skipped, total = [], [], 0
        for line in listing.splitlines():
            meta, _, path = line.partition("\t")
            rel = PurePosixPath(path).relative_to(sub) if str(sub) != "." else PurePosixPath(path)
            if meta.startswith("120000"):
                skipped.append(f"{rel} (a link)")
                continue
            if rel.suffix.lower() not in PAGES | TEXT:
                skipped.append(str(rel))
                continue
            data = (wd / path).read_bytes()
            total += len(data)
            if total > max_bytes:
                shutil.rmtree(new, ignore_errors=True)
                raise Rejected(413, "folder larger than 20 MB")
            page = _page(rel, data)
            if page is None:
                skipped.append(f"{rel} (not UTF-8)")
                continue
            _write(new, *page)
            paths.append(path)
        if not paths:
            shutil.rmtree(new, ignore_errors=True)
            raise Rejected(400, "no Markdown or text files in that folder")
        shutil.rmtree(dest, ignore_errors=True)
        new.rename(dest)
    return {"files": len(paths), "skipped": skipped, "paths": paths}


# --- a website: its pages under the address given, read like a visitor's browser would, without running scripts ---

MAX_PAGES, MAX_PAGE, WEB_DEADLINE_S = 200, 2 << 20, 60
NOT_PAGES = re.compile(r"\.(pdf|png|jpe?g|gif|svg|webp|ico|zip|gz|tgz|mp[34]|mov|webm|css|js|json|xml|rss|txt|woff2?|ttf|exe|dmg)$", re.I)
SKIP_TAGS = {"title", "script", "style", "noscript", "svg", "template", "nav", "footer", "aside", "form", "button", "iframe",
             "select", "dialog"}
BLOCKS = {"p", "div", "section", "article", "main", "ul", "ol", "table", "tr", "blockquote", "dl", "dt", "dd",
          "figure", "figcaption", "br", "hr", "details", "summary"}
AGENT = "VoiceCore docs reader (+https://github.com/ai-calypse/voicecore-lab)"


class _Html(HTMLParser):
    """One page as Markdown: headings (with the page's own anchor ids), paragraphs, lists, code. When the page marks
    its content (<article>, else <main>), only that is kept; menus, footers and scripts never are. Links are collected
    from the whole page, menus included: they lead to the other pages."""

    def __init__(self, url: str):
        super().__init__(convert_charrefs=True)
        self.url, self.links, self.out, self.title = url, [], [], ""
        self.skip, self.skipping, self.depth, self.pre, self.in_title = 0, "", {"article": 0, "main": 0}, 0, False
        self.heading: tuple[int, str, list[str]] | None = None

    def emit(self, text: str) -> None:
        self.out.append((2 if self.depth["article"] else 1 if self.depth["main"] else 0, text))

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "a" and a.get("href"):
            self.links.append(urljoin(self.url, a["href"]))
        if self.skip:  # inside a left-out part: count only its own tag, whose end tag is never optional
            self.skip += tag == self.skipping
            return
        if tag in SKIP_TAGS or (tag == "header" and not any(self.depth.values())):
            self.skip, self.skipping, self.in_title = 1, tag, tag == "title" and not self.title
            return
        if tag in self.depth:
            self.depth[tag] += 1
        if re.fullmatch(r"h[1-6]", tag):
            self.heading = (min(int(tag[1]), 4), a.get("id") or "", [])
        elif tag == "pre":
            self.pre += 1
            self.emit("\n```\n")
        elif tag == "li":
            self.emit("\n- ")
        elif tag in ("td", "th"):
            self.emit(" | ")
        elif tag in BLOCKS:
            self.emit("\n\n")

    def handle_endtag(self, tag):
        if self.skip:
            self.skip -= tag == self.skipping
            self.in_title = self.in_title and self.skip > 0
            return
        if tag in self.depth and self.depth[tag]:
            self.depth[tag] -= 1
        if self.heading and re.fullmatch(r"h[1-6]", tag):
            level, anchor, text = self.heading
            self.heading = None
            if title := re.sub(r"\s+", " ", "".join(text)).replace("\u200b", "").strip(" #"):
                tag_id = f" {{#{anchor}}}" if re.fullmatch(r"[\w-]+", anchor) else ""
                self.emit(f"\n\n{'#' * level} {title}{tag_id}\n\n")
        elif tag == "pre" and self.pre:
            self.pre -= 1
            self.emit("\n```\n")
        elif tag in BLOCKS:
            self.emit("\n\n")

    def handle_data(self, data):
        if self.in_title:
            self.title += data
        if self.skip:
            return
        if self.heading:
            self.heading[2].append(data)
        else:
            self.emit(data if self.pre else re.sub(r"\s+", " ", data))

    def markdown(self) -> str:
        best = max((level for level, _ in self.out), default=0)
        text = re.sub(r"[ \t]+\n", "\n", "".join(t for level, t in self.out if level == best))
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        if text and not re.search(r"^# ", text, re.M) and self.title.strip():
            text = f"# {self.title.strip()}\n\n{text}"
        return text


def _clean(url: str) -> str:
    u = urlsplit(url)
    return f"{u.scheme.lower()}://{(u.netloc or '').lower()}{u.path or '/'}"


def _rel(path: str) -> PurePosixPath:
    """A file for a page: /help/billing -> help/billing.md, /help/ -> help/index.md."""
    parts = [re.sub(r"[^\w.-]+", "-", seg).strip(".-_")[:80] or "page" for seg in path.split("/") if seg]
    if path.endswith("/") or not parts:
        parts.append("index")
    parts[-1] = re.sub(r"\.html?$", "", parts[-1])
    return PurePosixPath(*parts[:-1], parts[-1] + ".md")


def _http_get(client: httpx.Client, url: str) -> tuple[int, str, str]:
    """One request, no redirects followed: (status, the redirect's target, the page's HTML or ""). The address
    actually connected to must be public too: DNS may answer differently than it did for check_url."""
    with client.stream("GET", url) as r:
        peer = (stream := r.extensions.get("network_stream")) and stream.get_extra_info("server_addr")
        if not peer or not ipaddress.ip_address(peer[0]).is_global:
            raise Rejected(400, f"{urlsplit(url).hostname} connected to a non-public address")
        if r.is_redirect:
            return r.status_code, urljoin(url, r.headers.get("location", "")), ""
        if r.status_code != 200 or "html" not in r.headers.get("content-type", ""):
            return r.status_code, "", ""
        body, start = b"", time.monotonic()
        for chunk in r.iter_bytes():
            body += chunk
            if len(body) > MAX_PAGE:
                return 413, "", ""
            if time.monotonic() - start > 15:  # a page sent a trickle at a time must not outlast the reading's deadline
                return 504, "", ""
        charset = re.search(r"charset=([\w-]+)", r.headers.get("content-type", ""))
        try:
            return 200, "", body.decode(charset.group(1) if charset else "utf-8", errors="replace")
        except LookupError:  # a charset Python doesn't know
            return 200, "", body.decode("utf-8", errors="replace")


def fetch_web(url: str, dest: Path, get=None, check=public_url, max_pages: int = MAX_PAGES,
              deadline_s: float = WEB_DEADLINE_S, clock=time.monotonic) -> dict:
    """Read the pages at a public https address and every page linked below it (same host, same folder or deeper),
    up to max_pages and deadline_s. Each page keeps its real address (source_url) for the answers' links.
    get(url) -> (status, redirect target, html): one request; injected by tests. A re-sync replaces dest."""

    def safe(u: str) -> str:
        try:
            return check(u)
        except UnsafeURL as e:
            raise Rejected(400, str(e)) from None
        except OSError:
            raise Rejected(400, f"couldn't find {urlsplit(u).hostname}: check the address") from None

    def follow(u: str, in_scope=lambda u: True) -> tuple[str, str] | None:
        """The page's final address and HTML, after at most 5 redirects, each one checked; None: not a page."""
        for _ in range(6):
            status, target, html = get(safe(u))
            if not target:
                return (u, html) if status == 200 and html else None
            u = _clean(target)
            if not in_scope(u):
                return None
        return None

    url = url.strip()
    if not url.lower().startswith("https://"):  # "acme.com/help" or "http://…": the site's https address
        url = "https://" + re.sub(r"^https?://", "", url, flags=re.I)
    client = None
    if get is None:
        client = httpx.Client(timeout=10, headers={"user-agent": AGENT})
        get = lambda u: _http_get(client, u)  # noqa: E731
    try:
        try:
            first = follow(_clean(url))
        except httpx.TimeoutException:
            raise Rejected(504, f"{url} took too long to answer") from None
        except httpx.HTTPError:
            raise Rejected(400, f"couldn't reach {url}") from None
        if first is None:
            raise Rejected(400, f"no web page at {url}")
        start = urlsplit(first[0])
        host, folder = start.netloc, start.path.rpartition("/")[0] + "/"

        def in_scope(u: str) -> bool:
            p = urlsplit(u)
            return p.scheme == "https" and p.netloc == host and p.path.startswith(folder) and not NOT_PAGES.search(p.path)

        new = dest.with_name(dest.name + ".new")
        shutil.rmtree(new, ignore_errors=True)
        queue, seen, written, total, stopped = deque([first]), {first[0]}, set(), 0, []
        end = clock() + deadline_s
        while queue:
            if len(written) >= max_pages or clock() > end or total > MAX_BODY:
                why = ("the limit" if len(written) >= max_pages else "20 MB of pages" if total > MAX_BODY
                       else f"reading stops after {deadline_s:.0f} s")
                stopped = [f"the pages after the first {len(written)} ({why})"]
                break
            page_url, html = queue.popleft()
            if html is None:  # a link: fetched now, and skipped if it isn't a page in scope
                try:
                    page = follow(page_url, in_scope)
                except (Rejected, httpx.HTTPError):
                    continue
                if page is None or (page[0] != page_url and page[0] in seen):
                    continue
                page_url, html = page
                seen.add(page_url)
            total += len(html)
            parsed = _Html(page_url)
            parsed.feed(html)
            rel = _rel(urlsplit(page_url).path)
            if (text := parsed.markdown()) and rel not in written:
                _write(new, rel, f"---\nsource_url: {page_url}\n---\n\n{text}\n")
                written.add(rel)
            for link in map(_clean, parsed.links):
                if link not in seen and in_scope(link):
                    seen.add(link)
                    queue.append((link, None))
        if not written:
            shutil.rmtree(new, ignore_errors=True)
            raise Rejected(400, f"no readable text at {url}. If the site needs JavaScript to show its pages, "
                                "upload the docs as files instead.")
        shutil.rmtree(dest, ignore_errors=True)
        new.rename(dest)
        return {"files": len(written), "skipped": stopped, "host": host}
    finally:
        if client:
            client.close()


FETCHERS = {"upload": save_upload, "text": save_text, "git": fetch_git, "web": fetch_web}
