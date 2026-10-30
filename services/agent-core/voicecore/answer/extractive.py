"""The free answer, for when the public budget is used up: no model call, just the closest docs section."""
from voicecore.answer.index import Index


def closest_section(index: Index):
    """question -> (reply, sources): the top retrieval hit, cited the same way the answer engine cites."""
    def answer(question: str) -> tuple[str, list[dict]]:
        hits = index.search(question, 1)
        if not hits:
            return "I couldn't find a matching section. Try other words.", []
        h = hits[0]
        return f"Closest section: {h.title}.", [{"n": 1, "id": h.id, "title": h.title, "url": h.url}]
    return answer
