"""Seam 17: log records. The JSON formatter keeps only allow-listed fields and redacts key values."""
import asyncio
import io
import json
import logging

from runtime_helpers import make
from voicecore import logs
from voicecore.providers.base import ProviderError
from voicecore.providers.mock import LLMScript, MockLLM


def emit(msg: str, fmt: logging.Formatter | None = None, **extra) -> dict:
    buf = io.StringIO()
    h = logging.StreamHandler(buf)
    h.setFormatter(fmt or logs.Formatter())
    lg = logging.getLogger("voicecore.test")
    lg.handlers, lg.propagate, lg.level = [h], False, logging.INFO
    lg.info(msg, extra=extra, exc_info=extra.pop("exc_info", None))
    return json.loads(buf.getvalue())


def test_json_log_line_keeps_only_allowed_fields():
    line = emit("hello", session_id="s-1", text="q")
    assert set(line) == {"ts", "level", "logger", "msg", "session_id"}
    assert (line["level"], line["logger"], line["msg"], line["session_id"]) == ("info", "voicecore.test", "hello", "s-1")


def test_known_key_values_are_redacted(monkeypatch):
    monkeypatch.setenv("DEEPGRAM_API_KEY", "dg-test-123")
    fmt = logs.Formatter()
    assert emit("failed dg-test-123", fmt)["msg"] == "failed [redacted]"
    assert emit("auth Token 0123456789abcdef0123 sk-or-v1-0123abcd sk_car_xyz", fmt)["msg"] == "auth Token [redacted] [redacted] [redacted]"
    assert emit("authorization: token 0123456789abcdef0123", fmt)["msg"] == "authorization: token [redacted]"  # any case
    assert emit("Token expired for this session", fmt)["msg"] == "Token expired for this session"  # short words stay
    assert emit("x", fmt, reason="dg-test-123")["reason"] == "[redacted]"  # allowed fields are redacted too


async def test_provider_error_logged_with_kind_and_provider(caplog):
    llm = MockLLM(LLMScript(tokens=[], first_token_ms=0, error=ProviderError("rate_limited", "HTTP 429")))
    s, _ = await make(llm=llm)
    with caplog.at_level(logging.WARNING, logger="voicecore.session"):
        await s.on_event({"type": "text.input", "text": "hi"})
        await asyncio.sleep(0.1)
    await s.close()
    r = next(r for r in caplog.records if r.getMessage() == "provider error")
    assert (r.provider, r.kind, r.session_id, r.gen) == ("llm", "rate_limited", "s-test", 1)


def test_traceback_kept_and_redacted(monkeypatch):
    monkeypatch.setenv("DEEPGRAM_API_KEY", "dg-test-123")
    try:
        raise RuntimeError("boom dg-test-123")
    except RuntimeError as e:
        line = emit("handler failed", logs.Formatter(), exc_info=e)
    assert line["exc"].startswith("Traceback") and "RuntimeError: boom [redacted]" in line["exc"]


def test_log_format_json_only_when_asked(monkeypatch):
    root, ws = logging.getLogger(), logging.getLogger("websockets")
    saved = root.handlers[:], root.level, ws.level
    try:
        for value, json_lines in (("json", True), ("", False), ("JSON", False), ("text", False)):
            monkeypatch.setenv("LOG_FORMAT", value)
            logs.setup()
            assert root.handlers[0].formatter.json_lines is json_lines, value
    finally:
        root.handlers[:] = saved[0]
        root.setLevel(saved[1])
        ws.setLevel(saved[2])


async def test_internal_bug_is_not_logged_as_a_provider_error(caplog):
    s, _ = await make(llm=MockLLM(LLMScript(tokens=[], first_token_ms=0, error=KeyError("oops"))))
    with caplog.at_level(logging.WARNING, logger="voicecore.session"):
        await s.on_event({"type": "text.input", "text": "hi"})
        await asyncio.sleep(0.1)
    await s.close()
    msgs = [r.getMessage() for r in caplog.records]
    assert "provider error" not in msgs and "answer failed" in msgs
    assert next(r for r in caplog.records if r.getMessage() == "answer failed").exc_info[0] is KeyError
