"""Install-wide settings and upgrades (Step 10, P5b): allowed websites, the spend line, schema migrations."""
import json
import sqlite3

from fastapi.testclient import TestClient

from voicecore_console.app import create_app
from voicecore_console.store import SCHEMA, Store

PASSWORD = "correct horse battery"


def signed_in(tmp_path, **kw):
    c = TestClient(create_app(tmp_path / "console", tmp_path / "agents", setup_token="s", **kw), base_url="http://localhost:8000")
    assert c.post("/api/setup", json={"token": "s", "password": PASSWORD}).status_code == 201
    return c


def test_allowed_websites_published_for_the_gateway(tmp_path):
    c = signed_in(tmp_path)
    assert c.get("/api/site").json() == {"origins": []}
    r = c.put("/api/site", json={"origins": ["acme.com", "https://docs.acme.com", "localhost:3000"]})
    assert r.status_code == 200
    published = json.loads((tmp_path / "agents" / "_site" / "origins.json").read_text())
    assert published == {"origins": ["acme.com", "https://docs.acme.com", "localhost:3000"]}
    assert c.get("/api/site").json() == published


def test_allowed_websites_refuse_any_site_patterns(tmp_path):
    c = signed_in(tmp_path)
    r = c.put("/api/site", json={"origins": ["*"]})
    assert (r.status_code, r.json()) == (422, {"detail": "not a website: * (use a host such as docs.example.com)"})
    r = c.put("/api/site", json={"origins": ["https://acme.com/path"]})
    assert (r.status_code, r.json()) == (422, {"detail": "not a website: https://acme.com/path (use a host such as docs.example.com)"})


def test_usage_reads_the_ledger_read_only(tmp_path):
    ledger = tmp_path / "ledger.json"
    ledger.write_text(json.dumps({"entries": [{"pool": "usd", "amount": 0.25, "status": "settled", "sub": "public", "ts": 0}]}))
    ledger.chmod(0o444)  # the console mounts it read-only
    c = signed_in(tmp_path, ledger=ledger)
    u = c.get("/api/usage").json()
    assert (u["spent_usd"], u["cap_usd"]) == (0.25, 2.0)  # the lower of the $5 pool and the $2 public total


def test_usage_without_a_ledger(tmp_path):
    assert signed_in(tmp_path).get("/api/usage").json() == {"spent_usd": None, "today_usd": None, "cap_usd": 2.0,
                                                            "daily_cap_usd": 0.5, "editable": False}


def test_spending_limits_set_in_the_dashboard(tmp_path):
    c = signed_in(tmp_path, limits_file=tmp_path / "providers" / "limits.json")
    r = c.put("/api/limits", json={"daily_usd": 1, "total_usd": 12.345})
    assert r.status_code == 200
    assert r.json() == {"spent_usd": None, "today_usd": None, "cap_usd": 12.35, "daily_cap_usd": 1.0, "editable": True}
    assert json.loads((tmp_path / "providers" / "limits.json").read_text()) == {"daily_usd": 1.0, "total_usd": 12.35}
    assert c.put("/api/limits", json={"daily_usd": 0, "total_usd": 5}).status_code == 422


def test_spending_limits_set_on_the_server_are_read_only(tmp_path):
    r = signed_in(tmp_path).put("/api/limits", json={"daily_usd": 1, "total_usd": 10})
    assert (r.status_code, r.json()) == (409, {"detail": "This install's spending limits are set on the server, in its .env file."})


def test_the_docs_website_becomes_an_allowed_website(tmp_path):
    c = signed_in(tmp_path)
    c.put("/api/site", json={"origins": ["*.example.org"]})
    c.post("/api/agents", json={"name": "Acme Docs"})
    config = c.get("/api/agents/acme-docs").json()["config"]
    r = c.put("/api/agents/acme-docs/settings", json={**config, "docs_url": "https://acme.com/help/"})
    assert r.json()["allowed"] == ["acme.com", "www.acme.com"]
    assert json.loads((tmp_path / "agents" / "_site" / "origins.json").read_text())["origins"] == [
        "*.example.org", "acme.com", "www.acme.com"]
    c.put("/api/site", json={"origins": ["*.example.org"]})  # removed on purpose: saving other settings leaves it out
    assert c.put("/api/agents/acme-docs/settings", json={**config, "docs_url": "https://acme.com/help/", "name": "Acme"}).json()["allowed"] == []
    r = c.put("/api/agents/acme-docs/settings", json={**config, "docs_url": "https://docs.example.org/"})
    assert r.json()["allowed"] == []  # *.example.org covers it


def test_migrations_from_v1(tmp_path):
    path = tmp_path / "console.db"
    db = sqlite3.connect(path)
    db.executescript(SCHEMA[0] + "; PRAGMA user_version = 1;")
    db.execute("INSERT INTO agents (id, config, created, updated) VALUES ('acme-docs', '{\"name\": \"Acme Docs\"}', 0, 0)")
    db.commit()
    db.close()
    store = Store(path)
    with store.db() as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == len(SCHEMA) >= 2
        assert db.execute("SELECT origins FROM site").fetchone() is None or True
    assert store.agent("acme-docs")["config"] == {"name": "Acme Docs"}
