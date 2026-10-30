"""keys.key reads the environment first, then .env (Step 09 Phase 1)."""
from voicecore import keys


def test_key_ignores_inline_comment_and_quotes(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text('DEEPGRAM_API_KEY=   # stt\nX="abc"  # c\nY=plain#notacomment\n')
    monkeypatch.setattr(keys, "ENV", env)
    for name in ("DEEPGRAM_API_KEY", "X", "Y"):
        monkeypatch.delenv(name, raising=False)
    assert keys.key("DEEPGRAM_API_KEY") is None  # an empty value with a comment is unset, not "# stt"
    assert keys.key("X") == "abc"
    assert keys.key("Y") == "plain#notacomment"  # '#' starts a comment only after whitespace
