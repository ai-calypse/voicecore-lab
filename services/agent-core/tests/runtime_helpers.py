"""Shared helpers for runtime tests: capture what a Session sends and feed it frames."""
import json

import numpy as np

from voicecore import protocol
from voicecore.providers.mock import LLMScript, MockLLM, MockTTS
from voicecore.runtime.session import Session


class Out:
    """Records every outbound message with the session's newest generation at send time."""

    def __init__(self):
        self.msgs: list[tuple[bytes | str, int]] = []
        self.session: Session | None = None

    async def __call__(self, m):
        self.msgs.append((m, self.session.gen if self.session else 0))

    def events(self, type: str | None = None) -> list[dict]:
        es = [json.loads(m) for m, _ in self.msgs if isinstance(m, str)]
        return [e for e in es if type is None or e["type"] == type]

    def frames(self) -> list[protocol.Frame]:
        return [protocol.decode_frame(m) for m, _ in self.msgs if isinstance(m, bytes)]

    def kinds(self) -> list[str]:
        """Event types and 'frame:<gen>' in send order."""
        return [json.loads(m)["type"] if isinstance(m, str) else f"frame:{protocol.decode_frame(m).generation_id}" for m, _ in self.msgs]


async def make(llm=None, tts=None, **kw) -> tuple[Session, Out]:
    out = Out()
    s = Session("s-test", llm=llm or MockLLM(LLMScript(tokens=["Run ", "uv ", "init. ", "Then ", "uv ", "add."])),
                tts=tts or MockTTS(), send=out, **kw)
    out.session = s
    await s.start()
    return s, out


def mic(seq: int, value: int = 0) -> protocol.Frame:
    return protocol.Frame(protocol.KIND_MIC, 0, 1, seq, seq * 20_000, 0, np.full(320, value, np.int16))
