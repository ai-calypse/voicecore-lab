"""Untrusted input: uploads and pasted text become Markdown pages under one folder per source, or are refused
with a reason the console can show. A new kind of source is one more function in FETCHERS."""
import io
import re
import shutil
import stat
import subprocess
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

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


FETCHERS = {"upload": save_upload, "text": save_text, "git": fetch_git}
