"""Git sources (Step 10, P7, seam 22): a hardened shallow clone of one folder, against local repositories only."""
import subprocess

import pytest

from voicecore.answer.ingest import UnsafeURL, check_url
from voicecore_console import sources


def git(cwd, *args):
    subprocess.run(["git", "-c", "user.email=t@example.test", "-c", "user.name=t", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "repo"
    (r / "docs").mkdir(parents=True)
    (r / "docs" / "a.md").write_text("# A\n\nAlpha.\n")
    (r / "docs" / "logo.png").write_bytes(b"\x89PNG")
    (r / "README.md").write_text("# Readme\n\nNot the docs.\n")
    (r / "docs" / "link.md").symlink_to("/etc/passwd")
    git(r, "init", "-q", "-b", "main")
    git(r, "add", "-A")
    git(r, "commit", "-qm", "docs")
    return r


def fetch(repo, dest, **kw):
    # file:// only in tests: the console itself allows https alone (sources.git_command)
    return sources.fetch_git(f"file://{repo}", "docs", dest, check=lambda u: u, protocols=("file",), **kw)


def test_git_url_rules():
    with pytest.raises(UnsafeURL, match="^only https URLs: http://github.com/a/b$"):
        check_url("http://github.com/a/b", allowed=None)
    with pytest.raises(UnsafeURL, match="^host not allowed: 10.0.0.1$"):
        check_url("https://10.0.0.1/a/b", allowed=None)
    with pytest.raises(UnsafeURL, match="non-public address"):
        check_url("https://localhost/a/b", allowed=None)


def test_git_command_is_hardened():
    cmd = sources.git_command("https://github.com/acme/docs", "", "/tmp/x")
    joined = " ".join(cmd)
    for flag in ("protocol.allow=never", "protocol.https.allow=always", "http.followRedirects=false", "core.symlinks=false",
                 "--depth 1", "--filter=blob:none", "--sparse", "--single-branch", "--no-tags"):
        assert flag in joined, flag
    assert sources.git_env("/tmp/h")["GIT_TERMINAL_PROMPT"] == "0"


def test_sparse_clone_only_folder(repo, tmp_path):
    r = fetch(repo, tmp_path / "out")
    assert r["paths"] == ["docs/a.md"]
    assert sorted(p.name for p in (tmp_path / "out").rglob("*") if p.is_file()) == ["a.md"]


def test_symlink_skipped(repo, tmp_path):
    r = fetch(repo, tmp_path / "out")
    assert "link.md (a link)" in r["skipped"]
    assert not (tmp_path / "out" / "link.md").exists()


def test_size_cap(repo, tmp_path):
    with pytest.raises(sources.Rejected, match="^folder larger than 20 MB$"):
        fetch(repo, tmp_path / "out", max_bytes=5)


def test_resync_replaces_files(repo, tmp_path):
    fetch(repo, tmp_path / "out")
    (repo / "docs" / "a.md").unlink()
    (repo / "docs" / "b.md").write_text("# B\n\nBeta.\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "rename")
    r = fetch(repo, tmp_path / "out")
    assert r["paths"] == ["docs/b.md"]
    assert sorted(p.name for p in (tmp_path / "out").rglob("*.md")) == ["b.md"]


def test_api_refuses_a_private_address(tmp_path):
    from fastapi.testclient import TestClient

    from voicecore_console.app import create_app

    c = TestClient(create_app(tmp_path / "console", tmp_path / "agents", setup_token="s"), base_url="http://localhost:8000")
    c.post("/api/setup", json={"token": "s", "password": "correct horse battery"})
    c.post("/api/agents", json={"name": "Acme Docs"})
    r = c.post("/api/agents/acme-docs/sources/git", json={"url": "https://10.0.0.1/acme/docs", "folder": "docs"})
    assert (r.status_code, r.json()) == (400, {"detail": "host not allowed: 10.0.0.1"})
