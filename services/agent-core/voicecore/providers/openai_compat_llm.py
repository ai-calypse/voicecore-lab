"""OpenAI-compatible streaming chat (OpenRouter, openai/gpt-4.1-nano). SDK retries are off: retry policy is ours."""
import openai
from openai import AsyncOpenAI

from voicecore import keys

from .base import Done, ProviderError, TextDelta, ToolCall, http_error

BASE_URL = "https://openrouter.ai/api/v1"
MODEL = "openai/gpt-4.1-nano"
PRICE_IN, PRICE_OUT = 0.10 / 1e6, 0.40 / 1e6  # USD per token, OpenRouter /models 2026-10-29
CALL_ESTIMATE_USD = 0.0002  # a call is refused unless this much of the reservation is left


def _estimate(messages, out_chars):
    """Cost of a call that ended before its usage report (cancelled or failed): about 4 characters per token."""
    in_chars = sum(len(str(m.get("content", ""))) for m in messages)
    return in_chars / 4 * PRICE_IN + out_chars / 4 * PRICE_OUT


class OpenAICompatLLM:
    def __init__(self, reservation, key: str | None = None, model: str = MODEL, base_url: str = BASE_URL):
        self.reservation, self.model = reservation, model
        self.client = AsyncOpenAI(api_key=key or keys.key("OPENROUTER_API_KEY") or "", base_url=base_url, max_retries=0, timeout=30)
        self.cost_usd = 0.0
        self.calls = 0

    async def stream(self, messages, tools=None, max_tokens=80):
        if self.cost_usd + CALL_ESTIMATE_USD > self.reservation.amount:
            raise ProviderError("fatal", f"LLM budget for this session (${self.reservation.amount}) is used up")
        self.calls += 1
        extra = {"tools": tools} if tools else {}
        chunks, usage, out_chars = None, {}, 0
        try:
            chunks = await self.client.chat.completions.create(
                model=self.model, messages=messages, stream=True, max_tokens=max_tokens, temperature=0,
                stream_options={"include_usage": True}, extra_body={"usage": {"include": True}}, **extra)
            calls = {}
            async for ch in chunks:
                if ch.choices:
                    d = ch.choices[0].delta
                    if d.content:
                        out_chars += len(d.content)
                        yield TextDelta(d.content)
                    for tc in d.tool_calls or []:
                        c = calls.setdefault(tc.index, {"id": "", "name": "", "arguments": ""})
                        c["id"] = tc.id or c["id"]
                        if tc.function:
                            c["name"] += tc.function.name or ""
                            c["arguments"] += tc.function.arguments or ""
                if ch.usage:
                    u = ch.usage
                    cost = (u.model_extra or {}).get("cost")
                    usage = {"input_tokens": u.prompt_tokens, "output_tokens": u.completion_tokens,
                             "cost_usd": cost if cost is not None else u.prompt_tokens * PRICE_IN + u.completion_tokens * PRICE_OUT}
            for c in calls.values():
                yield ToolCall(c["id"], c["name"], c["arguments"])
            yield Done(usage)
        except openai.APIStatusError as e:
            raise http_error(e.status_code, "llm") from None
        except (openai.APIConnectionError, openai.APITimeoutError) as e:
            raise ProviderError("retryable", f"llm connection: {e}") from None
        except openai.APIError as e:  # an error event in the middle of the stream
            raise ProviderError("retryable", f"llm stream error: {e}") from None
        finally:  # also on cancel: the call was billed even if the usage report never arrived
            self.cost_usd += usage["cost_usd"] if usage else _estimate(messages, out_chars)
            if chunks is not None:
                await chunks.close()
