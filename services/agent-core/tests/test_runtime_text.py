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


def test_speechify_keeps_identifiers_with_underscores_and_hashes():
    assert speechify("Set `UV_INDEX_URL` (see issue #12).") == "Set UV_INDEX_URL (see issue #12)."


def test_speechify_says_dollar_amounts_in_full_words():
    # Aura read "$0.000083" as "zero dollars" (manual session, 2026-10-30): amounts are spoken, not left to the voice
    assert speechify("It costs $0.000083 per turn.") == "It costs zero point zero zero zero zero eight three dollars per turn."
    assert speechify("About $0.03 per 1,000 characters.") == "About 3 cents per 1,000 characters."
    assert speechify("A cap of $0.12, or $5.00 in total.") == "A cap of 12 cents, or 5 dollars in total."
    assert speechify("It was $1.04 of $5.") == "It was 1 dollar and 4 cents of 5 dollars."
    assert speechify("$1,500 and $0.0385") == "1,500 dollars and zero point zero three eight five dollars"
