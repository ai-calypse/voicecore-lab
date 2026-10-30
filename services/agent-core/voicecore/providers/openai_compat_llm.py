"""OpenAI-compatible streaming chat through OpenRouter (see MODEL below). SDK retries are off: retry policy is ours."""
import asyncio
import httpx
import openai
from openai import AsyncOpenAI

from voicecore import keys

from .base import Done, ProviderError, TextDelta, ToolCall, http_error

BASE_URL = "https://openrouter.ai/api/v1"
# Default since the latency work (2026-10-30, reports/latency_tuning.md): gpt-oss-120b on Cerebras through OpenRouter,
# low reasoning effort. First answer token p50 300 ms against 574 ms for gpt-4.1-nano with the same grounded prompt.
MODEL, PROVIDER, REASONING = "openai/gpt-oss-120b", "Cerebras", "low"
PRICES = {  # USD per token (input, output), OpenRouter endpoints 2026-10-30; unknown models use the dearest row
    "openai/gpt-4.1-nano": (0.10 / 1e6, 0.40 / 1e6),
    "openai/gpt-oss-120b": (0.35 / 1e6, 0.75 / 1e6),  # Cerebras
}
# One connection pool per process, kept alive for a minute: the default (5 s) closed it while the user was talking,
# so a turn paid a fresh TLS handshake to OpenRouter.
_HTTP: dict = {}  # one pool per event loop (tests run a loop per test; the server runs one)


def _http() -> httpx.AsyncClient:
    loop = asyncio.get_running_loop()
    c = _HTTP.get(loop)
    if c is None or c.is_closed:
        _HTTP.clear()  # connections of a finished loop cannot be reused
        c = _HTTP[loop] = httpx.AsyncClient(timeout=30, limits=httpx.Limits(keepalive_expiry=60))
    return c


def _estimate(messages, out_chars, model=MODEL):
    """Cost of a call that ended before its usage report (cancelled or failed): about 4 characters per token."""
    price_in, price_out = PRICES.get(model, max(PRICES.values()))
    in_chars = sum(len(str(m.get("content", ""))) for m in messages)
    return in_chars / 4 * price_in + out_chars / 4 * price_out


class OpenAICompatLLM:
    def __init__(self, reservation, key: str | None = None, model: str = MODEL, base_url: str = BASE_URL,
                 provider: str | None = PROVIDER, reasoning: str | None = REASONING):
        """provider: the OpenRouter provider to try first (others only if it fails), or None to let OpenRouter route.
        reasoning: effort for reasoning models (low/medium/high), or None for models without it."""
        self.reservation, self.model, self.base_url = reservation, model, base_url
        self.provider = provider if model == MODEL or provider != PROVIDER else None  # the Cerebras pin belongs to the default model
        self.reasoning = reasoning if model == MODEL or reasoning != REASONING else None
        self._key = key or keys.key("OPENROUTER_API_KEY") or ""
        self.client = AsyncOpenAI(api_key=self._key, base_url=base_url, max_retries=0, http_client=_http())
        self.cost_usd = 0.0
        self.calls = 0

    async def warm(self) -> None:
        """Open the HTTPS connection to OpenRouter before the first turn (a free key-info request)."""
        try:
            await _http().get(f"{self.base_url}/key", headers={"Authorization": f"Bearer {self._key}"})
        except httpx.HTTPError:
            pass

    async def stream(self, messages, tools=None, max_tokens=80):
        if self.cost_usd + _estimate(messages, max_tokens * 4, self.model) > self.reservation.amount:  # this prompt, worst-case output
            raise ProviderError("fatal", f"LLM budget for this session (${self.reservation.amount}) is used up")
        self.calls += 1
        extra = {"tools": tools} if tools else {}
        body = {"usage": {"include": True}}
        if self.provider:
            body["provider"] = {"order": [self.provider], "allow_fallbacks": True}  # slower beats failing when it is down
        if self.reasoning:
            body["reasoning"] = {"effort": self.reasoning}
        chunks, usage, out_chars = None, {}, 0
        try:
            chunks = await self.client.chat.completions.create(
                model=self.model, messages=messages, stream=True, max_tokens=max_tokens, temperature=0,
                stream_options={"include_usage": True}, extra_body=body, **extra)
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
                    price_in, price_out = PRICES.get(self.model, max(PRICES.values()))
                    usage = {"input_tokens": u.prompt_tokens, "output_tokens": u.completion_tokens,
                             "cost_usd": cost if cost is not None else u.prompt_tokens * price_in + u.completion_tokens * price_out}
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
            self.cost_usd += usage["cost_usd"] if usage else _estimate(messages, out_chars, self.model)
            if chunks is not None:
                await chunks.close()
