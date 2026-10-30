"""Text helpers for the generation runtime: transcript assembly, TTS chunking, speakable text."""
import re


class TranscriptAssembler:
    """Finals accumulate; an interim replaces the previous interim, so revisions never duplicate words."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.finals: list[str] = []
        self.pending = ""

    def partial(self, text: str):
        self.pending = text

    def final(self, text: str):
        self.finals.append(text)
        self.pending = ""

    def text(self) -> str:
        return " ".join(self.finals + ([self.pending] if self.pending else [])).strip()


_SENTENCE_END = re.compile(r"[.!?](?=\s)|\n")


class Chunker:
    """Cuts streaming text at sentence ends (. ! ? followed by whitespace, or a newline).

    A URL or a [n] citation has no whitespace inside it, so neither is ever split.
    """

    def __init__(self):
        self.buf = ""

    def push(self, delta: str) -> list[str]:
        self.buf += delta
        out = []
        while m := _SENTENCE_END.search(self.buf):
            chunk, self.buf = self.buf[: m.end()].strip(), self.buf[m.end() :]
            if chunk:
                out.append(chunk)
        return out

    def flush(self) -> str:
        rest, self.buf = self.buf.strip(), ""
        return rest


_CITATION = re.compile(r"\s*\[\d+(?:,\s*\d+)*\]")
_URL = re.compile(r"https?://\S+?(?=[.,;:!?)]*(?:\s|$))")  # trailing punctuation is not part of the URL


def speechify(text: str) -> str:
    """What TTS should say: no [n] citation markers, no raw URLs, no Markdown emphasis or code ticks."""
    text = _CITATION.sub("", text)
    text = _URL.sub("the link in the chat", text)
    text = re.sub(r"[*_`#]", "", text)
    return re.sub(r"\s+", " ", text).strip()
