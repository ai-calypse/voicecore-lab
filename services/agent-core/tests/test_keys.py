"""keys.key reads the environment first, then .env (Step 09 Phase 1)."""
from voicecore import keys


def test_key_ignores_inline_comment_and_quotes(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text('DEEPGRAM_API_KEY=   # stt\nX="abc"  # c\nY=plain#notacomment\nZ="ab #cd"\nH=#s3cr3t\n'
                   'DEEPGRAM_API_KEY=real-key\n')
    monkeypatch.setattr(keys, "ENV", env)
    for name in ("DEEPGRAM_API_KEY", "X", "Y", "Z", "H"):
        monkeypatch.delenv(name, raising=False)
    assert keys.key("DEEPGRAM_API_KEY") == "real-key"  # the empty commented placeholder does not hide a later real line
    assert keys.key("X") == "abc"
    assert keys.key("Y") == "plain#notacomment"  # '#' starts a comment only after whitespace
    assert keys.key("Z") == "ab #cd"  # inside quotes nothing is a comment
    assert keys.key("H") == "#s3cr3t"  # a leading '#' with no whitespace before it is part of the value


def test_dashboard_keys_win_and_are_private(tmp_path, monkeypatch):
    """Keys set in the dashboard (VOICECORE_KEYS_FILE) take effect at the next session, over the environment."""
    path = tmp_path / "providers" / "keys.json"
    monkeypatch.setenv("VOICECORE_KEYS_FILE", str(path))
    monkeypatch.setenv("DEEPGRAM_API_KEY", "from-env")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr(keys, "ENV", tmp_path / "no.env")
    assert (keys.key("DEEPGRAM_API_KEY"), keys.voice_ready()) == ("from-env", False)
    keys.save(path, {"DEEPGRAM_API_KEY": "from-dashboard", "OPENROUTER_API_KEY": "or-dashboard"})
    assert path.stat().st_mode & 0o777 == 0o600
    assert (keys.key("DEEPGRAM_API_KEY"), keys.voice_ready()) == ("from-dashboard", True)
    keys.save(path, {"OPENROUTER_API_KEY": "or-dashboard"})  # removed in the dashboard: the environment's again
    assert keys.key("DEEPGRAM_API_KEY") == "from-env"


def test_dashboard_key_is_redacted_from_logs(tmp_path, monkeypatch):
    from voicecore.logs import Formatter

    path = tmp_path / "keys.json"
    monkeypatch.setenv("VOICECORE_KEYS_FILE", str(path))
    f = Formatter()  # made before the key exists: a key added later is still redacted
    keys.save(path, {"DEEPGRAM_API_KEY": "dg-secret-value-1234"})
    assert "dg-secret-value-1234" not in f.redact("connect failed for dg-secret-value-1234")
