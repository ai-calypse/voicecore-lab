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


_MONEY = re.compile(r"\$(\d[\d,]*)(?:\.(\d+))?")
_DIGITS = "zero one two three four five six seven eight nine".split()


def _say_money(m: re.Match) -> str:
    """$1.04 -> "1 dollar and 4 cents", $0.03 -> "3 cents", $0.000083 -> "zero point zero zero zero zero eight three
    dollars" (Aura read that one as "zero dollars")."""
    whole, frac = m.group(1), m.group(2) or ""
    if len(frac.rstrip("0")) > 2:  # less than a cent: say every digit
        return f"{'zero' if int(whole.replace(',', '')) == 0 else whole} point {' '.join(_DIGITS[int(d)] for d in frac)} dollars"
    dollars, cents = int(whole.replace(",", "")), int((frac + "00")[:2])
    parts = [f"{whole} dollar{'' if dollars == 1 else 's'}"] if dollars else []
    parts += [f"{cents} cent{'' if cents == 1 else 's'}"] if cents else []
    return " and ".join(parts) or "zero dollars"


def speechify(text: str) -> str:
    """What TTS should say: no [n] citation markers, no raw URLs, no Markdown emphasis or code ticks."""
    text = _CITATION.sub("", text)
    text = _MONEY.sub(_say_money, text)
    text = _URL.sub("the link in the chat", text)
    text = re.sub(r"\*\*|\*|`", "", text)  # emphasis and code ticks; underscores and # stay (UV_INDEX_URL, issue #12)
    text = re.sub(r"(?m)^#+\s*", "", text)  # Markdown headings
    return re.sub(r"\s+", " ", text).strip()
