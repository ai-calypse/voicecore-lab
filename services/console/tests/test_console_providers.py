"""Provider keys from the dashboard (Step 10 follow-up): checked with the provider before they are saved, never shown
again, and live at the next session through the shared key file (voicecore.keys)."""
import pytest
from fastapi.testclient import TestClient

from voicecore import keys
from voicecore_console import provider_keys
from voicecore_console.app import create_app

PASSWORD = "correct horse battery"


def client(tmp_path, check=lambda provider, key: key != "bad-key-0000", **kw):
    kw = {"providers": "auto", "keys_file": tmp_path / "providers" / "keys.json", **kw}
    app = create_app(tmp_path / "console", tmp_path / "agents", admin_password=PASSWORD, check_key=check, **kw)
    c = TestClient(app, base_url="http://localhost:8000")
    c.post("/api/login", json={"password": PASSWORD})
    return c


@pytest.fixture(autouse=True)
def no_env_keys(monkeypatch):
    for name in keys.VOICE:
        monkeypatch.delenv(name, raising=False)


def test_both_keys_turn_voice_on(tmp_path):
    c = client(tmp_path)
    assert c.get("/api/status").json()["providers"] == "free"
    assert c.put("/api/providers/deepgram", json={"key": "dg-good-key-1234"}).status_code == 200
    r = c.put("/api/providers/openrouter", json={"key": " sk-or-v1-good-5678 \n"})
    assert r.json() == {"deepgram": {"source": "dashboard", "last4": "1234"}, "openrouter": {"source": "dashboard", "last4": "5678"},
                        "voice": True, "editable": True}
    assert c.get("/api/status").json()["providers"] == "live"
    assert keys.saved(tmp_path / "providers" / "keys.json") == {"DEEPGRAM_API_KEY": "dg-good-key-1234",
                                                                "OPENROUTER_API_KEY": "sk-or-v1-good-5678"}
    assert "good-key" not in c.get("/api/providers").text  # write-only: only the last four characters come back


def test_a_key_the_provider_refuses_is_not_saved(tmp_path):
    r = client(tmp_path).put("/api/providers/deepgram", json={"key": "bad-key-0000"})
    assert (r.status_code, r.json()) == (422, {"detail": "Deepgram did not accept this key"})
    assert not (tmp_path / "providers" / "keys.json").exists()


def test_provider_unreachable(tmp_path):
    def down(provider, key):
        raise provider_keys.Unreachable(provider)

    r = client(tmp_path, check=down).put("/api/providers/openrouter", json={"key": "sk-or-v1-good-5678"})
    assert (r.status_code, r.json()) == (502, {"detail": "Couldn't reach OpenRouter to check the key. Try again."})


def test_not_a_key(tmp_path):
    c = client(tmp_path)
    r = c.put("/api/providers/deepgram", json={"key": "two words here"})
    assert (r.status_code, r.json()) == (422, {"detail": "That doesn't look like an API key."})
    assert c.put("/api/providers/elevenlabs", json={"key": "xi-good-key-1234"}).status_code == 404


def test_removing_a_key_falls_back_to_the_server(tmp_path, monkeypatch):
    c = client(tmp_path)
    c.put("/api/providers/deepgram", json={"key": "dg-good-key-1234"})
    assert c.delete("/api/providers/deepgram").status_code == 204
    assert c.get("/api/providers").json()["deepgram"] == {"source": None, "last4": None}
    monkeypatch.setenv("DEEPGRAM_API_KEY", "dg-from-env-abcd")
    assert c.get("/api/providers").json()["deepgram"] == {"source": "server", "last4": "abcd"}


def test_fixed_mode_keys_are_read_only(tmp_path):
    c = client(tmp_path, providers="live", keys_file=None)
    assert c.get("/api/providers").json()["editable"] is False
    r = c.put("/api/providers/deepgram", json={"key": "dg-good-key-1234"})
    assert (r.status_code, r.json()) == (409, {"detail": "This install's provider keys are set on the server, not here."})


def test_keys_need_sign_in(tmp_path):
    app = create_app(tmp_path / "console", tmp_path / "agents", admin_password=PASSWORD, providers="auto",
                     keys_file=tmp_path / "keys.json")
    anonymous = TestClient(app, base_url="http://localhost:8000")
    assert anonymous.get("/api/providers").status_code == 401
    assert anonymous.put("/api/providers/deepgram", json={"key": "dg-good-key-1234"}).status_code == 401
