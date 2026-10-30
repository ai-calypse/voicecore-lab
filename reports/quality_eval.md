# Quality eval (S06-T05)

**Date:** 2026-10-30 UTC. Text-only LLM, no TTS credits.

## Speech recognition: WER on holdout audio (`live-provider`)

Command: `uv run python harness/wer_eval.py` → [`wer_holdout.json`](wer_holdout.json). Deepgram nova-3 with keyterms, audio paced in real time, closed with `CloseStream`. References are the LibriSpeech transcripts and the answer-key question text. Normalisation lowercases and removes punctuation; there is no other text normalisation.

| Clips | n | WER |
|---|---:|---:|
| **all** | 25 | **6.5 %** |
| docs questions (Aura holdout voice) | 15 | 3.2 % |
| LibriSpeech clean | 3 | 1.7 % |
| slow 0.8× | 1 | 0.0 % |
| mid-pause 600 ms | 2 | 4.2 % |
| noisy 5 dB | 2 | 10.8 % |
| noisy 10 dB | 2 | 26.7 % |

- **Noisy 10 dB:** part of this WER is the reference, not the recogniser. LibriSpeech keeps dialect spelling ("an i dunno which is worst dyin"), and Deepgram writes standard English. With 2 clips per noisy category, these rows are anecdotes.
- **Method finding:** streaming the audio faster than real time and then closing lost the last words of long clips, which made the overall WER 9.9 % ([`wer_holdout_fast_streaming.json`](wer_holdout_fast_streaming.json)). A same-clip probe showed paced audio is complete, while `Finalize` before close only partly helps. Live sessions are always paced, so the product is not affected.

## Answers (live, holdout and adversarial)

From S04-T05 ([`docs_eval.md`](docs_eval.md), run `20261030T013455Z`):
- **Refusal accuracy:** 15 / 15.
- **Citations supporting the answer:** 15 / 15.
- **`must_contain` terms present:** 10 / 11.
- **Adversarial:** 13 / 15 with no adversarial claims leaked; fresh set 6 / 6.

## Manual audit — not done yet

[`answer_audit.md`](answer_audit.md) lists 20 answers (15 holdout, 5 adversarial) with a blank Verdict column. The plan has the project owner audit them by hand, so this stays open until filled in.
