"""S05-T03 recovery paths (seam 4): mock providers, fake time."""
import asyncio

import pytest
from runtime_helpers import make, mic

from voicecore.providers.base import ProviderError
from voicecore.providers.mock import LLMScript, MockLLM, MockSTT, MockTTS
from voicecore.runtime.session import BUSY, REPROMPT, State
from voicecore.turntaking.vad_fixture import FixtureVAD

pytestmark = pytest.mark.looptime


async def test_no_stt_final_5s_after_endpoint_reprompts():
    s, out = await make(stt=MockSTT(), vad=FixtureVAD([[200, 1200]]))  # the STT never returns text
    for k in range(110):
        await s.on_frame(mic(k))
        await asyncio.sleep(0.02)
    await asyncio.sleep(4.5)
    assert out.events("agent.text") == []
    await asyncio.sleep(1)
    assert out.events("agent.text") == [{"type": "agent.text", "gen": 1, "text": REPROMPT}]
    await s.close()


class DroppingTTS(MockTTS):
    """Fails before any audio, like a TTS socket that closed."""

    async def synth(self, gen, text, last):
        raise ProviderError("retryable", "cartesia closed")


async def test_tts_disconnect_sends_the_text_answer_and_retries_tts_once_on_a_new_stream():
    made = []

    def factory():
        made.append(MockTTS(first_audio_ms=5))
        return made[-1]

    s, out = await make(tts=DroppingTTS(), tts_factory=factory)
    await s.on_event({"type": "text.input", "text": "hi"})
    await asyncio.sleep(5)
    assert [e["gen"] for e in out.events("agent.text")] == [1]
    assert len(made) == 1 and made[0].texts  # one retry, on a fresh stream, with the answer text
    assert out.frames() and out.frames()[-1].flags == 1  # and it was spoken
    await s.close()


async def test_http_429_backs_off_1_2_4s_then_says_it_is_busy():
    llm = MockLLM(LLMScript(tokens=[], first_token_ms=0, error=ProviderError("rate_limited", "HTTP 429")))
    s, out = await make(llm=llm)
    await s.on_event({"type": "text.input", "text": "hi"})
    await asyncio.sleep(6.9)
    assert len(llm.calls) == 3 and out.events("agent.text") == []  # tries at 0, 1, 3 s
    await asyncio.sleep(0.2)
    assert len(llm.calls) == 4  # and at 7 s
    await asyncio.sleep(1)
    assert out.events("agent.text") == [{"type": "agent.text", "gen": 1, "text": BUSY}]
    await s.close()


async def test_429_then_success_answers_normally():
    calls = []

    def script(messages):
        calls.append(1)
        return LLMScript(tokens=["Fine."], first_token_ms=0, error=ProviderError("rate_limited", "429") if len(calls) == 1 else None)

    s, out = await make(llm=MockLLM(script))
    await s.on_event({"type": "text.input", "text": "hi"})
    await asyncio.sleep(3)
    assert out.events("agent.text") == [{"type": "agent.text", "gen": 1, "text": "Fine."}]
    await s.close()


async def test_client_paused_over_30s_during_a_generation_cancels_it():
    s, out = await make(tts=MockTTS(ms_per_char=1000))  # a long answer
    await s.on_event({"type": "text.input", "text": "hi"})
    await asyncio.sleep(1)
    await s.on_event({"type": "client.paused"})
    await asyncio.sleep(29)
    assert out.events("agent.cancel") == []
    await asyncio.sleep(2)
    assert out.events("agent.cancel") == [{"type": "agent.cancel", "gen": 1}]
    await s.close()


async def test_client_resuming_playout_before_30s_keeps_the_generation():
    s, out = await make(tts=MockTTS(ms_per_char=1000))
    await s.on_event({"type": "text.input", "text": "hi"})
    await s.on_event({"type": "client.paused"})
    await asyncio.sleep(20)
    await s.on_event({"type": "client.resumed_playout"})
    await asyncio.sleep(20)
    assert out.events("agent.cancel") == []
    await s.close()


async def test_mic_revoked_stops_voice_but_text_still_works():
    stt = MockSTT()
    s, out = await make(stt=stt, vad=FixtureVAD([[1000, 5000]]))
    for k in range(10):  # 200 ms of silence on stream 1, then the user turns the mic off
        await s.on_frame(mic(k))
        await asyncio.sleep(0.02)
    await s.on_event({"type": "mic.revoked"})
    for k in range(10, 150):  # late frames of the revoked stream (speech by the labels) are ignored
        await s.on_frame(mic(k))
        await asyncio.sleep(0.02)
    assert stt.audio_ms == 0 and out.events("user.speech_started") == []
    await s.on_event({"type": "text.input", "text": "hi"})
    await asyncio.sleep(3)
    assert [e["gen"] for e in out.events("agent.text")] == [1]
    await s.close()


# Code review 2026-10-30 (Steps 04-05) regressions

class LateFailingTTS(MockTTS):
    """synth succeeds; the error arrives later from the socket, as Cartesia reports it."""

    async def audio(self):
        await asyncio.sleep(0.5)
        raise ProviderError("retryable", "cartesia error frame")
        yield  # pragma: no cover


async def test_a_late_tts_error_after_the_text_was_sent_is_retried_once():
    made = []

    def factory():
        made.append(MockTTS(first_audio_ms=5))
        return made[-1]

    s, out = await make(tts=LateFailingTTS(), tts_factory=factory, llm=MockLLM(LLMScript(tokens=["Short."], first_token_ms=10)))
    await s.on_event({"type": "text.input", "text": "hi"})
    await asyncio.sleep(5)
    assert len(made) == 1 and out.frames() and out.frames()[-1].flags == 1
    await s.close()


async def test_the_pause_timer_follows_the_current_generation():
    s, out = await make(tts=MockTTS(ms_per_char=1000))
    await s.on_event({"type": "text.input", "text": "first"})
    await s.on_event({"type": "client.paused"})
    await asyncio.sleep(10)
    await s.on_event({"type": "text.input", "text": "second"})  # gen 1 superseded; its timer must not linger
    await asyncio.sleep(0.1)
    await s.on_event({"type": "client.paused"})
    await asyncio.sleep(25)
    assert [e["gen"] for e in out.events("agent.cancel")] == [1]
    await asyncio.sleep(6)
    assert [e["gen"] for e in out.events("agent.cancel")] == [1, 2]
    await s.close()


async def test_revoking_the_mic_mid_utterance_drops_the_half_turn():
    stt = MockSTT()
    s, out = await make(stt=stt, vad=FixtureVAD([[0, 5000]]))
    for k in range(25):
        await s.on_frame(mic(k))
        await asyncio.sleep(0.02)
    assert s.state == State.USER_SPEAKING
    await s.on_event({"type": "mic.revoked"})
    assert s.state == State.LISTENING and s.transcript.text() == ""
    await s.close()


async def test_text_input_that_is_not_a_short_string_is_ignored():
    s, out = await make()
    for bad in ([{"type": "image_url", "image_url": {"url": "https://x"}}], "a" * 501, "   ", None):
        await s.on_event({"type": "text.input", "text": bad})
    await asyncio.sleep(2)
    assert out.events("agent.generation_started") == [] and s.history == []
    await s.close()
