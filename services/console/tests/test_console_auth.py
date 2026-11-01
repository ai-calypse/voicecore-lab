"""Console auth (Step 10, P4, seam 22): one admin made on first run with a setup token, sessions, API keys."""
import hashlib
import sqlite3
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

from voicecore_console.app import create_app

PASSWORD = "correct horse battery"


def client(tmp_path, token="setup-123", now=None, **kw):
    app = create_app(tmp_path / "console", tmp_path / "agents", setup_token=token, **({"now": now} if now else {}), **kw)
    return TestClient(app, base_url="http://localhost:8000")


def setup(c, password=PASSWORD, token="setup-123"):
    return c.post("/api/setup", json={"token": token, "password": password})


def test_setup_needs_token(tmp_path):
    c = client(tmp_path)
    assert c.post("/api/setup", json={"password": PASSWORD}).status_code == 403
    assert setup(c, token="wrong").status_code == 403
    r = setup(c)
    assert r.status_code == 201
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie
    assert c.get("/api/me").json() == {"admin": True}


def test_setup_once(tmp_path):
    c = client(tmp_path)
    setup(c)
    r = setup(c)
    assert (r.status_code, r.json()) == (409, {"detail": "already set up"})


def test_password_min_12(tmp_path):
    assert setup(client(tmp_path), password="short").status_code == 422


def test_unauthenticated_is_401(tmp_path):
    c = client(tmp_path)
    setup(c)
    assert TestClient(c.app, base_url="http://localhost:8000").get("/api/keys").status_code == 401


def test_login_and_logout(tmp_path):
    c = client(tmp_path)
    setup(c)
    fresh = TestClient(c.app, base_url="http://localhost:8000")
    assert fresh.post("/api/login", json={"password": "wrong password!"}).status_code == 401
    assert fresh.post("/api/login", json={"password": PASSWORD}).status_code == 200
    assert fresh.get("/api/me").json() == {"admin": True}
    assert fresh.post("/api/logout").status_code == 204
    assert fresh.get("/api/me").status_code == 401


def test_login_rate_limit(tmp_path):
    c = client(tmp_path)
    setup(c)
    fresh = TestClient(c.app, base_url="http://localhost:8000")
    codes = [fresh.post("/api/login", json={"password": "wrong password!"}).status_code for _ in range(5)]
    assert codes == [401] * 5
    assert fresh.post("/api/login", json={"password": PASSWORD}).status_code == 429  # even the right one, this minute


def test_cross_origin_post_403(tmp_path):
    c = client(tmp_path)
    setup(c)
    r = c.post("/api/keys", json={"label": "ci"}, headers={"Origin": "https://evil.example"})
    assert (r.status_code, r.json()) == (403, {"detail": "cross-origin request"})
    assert c.post("/api/keys", json={"label": "ci"}, headers={"Origin": "http://localhost:8000"}).status_code == 201


def test_api_key_once_hashed(tmp_path):
    c = client(tmp_path)
    setup(c)
    r = c.post("/api/keys", json={"label": "ci"})
    assert r.status_code == 201
    key = r.json()["key"]
    assert key.startswith("vck_") and len(key) == 4 + 64
    listed = c.get("/api/keys").json()
    assert [k["label"] for k in listed] == ["ci"] and all("key" not in k for k in listed)
    db = sqlite3.connect(tmp_path / "console" / "console.db")
    assert db.execute("SELECT key_hash FROM api_keys").fetchone()[0] == hashlib.sha256(key.encode()).hexdigest()
    bearer = TestClient(c.app, base_url="http://localhost:8000", headers={"Authorization": f"Bearer {key}"})
    assert bearer.get("/api/keys").status_code == 200


def test_revoked_key_401(tmp_path):
    c = client(tmp_path)
    setup(c)
    r = c.post("/api/keys", json={"label": "ci"}).json()
    assert c.delete(f"/api/keys/{r['id']}").status_code == 204
    bearer = TestClient(c.app, base_url="http://localhost:8000", headers={"Authorization": f"Bearer {r['key']}"})
    assert bearer.get("/api/keys").status_code == 401


def test_reset_admin_prints_fragment_url(tmp_path):
    c = client(tmp_path)
    setup(c)
    out = subprocess.run([sys.executable, "-m", "voicecore_console", "reset-admin", "--data-dir", str(tmp_path / "console"),
                          "--url", "http://localhost:8000"], capture_output=True, text=True, check=True).stdout
    assert "http://localhost:8000/#/setup?token=" in out
    token = out.split("token=")[1].split()[0]
    assert c.get("/api/me").status_code == 401  # the old session is gone
    assert setup(c, token=token).status_code == 201


def test_admin_password_from_env(tmp_path):
    """CONSOLE_ADMIN_PASSWORD: no setup link; the installer prints the password and keeps it in .env."""
    c = client(tmp_path, token=None, admin_password=PASSWORD)
    assert c.get("/api/status").json()["setup_needed"] is False
    assert c.post("/api/login", json={"password": PASSWORD}).status_code == 200


def test_changed_env_password_replaces_admin_and_signs_out(tmp_path):
    c = client(tmp_path, token=None, admin_password=PASSWORD)
    c.post("/api/login", json={"password": PASSWORD})
    again = client(tmp_path, token=None, admin_password="a brand new passphrase")
    assert again.get("/api/me", cookies=c.cookies).status_code == 401
    assert again.post("/api/login", json={"password": PASSWORD}).status_code == 401
    assert again.post("/api/login", json={"password": "a brand new passphrase"}).status_code == 200


def test_same_env_password_keeps_sessions(tmp_path):
    c = client(tmp_path, token=None, admin_password=PASSWORD)
    c.post("/api/login", json={"password": PASSWORD})
    assert client(tmp_path, token=None, admin_password=PASSWORD).get("/api/me", cookies=c.cookies).status_code == 200


def test_short_env_password_refused(tmp_path):
    with pytest.raises(ValueError, match="CONSOLE_ADMIN_PASSWORD must be at least 12 characters"):
        client(tmp_path, token=None, admin_password="short")
