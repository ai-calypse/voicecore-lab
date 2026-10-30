"""Live adapters are only built against a budget reservation, so nothing can spend outside the guard."""
from voicecore import budget

POOL = {"stt": "usd", "llm": "usd", "tts": "cartesia_credits", "deepgram_tts": "usd"}  # "tts" is Cartesia


def make_live(kind: str, reservation: budget.Reservation | None, **kwargs):
    if reservation is None or reservation.pool != POOL[kind]:
        raise budget.BudgetExceeded(f"live {kind} needs a reservation in pool {POOL[kind]}")
    if kind == "stt":
        from .deepgram_stt import DeepgramSTT

        return DeepgramSTT(reservation, **kwargs)
    if kind == "llm":
        from .openai_compat_llm import OpenAICompatLLM

        return OpenAICompatLLM(reservation, **kwargs)
    if kind == "deepgram_tts":
        from .deepgram_tts import DeepgramTTS

        return DeepgramTTS(reservation, **kwargs)
    from .cartesia_tts import CartesiaTTS

    return CartesiaTTS(reservation, **kwargs)
