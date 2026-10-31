"""What the console UI needs from the server (Step 10, P6): its status, the built pages, and the Test preview."""
from fastapi.testclient import TestClient

from voicecore_console.app import create_app

PASSWORD = "correct horse battery"
SNIPPET = '<script src="http://127.0.0.1:18082/widget.js" data-agent="acme-docs" async></script>'


def app(tmp_path, **kw):
    return create_app(tmp_path / "console", tmp_path / "agents", setup_token="s", providers="free",
                      voice_url="http://127.0.0.1:18082", **kw)


def test_status_before_and_after_setup(tmp_path):
    c = TestClient(app(tmp_path), base_url="http://localhost:8000")
    assert c.get("/api/status").json() == {"setup_needed": True, "providers": "free", "voice_url": "http://127.0.0.1:18082"}
    c.post("/api/setup", json={"token": "s", "password": PASSWORD})
    assert c.get("/api/status").json()["setup_needed"] is False


def test_preview_page_holds_the_real_snippet(tmp_path):
    c = TestClient(app(tmp_path), base_url="http://localhost:8000")
    assert c.get("/preview/acme-docs").status_code == 401  # signed-in admins only
    c.post("/api/setup", json={"token": "s", "password": PASSWORD})
    c.post("/api/agents", json={"name": "Acme Docs"})
    r = c.get("/preview/acme-docs")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    assert SNIPPET in r.text
    assert "frame-ancestors 'self'" in r.headers["content-security-policy"]
    assert c.get("/preview/nope").status_code == 404


def test_snippet_in_agent_details(tmp_path):
    c = TestClient(app(tmp_path), base_url="http://localhost:8000")
    c.post("/api/setup", json={"token": "s", "password": PASSWORD})
    c.post("/api/agents", json={"name": "Acme Docs"})
    assert c.get("/api/agents/acme-docs").json()["snippet"] == SNIPPET


def test_built_ui_is_served(tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>VoiceCore console</title>")
    (dist / "assets" / "app.js").write_text("console.log(1)")
    c = TestClient(app(tmp_path, static_dir=dist), base_url="http://localhost:8000")
    r = c.get("/")
    assert r.status_code == 200 and "VoiceCore console" in r.text
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
    assert c.get("/assets/app.js").text == "console.log(1)"


def test_snippet_carries_the_turnstile_sitekey(tmp_path):
    c = TestClient(app(tmp_path, turnstile_sitekey="0x4AAAAAAAtest"), base_url="http://localhost:8000")
    c.post("/api/setup", json={"token": "s", "password": PASSWORD})
    c.post("/api/agents", json={"name": "Acme Docs"})
    assert c.get("/api/agents/acme-docs").json()["snippet"] == (
        '<script src="http://127.0.0.1:18082/widget.js" data-agent="acme-docs" data-turnstile-sitekey="0x4AAAAAAAtest" async></script>')
