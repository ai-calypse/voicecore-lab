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
