"""The free answer, for when the public budget is used up: no model call, just the closest docs section."""
from collections.abc import Callable

from voicecore.answer.index import Passage


def closest_section(retrieve: Callable[[str], list[Passage]]):
    """question -> (reply, sources): the top hit of the answer engine's own retrieval (so flagged and unofficial
    pages stay out, as they do for the model), cited the same way the engine cites."""
    def answer(question: str) -> tuple[str, list[dict]]:
        hits = retrieve(question)
        if not hits:
            return "I couldn't find a matching section. Try other words.", []
        h = hits[0]
        return f"Closest section: {h.title}.", [{"n": 1, "id": h.id, "title": h.title, "url": h.url}]
    return answer
