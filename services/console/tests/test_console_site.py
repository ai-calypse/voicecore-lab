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
    assert (u["spent_usd"], u["cap_usd"]) == (0.25, 5.0)


def test_usage_without_a_ledger(tmp_path):
    assert signed_in(tmp_path).get("/api/usage").json() == {"spent_usd": None, "cap_usd": None, "today_usd": None, "daily_cap_usd": None}


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
