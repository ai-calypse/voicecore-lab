"""STT reconnect after a dropped stream (Step 09 Phase 6, seam 4): mock providers, fake time."""
import asyncio

import pytest
from runtime_helpers import make, mic

from voicecore.providers.base import Final, Partial, ProviderError
from voicecore.providers.mock import MockSTT
from voicecore.runtime.session import REPROMPT, VOICE_INPUT_DOWN
from voicecore.trace import Tracer
from voicecore.turntaking.vad_fixture import FixtureVAD

pytestmark = pytest.mark.looptime


class DropOnFinalize(MockSTT):
    """Drops the moment the session asks for the final: the turn has ended, only its transcript is missing."""

    async def finalize(self):
        await super().finalize()
        self._dropped = True
        self._q.put_nowait(ProviderError("retryable", "mock stt: dropped at finalize"))


async def speak(s, frames=150):
    for k in range(frames):
        await s.on_frame(mic(k))
        await asyncio.sleep(0.02)


def names(events):
    return [(e["span"], e["event"]) for e in events]


async def test_stt_drop_reconnects_once_and_the_turn_is_answered():
    first, made, events = MockSTT(error_after_ms=600), [], []

    def factory():
        made.append(MockSTT(canned="how do I install uv?"))
        return made[-1]

    s, out = await make(stt=first, stt_factory=factory, vad=FixtureVAD([[200, 2000]]), tracer=Tracer("s-test", events.append))
    await speak(s)
    await asyncio.sleep(6)
    await s.close()
    assert len(made) == 1 and names(events).count(("stt", "reconnect")) == 1
    assert names(events).count(("stt", "error")) == 1  # one drop counts once, though send() and events() both failed
    assert [e["text"] for e in out.events("transcript.final")] == ["how do I install uv?"]
    assert out.events("agent.text") and out.events("agent.text")[0]["text"] not in (REPROMPT, VOICE_INPUT_DOWN)


async def test_reconnect_replays_the_audio_since_the_last_final():
    first, made = MockSTT(error_after_ms=600), []
    s, _ = await make(stt=first, stt_factory=lambda: made.append(MockSTT()) or made[-1], vad=FixtureVAD([[200, 2000]]))
    await speak(s)
    await s.close()
    sent_before_drop = first.audio_ms
    assert made[0].audio_ms >= sent_before_drop  # the new stream heard the start of the utterance again


async def test_drop_after_the_endpoint_promotes_the_pending_partial():
    first = DropOnFinalize([(300, Partial("how do I install uv"))])
    s, out = await make(stt=first, stt_factory=MockSTT, vad=FixtureVAD([[200, 1200]]))
    await speak(s, frames=110)
    await asyncio.sleep(1)  # well under the 5 s final wait
    await s.close()
    assert [e["text"] for e in out.events("transcript.final")] == ["how do I install uv"]


async def test_second_stt_drop_says_voice_input_is_down_once_and_typing_works():
    s, out = await make(stt=MockSTT(error_after_ms=400), stt_factory=lambda: MockSTT(error_after_ms=400),
                        vad=FixtureVAD([[200, 3000]]))
    await speak(s, frames=200)
    await asyncio.sleep(1)
    await s.on_event({"type": "text.input", "text": "hi"})
    await asyncio.sleep(1)
    await s.close()
    texts = [e["text"] for e in out.events("agent.text")]
    assert texts.count(VOICE_INPUT_DOWN) == 1 and len(texts) == 2


async def test_a_final_on_the_new_stream_is_not_duplicated_by_the_replay():
    async def run(script):
        made = []
        s, out = await make(stt=MockSTT(script, error_after_ms=600),
                            stt_factory=lambda: made.append(MockSTT(canned="install uv?")) or made[-1], vad=FixtureVAD([[200, 2000]]))
        await speak(s)
        await asyncio.sleep(6)
        await s.close()
        return made[0].audio_ms, [e["text"] for e in out.events("transcript.final")]

    heard_without_final, _ = await run([])
    heard_with_final, finals = await run([(300, Final("how do I"))])
    assert finals == ["how do I install uv?"]
    assert heard_with_final == heard_without_final - 300  # the 300 ms the first final covered were not replayed
