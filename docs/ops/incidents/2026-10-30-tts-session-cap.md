# 2026-10-30: speech stopped after about six answers

**Severity:** SEV2. **Status:** final. **Lead:** project owner.

## Summary

During a live test of the docs assistant, the agent stopped speaking after about six answers. Answers kept arriving as text, so the session looked healthy but was silent. The cause was Cartesia's per-session cap of 1,500 characters: once used up, every reply fell back to text without saying why. Switching text-to-speech to Deepgram Aura-2 with a 4,000-character session cap, and saying once when speech hits its cap, fixed it.

## Impact

- One live user session (the owner testing), `manual`. Exact turn count not recorded; "about six answers" before silence.
- No money lost: the cap did its job of bounding spend. The failure was that it was silent.

## Detection

A person noticed: "after few questions tts stopped". No alert existed for it; there were no metrics yet.

## Timeline (UTC)

| Time | Event |
|---|---|
| before 15:49 | the owner reports speech stopping after a few questions |
| 15:49 | fix committed: Deepgram Aura-2 by default, larger caps, a spoken-cap notice ([fc6e3b1](https://github.com/ai-calypse/voicecore-lab/commit/fc6e3b1)) |
| 15:58 | follow-up: dollar amounts read correctly ([8353aee](https://github.com/ai-calypse/voicecore-lab/commit/8353aee)) |

## Root cause

- Each live session reserved 1,500 Cartesia characters, sized for short answers. Conversational answers with citations are longer, so six of them used it up.
- When the reservation ran out, the TTS adapter raised a `fatal` error and the session answered in text only, which was the designed fallback. The fallback had no user-facing message, so silence looked like a bug.
- The project's Cartesia credits were nearly used up anyway (15,531 of 16,000), so a bigger Cartesia cap was not an option.

## What went well, and what did not

- Went well: the budget cap held, and text answers kept working.
- Did not: a cap that degrades service must say so. Nothing measured how often TTS hit its cap.
- Lucky: it happened in a test, not a demo.

## Action items

| Action | Owner | Link | Status |
|---|---|---|---|
| Deepgram Aura-2 TTS by default; 4,000-character session cap | owner | [fc6e3b1](https://github.com/ai-calypse/voicecore-lab/commit/fc6e3b1) | done |
| Say once, as text, when speech hits its session cap (`VOICE_OFF`) | owner | [fc6e3b1](https://github.com/ai-calypse/voicecore-lab/commit/fc6e3b1) | done |
| Count provider errors by kind, so a `fatal` TTS cap shows up | owner | Step 09 Phase 5 (`voicecore_provider_errors_total`) | done |
| Alert when provider errors pass 2% of calls | owner | Step 09 Phase 5 (`ProviderErrorsHigh`) | done |

## Blameless note

The cap and the fallback both worked as designed. The gap was a design decision, a silent fallback, that nobody had seen fail before.
