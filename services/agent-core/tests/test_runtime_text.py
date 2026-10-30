from voicecore.runtime.text import Chunker, TranscriptAssembler, speechify


def test_interims_then_final_give_the_final_text_once():
    a = TranscriptAssembler()
    for t in ("what is", "what is the"):
        a.partial(t)
    a.final("what is the sample rate")
    assert a.text() == "what is the sample rate"


def test_two_sentences_give_two_chunks_and_urls_and_citations_stay_whole():
    c = Chunker()
    chunks = []
    for piece in ["First sen", "tence. Sec", "ond, longer clause here."]:
        chunks += c.push(piece)
    chunks.append(c.flush())
    assert chunks == ["First sentence.", "Second, longer clause here."]
    c = Chunker()
    chunks = c.push("See https://x.y/z for details [1]. ") + [c.flush()]
    assert chunks == ["See https://x.y/z for details [1].", ""]


def test_speechify_drops_citations_and_raw_urls():
    assert speechify("Run `uv lock` [1]. See https://docs.astral.sh/uv/ [2, 3].") == "Run uv lock. See the link in the chat."
