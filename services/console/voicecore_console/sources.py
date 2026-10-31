"""Untrusted input: uploads and pasted text become Markdown pages under one folder per source, or are refused
with a reason the console can show. A new kind of source is one more function in FETCHERS."""
import io
import re
import stat
import zipfile
from pathlib import Path, PurePosixPath

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


FETCHERS = {"upload": save_upload, "text": save_text}  # "git" joins in P7
